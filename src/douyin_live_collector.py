from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from douyin_browser_automation import build_browser_config, open_or_attach
from douyin_workflow_runner import build_plan, load_launch_config


@dataclass
class CollectorResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    target_dates: list[str]
    clicked_steps: list[str]
    matched_rows: list[dict[str, Any]]
    row_samples: list[str]
    detail_candidates: list[dict[str, Any]]
    detail_open_result: dict[str, Any] | None
    detail_page_state: dict[str, Any] | None
    active_tab_info: dict[str, Any] | None
    dashboard_open_result: dict[str, Any] | None
    core_metrics: dict[str, Any]


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def require_entry_url(payload: dict[str, Any]) -> str:
    entry_url = (payload.get("luopan_entry_url") or "").strip()
    if not entry_url:
        bookmark_label = payload.get("luopan_bookmark_label") or "罗盘入口"
        raise ValueError(
            "缺少 luopan_entry_url。当前自动化使用 Selenium，只能操作网页内容，不能直接点击浏览器书签栏。"
            f"请把书签“{bookmark_label}”对应的实际入口 URL 填入配置后再继续。"
        )
    return entry_url


def navigation_steps(payload: dict[str, Any]) -> list[dict[str, Any]]:
    steps = payload.get("navigation_steps") or []
    valid_steps: list[dict[str, Any]] = []
    for step in steps:
        action = step.get("action", "click")
        if action == "click" and step.get("text"):
            valid_steps.append(step)
        elif action == "select_option" and step.get("trigger_text") and step.get("option_text"):
            valid_steps.append(step)
    return valid_steps


def should_resume_from_current_page(payload: dict[str, Any]) -> bool:
    return bool(payload.get("resume_from_current_page", False))


def page_kind_from_url(url: str) -> str:
    if "/screen/live/shop" in url:
        return "professional_dashboard"
    if "/screen/shop/main" in url:
        return "dashboard"
    if "/screen/" in url:
        return "dashboard"
    if "live-detail" in url:
        return "detail"
    if "live-overview" in url or "live-list" in url:
        return "list"
    return "unknown"


def activate_best_existing_tab(driver: Any, preferred_kind: str | None = None) -> dict[str, Any]:
    handles = list(driver.window_handles)
    try:
        original_handle = driver.current_window_handle
    except Exception:
        original_handle = None
    candidates: list[dict[str, Any]] = []

    for handle in handles:
        driver.switch_to.window(handle)
        try:
            current_url = driver.current_url
        except Exception:
            current_url = ""
        try:
            title = driver.title
        except Exception:
            title = ""

        score = 0
        if "live-overview" in current_url:
            score += 3
        if "live-detail" in current_url:
            score += 4
        if "/screen/" in current_url:
            score += 5
        if "/screen/live/shop" in current_url:
            score += 2
        if "live-list" in current_url:
            score += 2
        if "直播概览" in title:
            score += 2
        if "直播间详情" in title:
            score += 3
        if "直播大屏" in title:
            score += 4
        if "专业版" in title:
            score += 2
        if "compass.jinritemai.com" in current_url:
            score += 1

        kind = page_kind_from_url(current_url)
        if preferred_kind and kind == preferred_kind:
            score += 10
        if handle == original_handle:
            score += 1

        candidates.append(
            {
                "handle": handle,
                "url": current_url,
                "title": title,
                "score": score,
                "kind": kind,
            }
        )

    best = max(candidates, key=lambda item: item["score"], default=None)
    if best:
        driver.switch_to.window(best["handle"])
        return {
            "selected_url": best["url"],
            "selected_title": best["title"],
            "candidate_count": len(candidates),
            "page_kind": best["kind"],
            "preferred_kind": preferred_kind,
        }

    return {
        "selected_url": driver.current_url,
        "selected_title": driver.title,
        "candidate_count": len(handles),
        "page_kind": page_kind_from_url(driver.current_url),
        "preferred_kind": preferred_kind,
    }


def build_text_xpath(text: str) -> str:
    return (
        f"//*[contains(normalize-space(text()), '{text}') and "
        "not(self::script) and not(self::style)]"
    )


def click_navigation_text(driver: Any, text: str, timeout_seconds: int = 12) -> None:
    exact_xpath = (
        f"//*[normalize-space(.)='{text}' and "
        "not(self::script) and not(self::style)]"
    )

    def find_visible_click_target(_: Any) -> Any | None:
        for xpath in (exact_xpath, build_text_xpath(text)):
            candidates: list[tuple[tuple[int, int, int], Any]] = []
            for element in driver.find_elements(By.XPATH, xpath):
                try:
                    if not element.is_displayed() or not element.is_enabled():
                        continue
                    tag_name = (element.tag_name or "").lower()
                    role = (element.get_attribute("role") or "").lower()
                    clickable_rank = 0 if tag_name in {"a", "button"} or role in {"button", "menuitem", "tab"} else 1
                    descendant_count = len(element.find_elements(By.XPATH, ".//*"))
                    text_length = len((element.text or "").strip())
                    candidates.append(((clickable_rank, descendant_count, text_length), element))
                except Exception:
                    continue
            if candidates:
                return min(candidates, key=lambda item: item[0])[1]
        return None

    element = WebDriverWait(driver, timeout_seconds).until(find_visible_click_target)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    try:
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)


