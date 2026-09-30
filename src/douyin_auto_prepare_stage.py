from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException

from douyin_browser_automation import build_browser_config, open_or_attach
from douyin_live_collector import (
    activate_best_existing_tab,
    click_navigation_text,
    navigation_steps,
    open_live_dashboard,
    page_kind_from_url,
    require_entry_url,
    select_dropdown_option,
    wait_for_step_feedback,
)


@dataclass
class PrepareStageResult:
    status: str
    message: str
    target: str
    current_url: str | None
    title: str | None
    active_tab_info: dict[str, Any] | None
    actions: list[str]


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return navigation_steps(payload)


def parse_config_date(raw: Any) -> date:
    """Accept common human-entered date spacing and return a real date."""
    match = re.fullmatch(r"\s*(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*", str(raw))
    if not match:
        raise ValueError(f"Invalid configured date: {raw!r}")
    return date(*(int(part) for part in match.groups()))


def requested_date_window(payload: dict[str, Any]) -> tuple[date, date] | None:
    """Return the configured date window, accepting single-day and range runs."""
    raw_start = payload.get("start_date") or payload.get("target_date")
    raw_end = payload.get("end_date") or raw_start
    if not raw_start or not raw_end:
        return None
    try:
        start = parse_config_date(raw_start)
        end = parse_config_date(raw_end)
    except ValueError:
        return None
    return (min(start, end), max(start, end))


def automatic_date_option(payload: dict[str, Any]) -> tuple[str, str]:
    """Choose an exact custom range when it fits the list page's 31-day limit."""
    window = requested_date_window(payload)
    if not window:
        return "近7天", "未识别目标日期，保留近7天"

    start, end = window
    days_ago = max((date.today() - start).days, 0)
    range_days = (end - start).days + 1
    if range_days <= 31 and start <= date.today():
        return "自定义", f"精确筛选 {start.isoformat()} 至 {end.isoformat()}"
    if days_ago <= 30 and range_days <= 30:
        return "近30天", "目标日期超出自定义单次范围，自动扩大为近30天"
    # The page exposes a "更多" range selector for historical dates.  It is
    # intentionally selected here instead of silently leaving the 7-day filter.
    return "更多", "目标日期超出近30天，自动打开更多日期范围"


def select_custom_date_window(driver: Any, start: date, end: date) -> None:
    """Select an exact date range in the Luopan custom calendar and commit it."""
    open_custom_date_picker(driver)

    for target in (start, end):
        cell = expose_custom_calendar_date(driver, target)
        driver.execute_script("arguments[0].click();", cell)
        time.sleep(0.5)

    # Newer Aurora pickers commit and close after the end date is selected.
    # Older builds still require a real outside click, so only use it when the
    # calendar remains open; this avoids an extra click on the refreshed page.
    if custom_date_picker_is_open(driver):
        ActionChains(driver).move_by_offset(15, 300).click().perform()
    time.sleep(3.0)


def calendar_month_key(value: date) -> int:
    return value.year * 12 + value.month


def custom_date_picker_is_open(driver: Any) -> bool:
    return bool(
        driver.execute_script(
            """
            return Array.from(document.querySelectorAll(
                'td.aurora-picker-cell-in-view[title], ' +
                'td.ecom-picker-cell-in-view[title], ' +
                'td.ant-picker-cell-in-view[title]'
            )).some((cell) => cell.offsetParent !== null);
            """
        )
    )


def open_custom_date_picker(driver: Any, timeout_seconds: float = 8.0) -> None:
    """Open the custom picker without confusing its trigger with hidden menu text."""
    if custom_date_picker_is_open(driver):
        return

    trigger_selectors = (
        ".aurora-dropdown-trigger",
        ".ecom-dropdown-trigger",
        ".ant-dropdown-trigger",
    )
    trigger = None
    for selector in trigger_selectors:
        for candidate in driver.find_elements(By.CSS_SELECTOR, selector):
            if candidate.is_displayed() and (candidate.text or "").strip() == "自定义":
                trigger = candidate
                break
        if trigger is not None:
            break

    if trigger is None:
        # Compatibility fallback for older Luopan builds. Restrict the match to
        # visible exact text instead of the former page-wide contains() XPath.
        candidates = driver.find_elements(By.XPATH, "//*[normalize-space(.)='自定义']")
        trigger = next((item for item in reversed(candidates) if item.is_displayed()), None)
    if trigger is None:
        raise RuntimeError("Custom date filter trigger was not found.")

    driver.execute_script("arguments[0].click();", trigger)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if custom_date_picker_is_open(driver):
            return
        time.sleep(0.2)
    raise RuntimeError("Custom date picker did not open after clicking its trigger.")


