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

from douyin_browser_automation import build_browser_config, open_or_attach
from douyin_live_collector import compact_dashboard_text
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By


@dataclass
class QianchuanStageResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    active_tab_info: dict[str, Any] | None
    fullscreen_result: dict[str, Any] | None
    core_metrics: dict[str, Any]


FIELD_ORDER = [
    "净成交订单数",
    "净成交订单成本（元）",
    "用户实际支付净成交金额（元）",
    "净成交金额结算率",
    "净成交订单结算率",
    "1小时内退款订单数",
    "1小时内退款金额（元）",
    "1小时内退款率",
    "整体成交订单数",
    "GPM（元）",
    "观看成交转化率",
    "整体成交订单成本（元）",
    "用户实际支付金额（元）",
    "整体成交智能优惠券金额（元）",
    "电商平台补贴金额（元）",
    "直播间退款金额（元）",
    "直播间退款率",
    "直播间整体曝光次数",
    "曝光观看率（次数）",
    "直播间整体观看人数",
    "直播间平均停留时长",
    "直播间整体新增粉丝数",
    "直播间评论次数",
    "直播间商品曝光次数",
    "直播间商品点击次数",
    "分享次数",
    "分享率",
    "整体消耗（元）",
    "综合成本（元）",
    "整体支付ROI",
    "综合营销ROI",
    "整体成交金额（元）",
    "净成交ROI",
    "净成交金额（元，常规口径）",
    "净成交金额（元，乘方投放期间）",
    "乘方投放状态",
]

FIELD_ALIASES = {
    "净成交订单数": ["净成交订单数"],
    "净成交订单成本（元）": ["净成交订单成本（元）", "净成交订单成本(元)"],
    "用户实际支付净成交金额（元）": ["用户实际支付净成交金额（元）", "用户实际支付净成交金额(元)"],
    "净成交金额结算率": ["净成交金额结算率"],
    "净成交订单结算率": ["净成交订单结算率"],
    "1小时内退款订单数": ["1小时内退款订单数"],
    "1小时内退款金额（元）": ["1小时内退款金额（元）", "1小时内退款金额(元)"],
    "1小时内退款率": ["1小时内退款率"],
    "整体成交订单数": ["整体成交订单数"],
    "GPM（元）": ["GPM（元）", "GPM(元)"],
    "观看成交转化率": ["观看成交转化率"],
    "整体成交订单成本（元）": ["整体成交订单成本（元）", "整体成交订单成本(元)"],
    "用户实际支付金额（元）": ["用户实际支付金额（元）", "用户实际支付金额(元)"],
    "整体成交智能优惠券金额（元）": ["整体成交智能优惠券金额（元）", "整体成交智能优惠券金额(元)"],
    "电商平台补贴金额（元）": ["电商平台补贴金额（元）", "电商平台补贴金额(元)"],
    "直播间退款金额（元）": ["直播间退款金额（元）", "直播间退款金额(元)"],
    "直播间退款率": ["直播间退款率"],
    "直播间整体曝光次数": ["直播间整体曝光次数"],
    "曝光观看率（次数）": ["曝光观看率（次数）", "曝光观看率(次数)"],
    "直播间整体观看人数": ["直播间整体观看人数"],
    "直播间平均停留时长": ["直播间平均停留时长", "直播间平均停留时长（整场）", "直播间平均停留时长(整场)"],
    "直播间整体新增粉丝数": ["直播间整体新增粉丝数"],
    "直播间评论次数": ["直播间评论次数"],
    "直播间商品曝光次数": ["直播间商品曝光次数"],
    "直播间商品点击次数": ["直播间商品点击次数"],
    "分享次数": ["分享次数"],
    "分享率": ["分享率"],
    "整体消耗（元）": ["整体消耗（元）", "整体消耗(元)"],
    "综合成本（元）": ["综合成本（元）", "综合成本(元)"],
    "整体支付ROI": ["整体支付ROI"],
    "综合营销ROI": ["综合营销ROI"],
    "整体成交金额（元）": ["整体成交金额（元）", "整体成交金额(元)"],
    "净成交ROI": ["净成交ROI"],
}