def wait_for_step_feedback(driver: Any, text: str, timeout_seconds: int = 8) -> None:
    xpath = build_text_xpath(text)
    try:
        WebDriverWait(driver, timeout_seconds).until(
            EC.presence_of_element_located((By.XPATH, xpath))
        )
    except Exception:
        time.sleep(1.2)


def select_dropdown_option(
    driver: Any,
    trigger_text: str,
    option_text: str,
    timeout_seconds: int = 12,
) -> None:
    click_navigation_text(driver, trigger_text, timeout_seconds=timeout_seconds)
    time.sleep(0.8)
    if option_text != trigger_text:
        click_navigation_text(driver, option_text, timeout_seconds=timeout_seconds)
    time.sleep(0.8)


def parse_target_dates(target_dates: list[str]) -> set[str]:
    normalized: set[str] = set()
    for value in target_dates:
        normalized.add(value)
        try:
            year, month, day = value.split("-")
            normalized.add(f"{year}.{int(month)}.{int(day)}")
            normalized.add(f"{year}-{int(month):02d}-{int(day):02d}")
            normalized.add(f"{year}/{int(month):02d}/{int(day):02d}")
            normalized.add(f"{int(month):02d}-{int(day):02d}")
            normalized.add(f"{int(month)}-{int(day)}")
            normalized.add(f"{int(month):02d}/{int(day):02d}")
            normalized.add(f"{int(month)}/{int(day)}")
            normalized.add(f"{int(month)}月{int(day)}日")
            normalized.add(f"{int(month)}月{int(day)}号")
        except Exception:
            continue
    return normalized


LIVE_TIME_RANGE_PATTERN = re.compile(
    r"(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{1,2}):(\d{2})\s*~\s*"
    r"(\d{4})[-/](\d{2})[-/](\d{2})\s+(\d{1,2}):(\d{2})"
)


def detail_candidate_priority(row_text: str, target_dates: list[str]) -> tuple[int, str]:
    """Rank candidates so a target-date morning cross-day live is selected first."""
    target_days = {value for value in target_dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)}
    match = LIVE_TIME_RANGE_PATTERN.search(row_text)
    if not match:
        return 0, "默认列表顺序"

    groups = match.groups()
    start_day = "-".join(groups[:3])
    end_day = "-".join(groups[5:8])
    is_cross_day = start_day != end_day or "跨天" in row_text

    if is_cross_day and start_day in target_days:
        return 200, "跨天直播按开播日期归属"
    if start_day in target_days:
        return 200, "目标日开播"
    if end_day in target_days:
        return 100, "目标日结束的跨天直播"
    return 0, "默认列表顺序"


def matching_target_date(row_text: str, target_dates: list[str]) -> str | None:
    """Return the target date for a row, assigning cross-day lives to their start date."""
    target_days = {value for value in target_dates if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)}
    match = LIVE_TIME_RANGE_PATTERN.search(row_text)
    if match:
        start_day = "-".join(match.groups()[:3])
        return start_day if start_day in target_days else None

    target_tokens = parse_target_dates(target_dates)
    return next((token for token in target_tokens if token in row_text), None)