def visible_custom_calendar_months(driver: Any) -> list[int]:
    """Return the real months displayed by the open two-panel date picker."""
    selectors = (
        "td.aurora-picker-cell-in-view[title]",
        "td.ecom-picker-cell-in-view[title]",
        "td.ant-picker-cell-in-view[title]",
    )
    month_keys: set[int] = set()
    for selector in selectors:
        for cell in driver.find_elements(By.CSS_SELECTOR, selector):
            if not cell.is_displayed():
                continue
            raw_date = cell.get_attribute("title") or ""
            try:
                month_keys.add(calendar_month_key(date.fromisoformat(raw_date)))
            except ValueError:
                continue
        if month_keys:
            break
    return sorted(month_keys)


def click_custom_calendar_month_navigation(driver: Any, direction: str) -> None:
    selectors = {
        "previous": (
            ".aurora-picker-header-prev-btn",
            ".ecom-picker-header-prev-btn",
            ".ant-picker-header-prev-btn",
            "button[aria-label='Previous month']",
            "button[aria-label='上个月']",
            "button[title='上个月']",
        ),
        "next": (
            ".aurora-picker-header-next-btn",
            ".ecom-picker-header-next-btn",
            ".ant-picker-header-next-btn",
            "button[aria-label='Next month']",
            "button[aria-label='下个月']",
            "button[title='下个月']",
        ),
    }
    for selector in selectors[direction]:
        for button in driver.find_elements(By.CSS_SELECTOR, selector):
            if button.is_displayed() and button.is_enabled():
                driver.execute_script("arguments[0].click();", button)
                return
    raise RuntimeError(f"Custom calendar {direction} month button was not found.")


def expose_custom_calendar_date(driver: Any, target: date, max_month_steps: int = 60) -> Any:
    """Navigate the open custom calendar until the requested date is selectable."""
    target_title = target.isoformat()
    selector = ", ".join(
        (
            f"td.aurora-picker-cell-in-view[title='{target_title}']"
            ":not(.aurora-picker-cell-disabled)",
            f"td.ecom-picker-cell-in-view[title='{target_title}']"
            ":not(.ecom-picker-cell-disabled)",
            f"td.ant-picker-cell-in-view[title='{target_title}']"
            ":not(.ant-picker-cell-disabled)",
        )
    )
    target_month = calendar_month_key(target)

    for _ in range(max_month_steps + 1):
        for cell in driver.find_elements(By.CSS_SELECTOR, selector):
            if cell.is_displayed():
                return cell

        visible_months = visible_custom_calendar_months(driver)
        if not visible_months:
            time.sleep(0.4)
            continue
        if target_month < visible_months[0]:
            direction = "previous"
        elif target_month > visible_months[-1]:
            direction = "next"
        else:
            # The target month is rendered but its cells may still be updating.
            time.sleep(0.4)
            continue

        before = visible_months
        click_custom_calendar_month_navigation(driver, direction)
        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = visible_custom_calendar_months(driver)
            if current and current != before:
                break
            time.sleep(0.15)

    raise RuntimeError(
        f"Custom calendar could not navigate to {target.isoformat()} "
        f"within {max_month_steps} month changes."
    )