FULLSCREEN_REQUIRED_FIELDS = [
    "净成交订单数",
    "用户实际支付净成交金额（元）",
    "GPM（元）",
]


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
    if target:
        driver.switch_to.window(target["handle"])
        return {
            "selected_url": target["url"],
            "selected_title": target["title"],
            "candidate_count": len(candidates),
            "page_kind": "qianchuan_dashboard",
            "preferred_kind": "qianchuan_dashboard",
        }
    return None


def extract_value(text: str, label: str) -> str | None:
    label_pattern = re.escape(label)
    patterns = [
        rf"{label_pattern}\s*([0-9]+分\s*[0-9]+秒)",
        rf"{label_pattern}\s*([0-9]+分钟\s*[0-9]+秒)",
        rf"{label_pattern}\s*([0-9]+分)",
        rf"{label_pattern}\s*([0-9]+分钟)",
        rf"{label_pattern}\s*([0-9]+秒)",
        rf"{label_pattern}\s*([0-9][0-9,]*(?:\.\d+)?\s*%)",
        rf"{label_pattern}\s*([0-9][0-9,]*(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return " ".join(match.group(1).split())
    return None


def extract_qianchuan_metrics(text: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for field in FIELD_ORDER:
        value = None
        for alias in FIELD_ALIASES.get(field, [field]):
            value = extract_value(text, alias)
            if value is not None:
                break
        metrics[field] = value
    amount_pattern = r"([0-9][0-9,]*(?:\.\d+)?)"
    net_amount_label = r"净成交金额(?:（元）|\(元\))"
    standard_net_amount = re.search(
        rf"净成交ROI\s*[0-9][0-9,]*(?:\.\d+)?\s+{net_amount_label}\s*{amount_pattern}",
        text,
    )
    special_net_amount = re.search(
        rf"{net_amount_label}\s*乘方投放期间\s*{amount_pattern}",
        text,
    )
    if standard_net_amount:
        metrics["净成交金额（元，常规口径）"] = standard_net_amount.group(1)
    else:
        plain_net_amount = re.search(rf"{net_amount_label}\s*{amount_pattern}", text)
        metrics["净成交金额（元，常规口径）"] = (
            plain_net_amount.group(1) if plain_net_amount else None
        )
    metrics["净成交金额（元，乘方投放期间）"] = (
        special_net_amount.group(1) if special_net_amount else None
    )
    metrics["乘方投放状态"] = "是" if special_net_amount else "否"
    metrics["page_excerpt"] = text[:3000]
    return metrics


def count_present_fields(metrics: dict[str, Any]) -> int:
    return sum(1 for field in FIELD_ORDER if metrics.get(field))


def needs_core_fullscreen(metrics: dict[str, Any]) -> bool:
    return any(not metrics.get(field) for field in FULLSCREEN_REQUIRED_FIELDS)


def get_page_text(driver: Any) -> str:
    text = driver.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
    return compact_dashboard_text(text)


def reset_qianchuan_page_state(driver: Any) -> None:
    current_url = driver.current_url
    driver.get(current_url)
    time.sleep(2.5)


def close_custom_column_modal(driver: Any) -> None:
    script = r"""
const closeButton = document.querySelector('.qc-ui-custom-column-modal-header .ovui-modal__close, .qc-ui-custom-column-modal-header [class*="close"]');
if (closeButton) {
  closeButton.click();
  return true;
}
const cancelButton = Array.from(document.querySelectorAll('button')).find((button) => {
  const text = String(button.innerText || '').replace(/\s+/g, ' ').trim();
  return text === '取消';
});
if (cancelButton) {
  cancelButton.click();
  return true;
}
return false;
"""
    closed = driver.execute_script(script)
    if closed:
        time.sleep(0.8)


def click_core_fullscreen(driver: Any) -> dict[str, Any]:
    script = r"""
const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
const root = document.querySelector('.summary-overview');
if (!root) {
  return { clicked: false, reason: 'summary_overview_not_found' };
}
const modelInput = root.querySelector('.operation-box .model-switch-item input.ovui-input');
const modelValue = norm(modelInput && modelInput.value);
const fullscreen = root.querySelector('.operation-box .custom-icon-op-wrapper');
if (!fullscreen) {
  return { clicked: false, reason: 'core_fullscreen_button_not_found', modelValue };
}
const rect = fullscreen.getBoundingClientRect();
return {
  clicked: true,
  reason: 'candidate_found',
  modelValue,
  button: {
    className: norm(fullscreen.className),
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    html: fullscreen.outerHTML.slice(0, 300),
  },
  cardPreview: norm(root.innerText).slice(0, 300),
};
"""
    candidate = driver.execute_script(script) or {"clicked": False, "reason": "unknown"}
    if not candidate.get("clicked"):
        return candidate

    close_custom_column_modal(driver)
    buttons = driver.find_elements(By.CSS_SELECTOR, ".summary-overview .operation-box .custom-icon-op-wrapper")
    target = None
    for button in buttons:
        rect = button.rect
        if rect.get("y", 0) < 180 and rect.get("width", 0) > 20:
            target = button
            break
    if target is None:
        candidate["clicked"] = False
        candidate["reason"] = "core_fullscreen_button_not_clickable"
        return candidate

    ActionChains(driver).move_to_element(target).pause(0.25).click(target).perform()
    time.sleep(1.2)
    candidate["reason"] = "clicked"
    return candidate


def wait_for_expanded_metrics(driver: Any, baseline_count: int, timeout_seconds: float = 8.0) -> tuple[str, dict[str, Any]]:
    deadline = time.time() + timeout_seconds
    best_text = ""
    best_metrics: dict[str, Any] = {}
    best_count = baseline_count
    while time.time() < deadline:
        time.sleep(0.8)
        text = get_page_text(driver)
        metrics = extract_qianchuan_metrics(text)
        count = count_present_fields(metrics)
        if count > best_count:
            best_text = text
            best_metrics = metrics
            best_count = count
        if not needs_core_fullscreen(metrics) or count >= baseline_count + 5:
            return text, metrics
    if best_metrics:
        return best_text, best_metrics
    text = get_page_text(driver)
    return text, extract_qianchuan_metrics(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Douyin qianchuan stage.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        active_tab_info = select_qianchuan_tab(driver)
        current_url = driver.current_url
        title = driver.title
        status = "ready"
        message = "Ready on the current Qianchuan core data page and extracted core metrics."
        core_metrics: dict[str, Any] = {}
        fullscreen_result: dict[str, Any] | None = None

        if not active_tab_info:
            status = "wrong_page"
            message = "Current page is not the Qianchuan core data page."
        else:
            reset_qianchuan_page_state(driver)
            close_custom_column_modal(driver)
            text = get_page_text(driver)
            core_metrics = extract_qianchuan_metrics(text)
            baseline_count = count_present_fields(core_metrics)

            if needs_core_fullscreen(core_metrics):
                fullscreen_result = click_core_fullscreen(driver)
                if fullscreen_result.get("clicked"):
                    text, core_metrics = wait_for_expanded_metrics(driver, baseline_count)
                    message = "Opened the core data fullscreen panel and re-extracted Qianchuan core metrics."
                else:
                    message = "Could not open the core data fullscreen panel; extracted currently visible Qianchuan metrics only."

        result = QianchuanStageResult(
            status=status,
            message=message,
            current_url=current_url,
            title=title,
            active_tab_info=active_tab_info,
            fullscreen_result=fullscreen_result,
            core_metrics=core_metrics,
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