def collect_matching_rows(driver: Any, target_dates: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    row_xpath = (
        "//table//tr | "
        "//*[@role='row'] | "
        "//*[contains(@class, 'row')] | "
        "//*[contains(@class, 'table-row')] | "
        "//*[contains(@class, 'list-item')]"
    )
    rows = driver.find_elements(By.XPATH, row_xpath)
    matches: list[dict[str, Any]] = []
    samples: list[str] = []
    seen_texts: set[str] = set()

    for row in rows:
        text = " ".join(row.text.split())
        if not text:
            continue
        if text in seen_texts:
            continue
        seen_texts.add(text)

        if "开播时间" in text and "直播间" in text:
            continue
        if "直播间成交金额" not in text and "操作" not in text and len(samples) < 15:
            samples.append(text)

        matched_date = matching_target_date(text, target_dates)
        if not matched_date:
            continue

        matches.append(
            {
                "matched_date": matched_date,
                "row_text": text,
                "is_live": "直播中" in text,
            }
        )

    if not samples:
        samples = list(seen_texts)[:15]

    return matches, samples


def collect_detail_candidates(driver: Any, target_dates: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_rows: set[str] = set()
    clickable_xpath = (
        "//*[contains(normalize-space(text()), '详情') or contains(normalize-space(text()), '大屏')]"
    )
    elements = driver.find_elements(By.XPATH, clickable_xpath)

    for element in elements:
        try:
            row = element.find_element(By.XPATH, "./ancestor::*[@role='row'][1] | ./ancestor::tr[1] | ./ancestor::*[contains(@class, 'row')][1]")
        except Exception:
            continue

        row_text = " ".join(row.text.split())
        if not row_text:
            continue
        if row_text in seen_rows:
            continue

        matched_date = matching_target_date(row_text, target_dates)
        if not matched_date:
            continue
        seen_rows.add(row_text)

        action_text = " ".join(element.text.split()) or "详情"
        priority, selection_reason = detail_candidate_priority(row_text, target_dates)
        candidates.append(
            {
                "matched_date": matched_date,
                "action_text": action_text,
                "row_text": row_text,
                "is_live": "直播中" in row_text,
                "selection_priority": priority,
                "selection_reason": selection_reason,
            }
        )

    return candidates


def close_other_live_session_tabs(driver: Any, selected_handle: str, selected_url: str | None) -> None:
    selected_match = re.search(r"[?&]live_room_id=(\d+)", selected_url or "")
    if not selected_match:
        return
    selected_room_id = selected_match.group(1)

    for handle in list(driver.window_handles):
        if handle == selected_handle:
            continue
        try:
            driver.switch_to.window(handle)
            other_url = driver.current_url or ""
        except Exception:
            continue
        other_match = re.search(r"[?&]live_room_id=(\d+)", other_url)
        if other_match and other_match.group(1) != selected_room_id:
            try:
                driver.close()
            except Exception:
                pass

    driver.switch_to.window(selected_handle)


def open_first_detail(driver: Any, target_dates: list[str], candidate_index: int = 0) -> dict[str, Any] | None:
    detail_elements = driver.find_elements(
        By.XPATH,
        "//*[contains(normalize-space(text()), '详情')]",
    )

    eligible: list[tuple[int, int, Any, str, str, str]] = []
    seen_rows: set[str] = set()
    for index, element in enumerate(detail_elements):
        try:
            row = element.find_element(
                By.XPATH,
                "./ancestor::*[@role='row'][1] | ./ancestor::tr[1] | ./ancestor::*[contains(@class, 'row')][1]",
            )
        except Exception:
            continue

        row_text = " ".join(row.text.split())
        if not row_text:
            continue
        if row_text in seen_rows:
            continue
        if "直播中" in row_text:
            continue

        matched_date = matching_target_date(row_text, target_dates)
        if not matched_date:
            continue
        seen_rows.add(row_text)

        priority, selection_reason = detail_candidate_priority(row_text, target_dates)
        eligible.append((priority, -index, element, row_text, matched_date, selection_reason))

    ordered = sorted(eligible, key=lambda item: (item[0], item[1]), reverse=True)
    if candidate_index < 0 or candidate_index >= len(ordered):
        return None

    for priority, _index, element, row_text, matched_date, selection_reason in ordered[candidate_index:candidate_index + 1]:

        before_handles = list(driver.window_handles)
        before_url = driver.current_url
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].click();", element)

        time.sleep(2.0)

        after_handles = list(driver.window_handles)
        if len(after_handles) > len(before_handles):
            new_handle = next(handle for handle in after_handles if handle not in before_handles)
            driver.switch_to.window(new_handle)
        else:
            try:
                current_url = driver.current_url
            except Exception:
                current_url = before_url
            if current_url == before_url:
                time.sleep(2.0)

        time.sleep(5.0)

        try:
            final_url = driver.current_url
        except Exception:
            final_url = None

        try:
            final_title = driver.title
        except Exception:
            final_title = None

        selected_handle = driver.current_window_handle
        close_other_live_session_tabs(driver, selected_handle, final_url)

        if final_url == before_url:
            time.sleep(2.0)

        return {
            "matched_date": matched_date,
            "row_text": row_text,
            "selection_priority": priority,
            "selection_reason": selection_reason,
            "candidate_index": candidate_index,
            "current_url": final_url,
            "title": final_title,
            "new_window_opened": len(after_handles) > len(before_handles),
        }

    return None


def detect_detail_page_state(driver: Any) -> dict[str, Any]:
    body = driver.find_element(By.TAG_NAME, "body")
    body_text = " ".join(body.text.split())
    excerpt = body_text[:1200]

    state = "unknown"
    reason = "未识别到明确状态"

    if "数据生成中" in body_text:
        state = "data_pending"
        reason = "页面出现“数据生成中”"
    elif "直播中" in body_text:
        state = "live_in_progress"
        reason = "页面出现“直播中”"
    elif ("直播时长" in body_text or "开播时间" in body_text) and ("结束" in body_text or "已结束" in body_text):
        state = "finished"
        reason = "页面同时出现直播时长/开播时间和结束相关文案"
    elif "直播时长" in body_text:
        state = "finished"
        reason = "页面出现“直播时长”"

    return {
        "state": state,
        "reason": reason,
        "page_excerpt": excerpt,
    }


def wait_for_detail_page_ready(driver: Any, retries: int = 3, wait_seconds: float = 3.0) -> dict[str, Any]:
    last_state = detect_detail_page_state(driver)
    for attempt in range(1, retries + 1):
        excerpt = last_state.get("page_excerpt", "")
        if "应用加载失败，请刷新页面重试" not in excerpt:
            last_state["retry_count"] = attempt - 1
            return last_state
        driver.refresh()
        time.sleep(wait_seconds)
        last_state = detect_detail_page_state(driver)
    last_state["retry_count"] = retries
    if "应用加载失败，请刷新页面重试" in last_state.get("page_excerpt", ""):
        last_state["state"] = "load_failed"
        last_state["reason"] = "详情页连续刷新后仍提示“应用加载失败，请刷新页面重试”"
    return last_state


def open_live_dashboard(driver: Any) -> dict[str, Any] | None:
    dashboard_xpath = "//*[contains(normalize-space(text()), '直播大屏')]"
    elements = driver.find_elements(By.XPATH, dashboard_xpath)
    if not elements:
        return None

    before_handles = list(driver.window_handles)
    before_url = ""
    try:
        before_url = driver.current_url
    except Exception:
        before_url = ""

    target = elements[0]
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target)
    try:
        target.click()
    except Exception:
        driver.execute_script("arguments[0].click();", target)

    time.sleep(3.0)
    after_handles = list(driver.window_handles)
    new_window_opened = len(after_handles) > len(before_handles)
    if new_window_opened:
        new_handle = next(handle for handle in after_handles if handle not in before_handles)
        driver.switch_to.window(new_handle)

    try:
        current_url = driver.current_url
    except Exception:
        current_url = before_url
    try:
        title = driver.title
    except Exception:
        title = ""

    return {
        "current_url": current_url,
        "title": title,
        "new_window_opened": new_window_opened,
    }