def open_entry_page_with_recovery(driver: Any, entry_url: str, attempts: int = 2) -> None:
    """Open Luopan without discarding a page that finishes after Selenium times out."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            driver.get(entry_url)
            return
        except TimeoutException as exc:
            last_error = exc
            # The renderer commonly completes the SPA shortly after WebDriver's
            # navigation timeout. Stop only remaining subresources, then check
            # whether the page is usable before requesting it a second time.
            try:
                driver.execute_cdp_cmd("Page.stopLoading", {})
            except WebDriverException:
                pass
            time.sleep(3.0)
            if page_kind_from_url(driver.current_url or "") == "list":
                return
            if attempt < attempts:
                time.sleep(2.0)
        except WebDriverException as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2.0)
    raise RuntimeError(f"Unable to open the Luopan entry page after {attempts} attempts: {last_error}")


def ensure_list_page(driver: Any, payload: dict[str, Any]) -> tuple[str, list[str], dict[str, Any] | None]:
    actions: list[str] = []
    active = activate_best_existing_tab(driver, preferred_kind="list")
    if page_kind_from_url(driver.current_url) == "list":
        # Reusing a list tab must still reapply account/date filters; otherwise
        # a stale "近7天" selection silently excludes older target sessions.
        actions.append("reuse_list_page")
    else:
        open_entry_page_with_recovery(driver, require_entry_url(payload))
        time.sleep(2.0)
        actions.append("open_entry_url")

    for step in normalize_steps(payload):
        action = step.get("action", "click")
        if action == "click":
            if page_kind_from_url(driver.current_url or "") == "list" and step.get("label") in {
                "直播",
                "直播概览及列表",
                "直播间列表",
            }:
                actions.append(f"skip_navigation_already_on_list: {step.get('label')}")
                continue
            click_navigation_text(driver, step["text"])
            actions.append(step.get("label") or step["text"])
            wait_for_step_feedback(driver, step["text"])
        elif action == "select_option":
            option_text = step["option_text"]
            reason = ""
            if step.get("label") == "时间范围":
                option_text, reason = automatic_date_option(payload)
            if step.get("label") == "时间范围" and option_text == "自定义":
                window = requested_date_window(payload)
                if window is None:
                    raise RuntimeError("Custom date filtering requires a valid target date.")
                select_custom_date_window(driver, *window)
            else:
                select_dropdown_option(driver, step["trigger_text"], option_text)
            action_text = f"{step.get('label') or 'select'}: {step['trigger_text']} -> {option_text}"
            actions.append(f"{action_text} ({reason})" if reason else action_text)
            wait_for_step_feedback(driver, option_text)
        time.sleep(1.0)

    active = activate_best_existing_tab(driver, preferred_kind="list")
    return ("ready" if page_kind_from_url(driver.current_url) == "list" else "wrong_page"), actions, active


def open_professional_from_dashboard(driver: Any) -> bool:
    current_url = driver.current_url or ""
    if "/screen/shop/main" not in current_url:
        return False
    professional_url = current_url.replace("/screen/shop/main", "/screen/live/shop")
    driver.get(professional_url)
    time.sleep(3.0)
    return "/screen/live/shop" in (driver.current_url or "")


def ensure_professional_page(driver: Any, payload: dict[str, Any]) -> tuple[str, list[str], dict[str, Any] | None]:
    del payload
    actions: list[str] = []
    active = activate_best_existing_tab(driver, preferred_kind="professional_dashboard")
    current_kind = page_kind_from_url(driver.current_url)
    if current_kind == "professional_dashboard":
        return "ready", actions, active

    if current_kind == "detail":
        result = open_live_dashboard(driver)
        if result:
            actions.append("open_live_dashboard")
            active = activate_best_existing_tab(driver, preferred_kind="dashboard")
            current_kind = page_kind_from_url(driver.current_url)

    if current_kind != "dashboard":
        active = activate_best_existing_tab(driver, preferred_kind="dashboard")
        current_kind = page_kind_from_url(driver.current_url)

    if current_kind == "dashboard" and open_professional_from_dashboard(driver):
        actions.append("switch_to_professional_dashboard")

    active = activate_best_existing_tab(driver, preferred_kind="professional_dashboard")
    return ("ready" if page_kind_from_url(driver.current_url) == "professional_dashboard" else "wrong_page"), actions, active


def click_first_existing(driver: Any, labels: list[str], timeout_seconds: float = 8.0) -> str | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        remaining = deadline - time.time()
        for label in labels:
            try:
                click_navigation_text(driver, label, timeout_seconds=max(min(remaining, 1.5), 0.2))
                return label
            except TimeoutException:
                continue
        time.sleep(0.3)
    return None


def extract_live_room_id(url: str) -> str | None:
    if not url:
        return None
    try:
        query = parse_qs(urlparse(url).query)
        values = query.get("live_room_id") or []
        return values[0] if values else None
    except Exception:
        return None


def find_qianchuan_href(driver: Any) -> str | None:
    script = """
const nodes = Array.from(document.querySelectorAll('a, button, [role="button"], div, span'));
for (const node of nodes) {
  const text = (node.innerText || node.textContent || '').trim();
  const href = node.href || node.getAttribute('href') || node.getAttribute('data-href') || '';
  const onclick = node.getAttribute('onclick') || '';
  const blob = `${text} ${href} ${onclick}`;
  if (blob.includes('qianchuan.jinritemai.com')) {
    return href || blob;
  }
}
return '';
"""
    try:
        value = driver.execute_script(script) or ""
    except Exception:
        return None
    value = str(value).strip()
    if "qianchuan.jinritemai.com" not in value:
        return None
    start = value.find("https://qianchuan.jinritemai.com")
    if start == -1:
        return None
    return value[start:].split()[0]


def open_qianchuan_from_previous_result(driver: Any) -> bool:
    previous_path = ROOT / "output" / "douyin_qianchuan_stage_result.json"
    if not previous_path.exists():
        return False
    try:
        payload = json.loads(previous_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False

    previous_url = (payload.get("current_url") or "").strip()
    if "qianchuan.jinritemai.com" not in previous_url:
        return False

    current_live_room_id = extract_live_room_id(driver.current_url or "")
    if current_live_room_id:
        parsed = urlparse(previous_url)
        query = parse_qs(parsed.query)
        query["live_room_id"] = [current_live_room_id]
        previous_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    driver.get(previous_url)
    time.sleep(3.0)
    return "qianchuan.jinritemai.com" in (driver.current_url or "")


def select_qianchuan_tab(driver: Any) -> dict[str, Any] | None:
    handles = list(driver.window_handles)
    candidates: list[dict[str, Any]] = []
    target = None
    for handle in handles:
        driver.switch_to.window(handle)
        url = driver.current_url
        title = driver.title
        item = {"handle": handle, "url": url, "title": title}
        candidates.append(item)
        if "qianchuan.jinritemai.com" in (url or ""):
            target = item
    if not target:
        return None
    driver.switch_to.window(target["handle"])
    return {
        "selected_url": target["url"],
        "selected_title": target["title"],
        "candidate_count": len(candidates),
        "page_kind": "qianchuan_dashboard",
        "preferred_kind": "qianchuan_dashboard",
    }


def ensure_qianchuan_page(driver: Any, payload: dict[str, Any]) -> tuple[str, list[str], dict[str, Any] | None]:
    actions: list[str] = []

    for _ in range(2):
        active = select_qianchuan_tab(driver)
        current_url = driver.current_url or ""
        if active and "qianchuan.jinritemai.com" in current_url:
            return "ready", actions, active

    active = activate_best_existing_tab(driver, preferred_kind="professional_dashboard")
    if page_kind_from_url(driver.current_url) != "professional_dashboard":
        status, nested_actions, active = ensure_professional_page(driver, payload)
        actions.extend(nested_actions)
        if status != "ready":
            return "wrong_page", actions, active

    before_handles = list(driver.window_handles)
    clicked_enter = click_first_existing(driver, ["立即进入", "绔嬪嵆杩涘叆"], timeout_seconds=8.0)
    if not clicked_enter:
        clicked = click_first_existing(driver, ["千川", "鍗冨窛"], timeout_seconds=3.0)
        if clicked:
            actions.append("open_qianchuan_panel")
            time.sleep(1.0)
            clicked_enter = click_first_existing(driver, ["立即进入", "绔嬪嵆杩涘叆"], timeout_seconds=5.0)
    if clicked_enter:
        actions.append("enter_qianchuan_dashboard")
        time.sleep(3.0)
        after_handles = list(driver.window_handles)
        if len(after_handles) > len(before_handles):
            new_handle = next((handle for handle in after_handles if handle not in before_handles), None)
            if new_handle:
                driver.switch_to.window(new_handle)

    if "qianchuan.jinritemai.com" not in (driver.current_url or ""):
        href = find_qianchuan_href(driver)
        if href:
            driver.get(href)
            actions.append("open_qianchuan_href")
            time.sleep(3.0)

    if "qianchuan.jinritemai.com" not in (driver.current_url or ""):
        if open_qianchuan_from_previous_result(driver):
            actions.append("open_qianchuan_from_previous_result")

    active = select_qianchuan_tab(driver)
    return ("ready" if active and "qianchuan.jinritemai.com" in (driver.current_url or "") else "wrong_page"), actions, active


def main() -> int:
    parser = argparse.ArgumentParser(description="Automatically prepare a required Douyin workflow page.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--target", choices=["list", "professional", "qianchuan"], required=True)
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        if args.target == "list":
            status, actions, active = ensure_list_page(driver, payload)
            message = "Automatically prepared the live room list page."
        elif args.target == "professional":
            status, actions, active = ensure_professional_page(driver, payload)
            message = "Automatically prepared the professional dashboard page."
        else:
            status, actions, active = ensure_qianchuan_page(driver, payload)
            message = "Automatically prepared the Qianchuan core data page."

        if status != "ready":
            message = f"Could not automatically prepare the {args.target} page."

        result = PrepareStageResult(
            status=status,
            message=message,
            target=args.target,
            current_url=driver.current_url,
            title=driver.title,
            active_tab_info=active,
            actions=actions,
        )
        result_json = json.dumps(asdict(result), ensure_ascii=False, indent=2)
        if args.result_output:
            output_path = Path(args.result_output).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result_json, encoding="utf-8-sig")
        print(result_json)
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