def first_match(patterns: list[str], text: str) -> str | None:
    import re

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return None


def compact_dashboard_text(text: str) -> str:
    import re

    compact = " ".join(text.split())
    compact = re.sub(r"[¥￥]\s+", "¥", compact)
    compact = re.sub(r"(\d)\s*,\s*(\d)", r"\1,\2", compact)
    compact = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", compact)
    compact = re.sub(r"¥(\d+),\s*(\d)\s+(\d)\b", r"¥\1,\2\3", compact)
    compact = re.sub(r"¥(\d+),\s*(\d)\b", r"¥\1,\2", compact)
    compact = re.sub(r"(\d)\s+(\d%)", r"\1\2", compact)
    compact = re.sub(r"(\d+\.\d+)\s+(\d+%)", r"\1 \2", compact)
    compact = re.sub(r"(\d+)\s+分钟\s+(\d+)秒", r"\1分钟\2秒", compact)
    compact = re.sub(r"(\d+)\s+小时\s+(\d+)分", r"\1小时\2分", compact)
    compact = compact.replace("楼", "¥")
    return compact


def clean_metric_value(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace(" ", "").replace("¥¥", "¥")


def extract_metric_block(compact_text: str, label: str, lookahead_labels: list[str]) -> str | None:
    import re

    lookahead = "|".join(re.escape(item) for item in lookahead_labels)
    pattern = rf"{re.escape(label)}\s*(.*?)(?={lookahead}|$)"
    match = re.search(pattern, compact_text)
    if not match:
        return None
    return match.group(1).strip()


def extract_currency_from_block(block: str | None) -> str | None:
    import re

    if not block:
        return None
    block = block.replace("¥ ", "¥")
    block = re.sub(r"¥(\d+),\s*(\d)\s*(\d)\b", r"¥\1,\2\3", block)
    block = re.sub(r"¥(\d+),\s*(\d)\b", r"¥\1,\2", block)
    match = re.search(r"[¥￥]\s*([\d,]+(?:\.\d+)?)", block)
    if match:
        return clean_metric_value(match.group(1))
    return None


def extract_simple_value_from_block(block: str | None) -> str | None:
    import re

    if not block:
        return None
    if block.startswith("暂无"):
        return "暂无"
    match = re.search(r"([\d,]+(?:\.\d+)?%?)", block)
    if match:
        return clean_metric_value(match.group(1))
    return None


def extract_duration_value(block: str | None) -> str | None:
    import re

    if not block:
        return None
    normalized = compact_dashboard_text(block)
    match = re.search(r"(\d+分钟\d+秒)", normalized)
    if match:
        return match.group(1)
    match = re.search(r"(\d+小时\d+分)", normalized)
    if match:
        return match.group(1)
    return normalized.strip() or None


def normalize_product_section(section: str) -> str:
    import re

    normalized = section
    normalized = re.sub(r"¥(\d+(?:\.\d+)?)\s*([\d.]+%)", r"¥\1 |\2", normalized)
    normalized = re.sub(r"([\d.]+%)\s*([\d.]+%)", r"\1 |\2", normalized)
    normalized = re.sub(r"([\d.]+%)\s*¥", r"\1 | ¥", normalized)
    normalized = re.sub(r"¥(\d+(?:\.\d+)?)\s*(\d+)\s+话术", r"¥\1 |\2 | 话术", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def extract_products(compact_text: str) -> list[dict[str, Any]]:
    import re

    start_marker = "当前购物车商品"
    end_candidates = ["共13条", "共", "人气趋势", "互动趋势", "实时评论", "直播已结束", "直播诊断"]
    if start_marker not in compact_text:
        return []

    start_index = compact_text.find(start_marker)
    end_index = len(compact_text)
    for marker in end_candidates:
        idx = compact_text.find(marker, start_index + len(start_marker))
        if idx != -1:
            end_index = min(end_index, idx)
    section = compact_text[start_index:end_index]

    # Remove header text before products start
    header_markers = ["操作"]
    for marker in header_markers:
        idx = section.find(marker)
        if idx != -1:
            section = section[idx + len(marker):].strip()
            break

    if not section:
        return []

    section = normalize_product_section(section)

    products: list[dict[str, Any]] = []
    product_chunks = section.split(" 话术 ")
    for chunk in product_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "¥" not in chunk or "%" not in chunk:
            continue

        match = re.search(
            r"^(?P<name>.+?)\s+¥(?P<price>[\d,]+(?:\.\d+)?)\s*\|\s*"
            r"(?P<exposure_click>[\d.]+%)\s*\|\s*"
            r"(?P<click_deal>[\d.]+%)\s*\|\s*"
            r"¥(?P<pay_amount>[\d,]+(?:\.\d+)?)\s*\|\s*"
            r"(?P<order_count>\d+)$",
            chunk,
        )
        if not match:
            continue

        products.append(
            {
                "商品名称": match.group("name").strip(),
                "到手价": clean_metric_value(match.group("price")),
                "曝光-点击转化率": match.group("exposure_click"),
                "点击-成交转化率": match.group("click_deal"),
                "累计用户支付金额": clean_metric_value(match.group("pay_amount")),
                "累计成交订单数": match.group("order_count"),
            }
        )
    return products


def wait_for_dashboard_text(driver: Any, timeout_seconds: int = 20) -> str:
    keywords = [
        "用户支付金额",
        "成交件数",
        "累计观看人数",
        "流量分析",
        "当前购物车商品",
    ]

    def fetch_text() -> str:
        try:
            return driver.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
        except Exception:
            return ""

    end_time = time.time() + timeout_seconds
    best_text = ""
    while time.time() < end_time:
        text = " ".join(fetch_text().split())
        if text:
            best_text = text
        if any(keyword in text for keyword in keywords):
            return text
        time.sleep(1.0)
    return best_text


def extract_dom_label_value_map(driver: Any) -> dict[str, str]:
    script = r"""
const labels = [
  "直播间用户支付金额",
  "投放消耗（店铺绑定）",
  "投放消耗（店铺被投）",
  "千次观看用户支付金额",
  "退款金额",
  "直播间观看人数",
  "成交人数",
  "成交件数",
  "点击-成交转化率",
  "累计观看人数",
  "新增粉丝数",
  "人均观看时长",
  "消费券引导支付金额",
  "消费券引导支付占比",
  "平均在线人数",
  "最高在线人数"
];

function visible(el) {
  const style = window.getComputedStyle(el);
  return style && style.display !== "none" && style.visibility !== "hidden";
}

function norm(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

function pushText(arr, text) {
  const t = norm(text);
  if (t && !arr.includes(t)) arr.push(t);
}

function candidateValue(el) {
  const texts = [];
  const parent = el.parentElement;

  pushText(texts, el.nextSibling && el.nextSibling.textContent);
  pushText(texts, el.previousSibling && el.previousSibling.textContent);

  if (parent) {
    for (const child of parent.children) {
      if (child === el) continue;
      pushText(texts, child.innerText);
      let hops = 0;
      let sub = child.firstElementChild;
      while (sub && hops < 6) {
        pushText(texts, sub.innerText);
        sub = sub.firstElementChild;
        hops += 1;
      }
    }
    pushText(texts, parent.innerText.replace(el.innerText || "", ""));
  }

  let sib = el.nextElementSibling;
  let hops = 0;
  while (sib && hops < 6) {
    pushText(texts, sib.innerText);
    sib = sib.nextElementSibling;
    hops += 1;
  }

  return texts.join(" | ");
}

const all = Array.from(document.querySelectorAll("body *"));
const result = {};

for (const label of labels) {
  const matches = all.filter(el => visible(el) && norm(el.innerText) === label);
  let value = "";
  for (const el of matches) {
    value = candidateValue(el);
    if (value) break;
  }
  result[label] = value;
}

return result;
"""
    try:
        return driver.execute_script(script) or {}
    except Exception:
        return {}


def extract_dom_products(driver: Any) -> list[dict[str, Any]]:
    script = r"""
function norm(text) {
  return (text || "").replace(/\s+/g, " ").trim();
}

const nodes = Array.from(document.querySelectorAll("body *"));
const candidates = [];

for (const el of nodes) {
  const text = norm(el.innerText);
  if (!text) continue;
  if (!text.includes("话术")) continue;
  if (!text.includes("¥")) continue;
  if (!text.includes("%")) continue;
  if (text.length < 20) continue;
  candidates.push(text);
}

return Array.from(new Set(candidates)).slice(0, 30);
"""
    try:
        rows = driver.execute_script(script) or []
    except Exception:
        rows = []

    import re

    products: list[dict[str, Any]] = []
    for row in rows:
        text = " ".join(str(row).split())
        text = text.replace("话术", "").strip()
        match = re.search(
            r"^(?P<name>.+?)\s+¥(?P<price>[\d,]+(?:\.\d+)?)\s+"
            r"(?P<exposure_click>[\d.]+%)\s+"
            r"(?P<click_deal>[\d.]+%)\s+"
            r"¥(?P<pay_amount>[\d,]+(?:\.\d+)?)\s+"
            r"(?P<order_count>\d+)$",
            text,
        )
        if not match:
            continue
        products.append(
            {
                "商品名称": match.group("name").strip(),
                "到手价": clean_metric_value(match.group("price")),
                "曝光-点击转化率": match.group("exposure_click"),
                "点击-成交转化率": match.group("click_deal"),
                "累计用户支付金额": clean_metric_value(match.group("pay_amount")),
                "累计成交订单数": match.group("order_count"),
            }
        )
    return sanitize_products(products)


def sanitize_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    header_keywords = [
        "商品 名称",
        "到手价",
        "曝光-点击转化率",
        "点击-成交转化率",
        "累计用户支付金额",
        "累计成交订单数",
        "操作",
    ]
    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()

    for item in products:
        name = " ".join(str(item.get("商品名称", "")).split())
        if not name:
            continue
        if any(keyword in name for keyword in header_keywords):
            continue
        if "¥" in name or "%" in name:
            continue

        normalized = {
            "商品名称": name,
            "到手价": str(item.get("到手价", "")).strip(),
            "曝光-点击转化率": str(item.get("曝光-点击转化率", "")).strip(),
            "点击-成交转化率": str(item.get("点击-成交转化率", "")).strip(),
            "累计用户支付金额": str(item.get("累计用户支付金额", "")).strip(),
            "累计成交订单数": str(item.get("累计成交订单数", "")).strip(),
        }
        key = (
            normalized["商品名称"],
            normalized["到手价"],
            normalized["曝光-点击转化率"],
            normalized["点击-成交转化率"],
            normalized["累计用户支付金额"],
            normalized["累计成交订单数"],
        )
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)

    return cleaned


def load_detail_stage_metric_fallback() -> dict[str, str]:
    import json

    fallback_path = Path(__file__).resolve().parent.parent / "output" / "douyin_detail_stage_result.json"
    if not fallback_path.exists():
        return {}
    try:
        payload = json.loads(fallback_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    detail_state = payload.get("detail_page_state") or {}
    excerpt = detail_state.get("page_excerpt")
    if not excerpt:
        return {}

    compact_text = compact_dashboard_text(str(excerpt))
    labels = [
        "直播间用户支付金额",
        "投放消耗（店铺绑定）",
        "投放消耗（店铺被投）",
        "退款金额",
        "最高在线人数",
    ]
    blocks = {label: extract_metric_block(compact_text, label, labels) for label in labels}
    return {
        "直播间用户支付金额": extract_currency_from_block(blocks.get("直播间用户支付金额")) or "",
        "投放消耗（店铺绑定）": extract_currency_from_block(blocks.get("投放消耗（店铺绑定）")) or "",
        "投放消耗（店铺被投）": extract_currency_from_block(blocks.get("投放消耗（店铺被投）")) or "",
        "退款金额": extract_currency_from_block(blocks.get("退款金额")) or "",
        "最高在线人数": extract_simple_value_from_block(blocks.get("最高在线人数")) or "",
    }


def prefer_metric_value(metric_name: str, primary: str | None, fallback: str | None) -> str | None:
    primary = primary or None
    fallback = fallback or None
    money_like_metrics = {
        "直播间用户支付金额",
        "投放消耗（店铺绑定）",
        "投放消耗（店铺被投）",
        "千次观看用户支付金额",
        "退款金额",
    }
    if not primary:
        return fallback
    if metric_name in money_like_metrics and fallback:
        # Dashboard text occasionally splits amounts into fragments like "5" or "5,733".
        if len(primary) <= 3:
            return fallback
        if "." not in primary and "." in fallback:
            return fallback
    return primary


def extract_core_metrics(driver: Any) -> dict[str, Any]:
    body_text = wait_for_dashboard_text(driver, timeout_seconds=20)
    compact_text = compact_dashboard_text(body_text)
    dom_map = extract_dom_label_value_map(driver)
    detail_fallback = load_detail_stage_metric_fallback()

    labels = [
        "直播间成交金额",
        "直播间用户支付金额",
        "投放消耗（店铺绑定）",
        "投放消耗（店铺被投）",
        "千次观看用户支付金额",
        "退款金额",
        "成交件数",
        "成交人数",
        "点击-成交转化率",
        "成交粉丝占比",
        "消费券引导支付金额",
        "平均在线人数",
        "累计观看人数",
        "新加直播团人数",
        "新增粉丝数",
        "人均观看时长",
        "消费券引导支付占比",
        "当前购物车商品",
    ]

    blocks = {label: extract_metric_block(compact_text, label, labels) for label in labels}

    metrics = {
        "直播间成交金额": None,
        "直播间用户支付金额": prefer_metric_value(
            "直播间用户支付金额",
            extract_currency_from_block(dom_map.get("直播间用户支付金额")) or extract_currency_from_block(blocks.get("直播间用户支付金额")),
            detail_fallback.get("直播间用户支付金额"),
        ),
        "投放消耗（店铺绑定）": prefer_metric_value(
            "投放消耗（店铺绑定）",
            extract_currency_from_block(dom_map.get("投放消耗（店铺绑定）")) or extract_currency_from_block(blocks.get("投放消耗（店铺绑定）")),
            detail_fallback.get("投放消耗（店铺绑定）"),
        ),
        "投放消耗（店铺被投）": prefer_metric_value(
            "投放消耗（店铺被投）",
            extract_currency_from_block(dom_map.get("投放消耗（店铺被投）")) or extract_currency_from_block(blocks.get("投放消耗（店铺被投）")),
            detail_fallback.get("投放消耗（店铺被投）"),
        ),
        "千次观看用户支付金额": extract_currency_from_block(dom_map.get("千次观看用户支付金额")) or extract_currency_from_block(blocks.get("千次观看用户支付金额")),
        "退款金额": prefer_metric_value(
            "退款金额",
            extract_currency_from_block(dom_map.get("退款金额")) or extract_currency_from_block(blocks.get("退款金额")),
            detail_fallback.get("退款金额"),
        ),
        "直播间观看人数": clean_metric_value(first_match(
            [
                r"直播间观看人数\s*([\d,]+)",
                r"观看人数\s*([\d,]+)",
            ],
            compact_text,
        )),
        "直播间成交人数": extract_simple_value_from_block(dom_map.get("成交人数")) or extract_simple_value_from_block(blocks.get("成交人数")) or clean_metric_value(first_match(
            [
                r"直播间成交人数\s*([\d,]+)",
                r"成交人数\s*([\d,]+)",
            ],
            compact_text,
        )),
        "成交件数": extract_simple_value_from_block(dom_map.get("成交件数")) or extract_simple_value_from_block(blocks.get("成交件数")),
        "点击-成交转化率": extract_simple_value_from_block(dom_map.get("点击-成交转化率")) or extract_simple_value_from_block(blocks.get("点击-成交转化率")),
        "累计观看人数": extract_simple_value_from_block(dom_map.get("累计观看人数")) or extract_simple_value_from_block(blocks.get("累计观看人数")),
        "新增粉丝数": extract_simple_value_from_block(dom_map.get("新增粉丝数")) or extract_simple_value_from_block(blocks.get("新增粉丝数")),
        "人均观看时长": extract_duration_value(dom_map.get("人均观看时长")) or extract_duration_value(blocks.get("人均观看时长")),
        "消费券引导支付金额": dom_map.get("消费券引导支付金额") or blocks.get("消费券引导支付金额"),
        "消费券引导支付占比": dom_map.get("消费券引导支付占比") or blocks.get("消费券引导支付占比"),
        "平均在线人数": clean_metric_value(first_match(
            [
                r"平均在线人数\s*([\d,]+)",
            ],
            compact_text,
        )),
        "最高在线人数": prefer_metric_value(
            "最高在线人数",
            extract_simple_value_from_block(dom_map.get("最高在线人数")) or clean_metric_value(first_match(
                [
                    r"最高在线人数\s*([\d,]+)",
                ],
                compact_text,
            )),
            detail_fallback.get("最高在线人数"),
        ),
    }

    metrics["page_excerpt"] = compact_text[:2000]
    metrics["products"] = sanitize_products(extract_dom_products(driver) or extract_products(compact_text))
    return metrics


def collect(payload: dict[str, Any]) -> CollectorResult:
    config = load_launch_config(Path(payload["_config_path"]))
    plan = build_plan(config)
    entry_url = require_entry_url(payload)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        clicked_steps: list[str] = []
        active_tab_info = None
        if should_resume_from_current_page(payload):
            clicked_steps.append("resume_from_current_page")
            active_tab_info = activate_best_existing_tab(driver)
        else:
            driver.get(entry_url)
            driver.implicitly_wait(browser_config.implicit_wait_seconds)
            for step in navigation_steps(payload):
                action = step.get("action", "click")
                if action == "click":
                    click_navigation_text(driver, step["text"])
                    clicked_steps.append(step.get("label") or step["text"])
                    wait_for_step_feedback(driver, step["text"])
                elif action == "select_option":
                    select_dropdown_option(driver, step["trigger_text"], step["option_text"])
                    clicked_steps.append(
                        f"{step.get('label') or '下拉选择'}: {step['trigger_text']} -> {step['option_text']}"
                    )
                    wait_for_step_feedback(driver, step["option_text"])
                time.sleep(1.0)

        driver.implicitly_wait(browser_config.implicit_wait_seconds)
        target_date_values = [item.target_date for item in plan.daily_runs]
        matched_rows: list[dict[str, Any]] = []
        row_samples: list[str] = []
        detail_candidates: list[dict[str, Any]] = []
        detail_open_result = None
        detail_page_state = None
        dashboard_open_result = None
        core_metrics: dict[str, Any] = {}
        message = "已成功打开入口页面。"
        status = "ready"
        if clicked_steps:
            message = f"已成功打开入口页面，并完成导航：{' -> '.join(clicked_steps)}。"
            if clicked_steps == ["resume_from_current_page"]:
                message = "已从当前列表页继续执行，并开始识别目标日期场次。"
        current_kind = page_kind_from_url(driver.current_url)
        if current_kind == "detail":
            detail_page_state = wait_for_detail_page_ready(driver, retries=3, wait_seconds=4.0)
            message = "已从当前详情页继续执行。"
            if detail_page_state:
                message = f"{message} 当前详情页状态：{detail_page_state['state']}。"
            if "应用加载失败，请刷新页面重试" not in (detail_page_state or {}).get("page_excerpt", ""):
                dashboard_open_result = open_live_dashboard(driver)
                if dashboard_open_result:
                    core_metrics = extract_core_metrics(driver)
                    message = f"{message} 已尝试进入直播大屏并提取第一批核心指标。"
        else:
            matched_rows, row_samples = collect_matching_rows(driver, target_date_values)
            detail_candidates = collect_detail_candidates(driver, target_date_values)
            if matched_rows:
                message = (
                    f"已完成导航：{' -> '.join(clicked_steps)}，并在当前页找到 {len(matched_rows)} 条目标日期场次。"
                )
                if clicked_steps == ["resume_from_current_page"]:
                    message = f"已从当前列表页继续执行，并在当前页找到 {len(matched_rows)} 条目标日期场次。"
                if any(row.get("is_live") for row in matched_rows):
                    status = "live_in_progress"
                    message = (
                        f"已完成导航：{' -> '.join(clicked_steps)}，找到目标日期场次，但该场次当前处于直播中，"
                        "按规则应停止采集并等待直播结束后重试。"
                    )
                    if clicked_steps == ["resume_from_current_page"]:
                        message = "已从当前列表页识别到目标日期场次，但该场次当前处于直播中，按规则应停止采集并等待直播结束后重试。"
                else:
                    detail_open_result = open_first_detail(driver, target_date_values)
                    if detail_open_result:
                        detail_page_state = wait_for_detail_page_ready(driver, retries=3, wait_seconds=4.0)
                        if "应用加载失败，请刷新页面重试" not in detail_page_state.get("page_excerpt", ""):
                            dashboard_open_result = open_live_dashboard(driver)
                            if dashboard_open_result:
                                core_metrics = extract_core_metrics(driver)
                        message = (
                            f"已完成导航：{' -> '.join(clicked_steps)}，找到目标日期场次并已进入详情页。"
                        )
                        if clicked_steps == ["resume_from_current_page"]:
                            message = "已从当前列表页找到目标日期场次，并已进入详情页。"
                        if detail_page_state:
                            message = (
                                f"{message} 当前详情页状态：{detail_page_state['state']}。"
                            )
                        if "应用加载失败，请刷新页面重试" in detail_page_state.get("page_excerpt", ""):
                            message = f"{message} 详情页出现“应用加载失败”，已自动刷新重试。"
                        elif dashboard_open_result:
                            message = f"{message} 已尝试进入直播大屏并提取第一批核心指标。"

        try:
            final_body = driver.find_element(By.TAG_NAME, "body")
            final_body_text = final_body.text.strip()
        except Exception:
            final_body_text = ""

        has_meaningful_result = bool(
            matched_rows
            or detail_candidates
            or detail_open_result
            or detail_page_state
            or dashboard_open_result
            or core_metrics
        )

        if not final_body_text and not has_meaningful_result:
            message = "已成功打开入口页面，但当前页面正文为空或仍在等待加载。"
            if clicked_steps:
                message = f"已完成导航：{' -> '.join(clicked_steps)}，但当前页面正文为空或仍在等待加载。"
        return CollectorResult(
            status=status,
            message=message,
            current_url=driver.current_url,
            title=driver.title,
            target_dates=[item.target_date for item in plan.daily_runs],
            clicked_steps=clicked_steps,
            matched_rows=matched_rows,
            row_samples=row_samples,
            detail_candidates=detail_candidates,
            detail_open_result=detail_open_result,
            detail_page_state=detail_page_state,
            active_tab_info=active_tab_info,
            dashboard_open_result=dashboard_open_result,
            core_metrics=core_metrics,
        )
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the Luopan entry page and prepare for collection.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "douyin_workflow_config.json"),
        help="Path to the launcher JSON config.",
    )
    parser.add_argument(
        "--result-output",
        default="",
        help="Optional path to write the collector result JSON.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    payload["_config_path"] = str(config_path)
    result = collect(payload)
    result_json = json.dumps(asdict(result), ensure_ascii=False, indent=2)
    if args.result_output:
        output_path = Path(args.result_output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_json, encoding="utf-8")
    print(result_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
