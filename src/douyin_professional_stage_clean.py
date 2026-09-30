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

from selenium.webdriver.common.by import By

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from douyin_browser_automation import build_browser_config, load_payload, open_or_attach
from douyin_live_collector import activate_best_existing_tab, click_navigation_text, compact_dashboard_text, page_kind_from_url


@dataclass
class ProfessionalStageResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    active_tab_info: dict[str, Any] | None
    overview_excerpt: str
    flow_excerpt: str
    audience_excerpt: str
    anchor_excerpt: str
    flow_analysis: list[dict[str, str]]
    audience_status: dict[str, str]
    audience_profiles: dict[str, dict[str, str]]
    products: list[dict[str, str]]
    anchors: list[dict[str, str]]


def body_excerpt(driver: Any, limit: int = 5000) -> str:
    text = driver.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
    return compact_dashboard_text(text)[:limit]


def accessibility_text(driver: Any, limit: int = 30000) -> str:
    """Read component labels from Chrome's accessibility tree as a chart-data fallback."""
    try:
        tree = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})
    except Exception:
        return ""

    parts: list[str] = []
    seen: set[str] = set()
    for node in tree.get("nodes") or []:
        for key in ("name", "value", "description"):
            raw = node.get(key) or {}
            value = " ".join(str(raw.get("value") or "").split())
            if value and value not in seen:
                seen.add(value)
                parts.append(value)
    return " ".join(parts)[:limit]


def select_professional_tab(driver: Any) -> dict[str, Any] | None:
    handles = list(driver.window_handles)
    candidates: list[dict[str, Any]] = []
    for handle in handles:
        driver.switch_to.window(handle)
        candidates.append(
            {
                "handle": handle,
                "url": driver.current_url,
                "title": driver.title,
                "kind": page_kind_from_url(driver.current_url),
            }
        )
    for item in candidates:
        if "专业版" in (item["title"] or "") or "/screen/live/shop" in (item["url"] or ""):
            driver.switch_to.window(item["handle"])
            return {
                "selected_url": item["url"],
                "selected_title": item["title"],
                "candidate_count": len(candidates),
                "page_kind": "professional_dashboard",
                "preferred_kind": "professional_dashboard",
            }
    return activate_best_existing_tab(driver, preferred_kind="professional_dashboard")


def try_click_text(driver: Any, label: str, wait_seconds: float = 2.0) -> str:
    try:
        click_navigation_text(driver, label, timeout_seconds=8)
        time.sleep(wait_seconds)
        return body_excerpt(driver)
    except Exception:
        return ""


def click_visible_text(driver: Any, label: str) -> bool:
    xpath = f"//*[normalize-space(.)={json.dumps(label, ensure_ascii=False)}]"
    candidates: list[tuple[float, Any]] = []
    for element in driver.find_elements(By.XPATH, xpath):
        try:
            if not element.is_displayed():
                continue
            size = element.size
            area = float(size.get("width", 0)) * float(size.get("height", 0))
            if area <= 0:
                continue
            candidates.append((area, element))
        except Exception:
            continue

    for _area, element in sorted(candidates, key=lambda item: item[0]):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            try:
                element.click()
            except Exception:
                driver.execute_script("arguments[0].click();", element)
            return True
        except Exception:
            continue
    return False


def wait_for_crowd_page(driver: Any, timeout_seconds: float = 15.0) -> str:
    deadline = time.time() + timeout_seconds
    best_text = ""
    while time.time() < deadline:
        text = body_excerpt(driver, limit=30000)
        if text:
            best_text = text
        if "全场累计用户画像" in text:
            return text
        time.sleep(1.0)
    return best_text


def has_real_profile_values(text: str) -> bool:
    if not text:
        return False
    required_markers = ["看播核心用户画像", "购买核心用户画像"]
    if not all(marker in text for marker in required_markers):
        return False

    decisive_patterns = [
        r"(女|男)\s*[\d.]+%",
        r"\d{2}-\d{2}岁?\s*[\d.]+%",
        r"(辽宁|北京|天津|上海|重庆|河北|山西|内蒙古|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|台湾|香港|澳门)\s*[\d.]+%",
        r"手机价格:?\s*\d{4}-\d{4}\s*[\d.]+%",
        r"(精致妈妈|小镇青年|小镇中老年|Z世代|新锐白领|资深中产|都市蓝领|都市银发)\s*[\d.]+%",
    ]
    return any(re.search(pattern, text) for pattern in decisive_patterns)


def is_profile_loaded(text: str) -> bool:
    """Return true only when the page contains usable profile values."""
    return has_real_profile_values(text)


def wait_for_profile_loaded(
    driver: Any,
    timeout_seconds: float = 18.0,
    poll_seconds: float = 1.5,
    excerpt_limit: int = 30000,
) -> str:
    deadline = time.time() + timeout_seconds
    best_text = body_excerpt(driver, limit=excerpt_limit)
    while time.time() < deadline:
        text = body_excerpt(driver, limit=excerpt_limit)
        if text:
            best_text = text
        if is_profile_loaded(text):
            return text
        time.sleep(poll_seconds)
    return best_text


def click_sidebar_people_and_collect(driver: Any) -> tuple[str, str, str]:
    # The professional screen is a full-page component.  Its left navigation has
    # no text node for "人群", and a refresh immediately after switching often
    # returns Selenium to the data page.  Opening the documented #crowd anchor
    # directly keeps the audience page active while the full-session data loads.
    crowd_url = (driver.current_url or "").split("#", 1)[0] + "#crowd"
    driver.get(crowd_url)
    time.sleep(2.0)
    audience_excerpt = wait_for_profile_loaded(driver, timeout_seconds=36.0)
    if not audience_excerpt:
        audience_excerpt = wait_for_crowd_page(driver) or body_excerpt(driver, limit=30000)
    if not is_profile_loaded(audience_excerpt):
        # A single retry is useful for intermittent API loads, but preserve the
        # crowd hash so the browser does not fall back to the hidden data page.
        driver.get(crowd_url)
        time.sleep(2.0)
        driver.refresh()
        time.sleep(2.0)
        audience_excerpt = wait_for_profile_loaded(driver, timeout_seconds=36.0) or audience_excerpt
    audience_excerpt = " ".join(part for part in [audience_excerpt, accessibility_text(driver)] if part)

    # All-session watch/buy values are rendered together on #crowd.  The legend
    # is not interactable to Selenium while the full-page section is scaled, so
    # reuse the loaded complete excerpt rather than attempting hidden clicks.
    watch_all_excerpt = audience_excerpt
    buy_all_excerpt = audience_excerpt
    return audience_excerpt, watch_all_excerpt, buy_all_excerpt


def click_anchor_analysis_and_collect(driver: Any, timeout_seconds: float = 20.0) -> str:
    def click_anchor_tab() -> bool:
        try:
            return bool(
                driver.execute_script(
                    """
                    const nodes = Array.from(document.querySelectorAll('*')).filter(
                      el => (el.innerText || '').trim() === '主播分析' &&
                            el.getBoundingClientRect().width > 0 &&
                            el.getBoundingClientRect().height > 0
                    );
                    if (!nodes.length) return false;
                    const node = nodes.sort((a, b) =>
                      (a.getBoundingClientRect().width * a.getBoundingClientRect().height) -
                      (b.getBoundingClientRect().width * b.getBoundingClientRect().height)
                    )[0];
                    const target = node.closest('[class*="tab"]') || node;
                    target.scrollIntoView({block: 'center'});
                    target.click();
                    return true;
                    """
                )
            )
        except Exception:
            return False

    best_text = ""
    for attempt in range(2):
        if attempt:
            driver.refresh()
            time.sleep(3.0)
        if not click_anchor_tab():
            try:
                click_navigation_text(driver, "主播分析", timeout_seconds=5)
            except Exception:
                pass
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            text = body_excerpt(driver, limit=30000)
            if text:
                best_text = text
            if "以下主播按本场直播用户支付金额排序" in text and parse_anchor_analysis(text):
                return text
            time.sleep(1.0)
    return best_text


def load_previous_professional_result(result_output: str) -> dict[str, Any]:
    path = Path(result_output).resolve()
    candidates = [path, path.with_suffix(".raw.json")]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
    return {}


def same_live_room(first_url: str | None, second_url: str | None) -> bool:
    first = re.search(r"[?&]live_room_id=(\d+)", first_url or "")
    second = re.search(r"[?&]live_room_id=(\d+)", second_url or "")
    return bool(first and second and first.group(1) == second.group(1))


def profile_has_real_values(profile: dict[str, str]) -> bool:
    return any(value and value != "待补充" for value in (profile or {}).values())


def parse_flow_analysis(text: str) -> list[dict[str, str]]:
    if not text:
        return []
    known_channels = [
        "短视频引流",
        "直播推荐",
        "其他",
        "搜索",
        "抖音商城推荐",
        "关注",
        "个人主页&店铺&橱窗",
        "头条西瓜",
        "活动页",
    ]
    items: list[dict[str, str]] = []
    for name in known_channels:
        match = re.search(rf"{re.escape(name)}\s+([\d.]+%)", text)
        if match:
            items.append({"channel": name, "ratio": match.group(1)})
    return items


def parse_audience_status(text: str) -> dict[str, str]:
    watch_status = ""
    buy_status = ""
    if "看播核心用户画像 女" in text or "看播核心用户画像 男" in text:
        watch_status = "已提取全场画像"
    if "购买核心用户画像 女" in text or "购买核心用户画像 男" in text:
        buy_status = "已提取全场画像"
    if "看播核心用户画像" in text and "购买核心用户画像" in text:
        watch_block = text.split("看播核心用户画像", 1)[1].split("购买核心用户画像", 1)[0].strip()
        if "无法展示画像" in watch_block:
            watch_status = watch_block
    if "购买核心用户画像" in text:
        buy_tail = text.split("购买核心用户画像", 1)[1]
        for marker in ["全场看播用户", "全场购买用户", "近7场直播看播用户", "近7场直播购买用户", "近1分钟看播用户", "近5分钟购买用户", "性别分布"]:
            if marker in buy_tail:
                buy_tail = buy_tail.split(marker, 1)[0]
                break
        buy_block = buy_tail.strip()
        if "无法展示画像" in buy_block:
            buy_status = buy_block
    return {
        "watch_status": watch_status or "待补充",
        "buy_status": buy_status or "待补充",
    }


def parse_audience_profiles(text: str) -> dict[str, dict[str, str]]:
    result = {
        "watch": {
            "性别": "待补充",
            "年龄": "待补充",
            "地域": "待补充",
            "手机价格": "待补充",
            "八大消费人群": "待补充",
        },
        "buy": {
            "性别": "待补充",
            "年龄": "待补充",
            "地域": "待补充",
            "手机价格": "待补充",
            "八大消费人群": "待补充",
        },
    }
    if not text:
        return result

    watch_block = ""
    buy_block = ""
    if "看播核心用户画像" in text and "购买核心用户画像" in text:
        watch_block = text.split("看播核心用户画像", 1)[1].split("购买核心用户画像", 1)[0].strip()
    if "购买核心用户画像" in text:
        buy_tail = text.split("购买核心用户画像", 1)[1]
        for marker in ["全场看播用户", "全场购买用户", "近7场直播看播用户", "近7场直播购买用户", "近1分钟看播用户", "近5分钟购买用户", "性别分布"]:
            if marker in buy_tail:
                buy_tail = buy_tail.split(marker, 1)[0]
                break
        buy_block = buy_tail.strip()

    def normalize_phone_price(raw: str) -> str:
        raw = raw.replace(" ", "")
        match = re.search(r"(\d{4}-\d{4})([\d.]+%)", raw)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return "待补充"

    def parse_block(block: str) -> dict[str, str]:
        parsed = {
            "性别": "待补充",
            "年龄": "待补充",
            "地域": "待补充",
            "手机价格": "待补充",
            "八大消费人群": "待补充",
        }
        block = " ".join(block.split())
        gender = re.search(r"(女|男)\s*([\d.]+%)", block)
        if gender:
            parsed["性别"] = f"{gender.group(1)}{gender.group(2)}"
        age = re.search(r"(\d{2}-\d{2}岁?)\s*([\d.]+%)", block)
        if age:
            parsed["年龄"] = f"{age.group(1)}{age.group(2)}"
        region = re.search(
            r"(辽宁|北京|天津|上海|重庆|河北|山西|内蒙古|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|台湾|香港|澳门)\s*([\d.]+%)",
            block,
        )
        if region:
            parsed["地域"] = f"{region.group(1)}{region.group(2)}"
        phone = re.search(r"手机价格:?\s*([0-9%.\-\s]+)", block)
        if phone:
            parsed["手机价格"] = normalize_phone_price(phone.group(1))
        segment = re.search(r"(精致妈妈|小镇青年|小镇中老年|Z世代|新锐白领|资深中产|都市蓝领|都市银发)\s*([\d.]+%)", block)
        if segment:
            parsed["八大消费人群"] = f"{segment.group(1)}{segment.group(2)}"
        return parsed

    if watch_block:
        result["watch"] = parse_block(watch_block)
    if buy_block:
        result["buy"] = parse_block(buy_block)
    return result


def parse_single_audience_block(text: str) -> dict[str, str]:
    parsed = {
        "性别": "待补充",
        "年龄": "待补充",
        "地域": "待补充",
        "手机价格": "待补充",
        "八大消费人群": "待补充",
    }
    text = compact_dashboard_text(text)
    gender = re.search(r"(女|男)\s*([\d.]+%)", text)
    if gender:
        parsed["性别"] = f"{gender.group(1)}{gender.group(2)}"
    age = re.search(r"(\d{2}-\d{2}岁?)\s*([\d.]+%)", text)
    if age:
        parsed["年龄"] = f"{age.group(1)}{age.group(2)}"
    region = re.search(
        r"(辽宁|北京|天津|上海|重庆|河北|山西|内蒙古|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|广西|海南|四川|贵州|云南|西藏|陕西|甘肃|青海|宁夏|新疆|台湾|香港|澳门)\s*([\d.]+%)",
        text,
    )
    if region:
        parsed["地域"] = f"{region.group(1)}{region.group(2)}"
    phone = re.search(r"手机价格:?\s*([0-9%.\-\s]+)", text)
    if phone:
        raw = compact_dashboard_text(phone.group(1)).replace(" ", "")
        standard = re.search(r"(\d{4}-\d{4})([\d.]+%)", raw)
        if standard:
            parsed["手机价格"] = f"{standard.group(1)} {standard.group(2)}"
    segment = re.search(r"(精致妈妈|小镇青年|小镇中老年|Z世代|新锐白领|资深中产|都市蓝领|都市银发)\s*([\d.]+%)", text)
    if segment:
        parsed["八大消费人群"] = f"{segment.group(1)}{segment.group(2)}"
    return parsed


def parse_products(text: str) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    if not text:
        return products

    start = text.find("商品信息")
    if start == -1:
        return products
    end = len(text)
    for marker in ["共13条", "全场累计用户画像", "画像总结", "问题反馈"]:
        idx = text.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    section = text[start:end]
    pattern = re.compile(
        r"(?P<name>.+?)\s+讲解\s+(?P<explain>\d+)\s+次\s+¥(?P<price>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<click_people>\d+)\s+(?P<click_deal>[\d.]+%)\s+¥(?P<pay>[\d,]+(?:\.\d+)?)\s+"
        r"¥(?P<minute_peak>[\d,]+(?:\.\d+)?)\s+(?P<count>\d+)\s+查看详情"
    )
    for match in pattern.finditer(section):
        name = match.group("name").strip()
        for prefix in ["商品信息 到手价 商品点击人数 点击-成交转化率 累计用户支付金额 分钟最高用户支付金额 累计成交件数 操作 ", "编辑话术 "]:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
        products.append(
            {
                "商品名称": name,
                "讲解次数": match.group("explain"),
                "价格": match.group("price"),
                "商品点击人数": match.group("click_people"),
                "点击-成交转化率": match.group("click_deal"),
                "累计用户支付金额": match.group("pay"),
                "分钟最高用户支付金额": match.group("minute_peak"),
                "累计成交件数": match.group("count"),
            }
        )
    return products


def parse_anchor_analysis(text: str) -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    if not text:
        return anchors
    start = text.find("主播能力")
    if start == -1:
        start = text.find("直播时长 用户支付金额")
    if start == -1:
        return anchors
    end = len(text)
    for marker in ["已选", "全部评论", "全部商品", "问题反馈"]:
        idx = text.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    section = text[start:end]
    pattern = re.compile(
        r"(?P<name>[\u4e00-\u9fa5A-Za-z路]+)\s+"
        r"(?P<duration>(?:\d+小时\d+分钟|\d+小时|\d+分钟))\s+"
        r"¥(?P<pay>[\d,]+(?:\.\d+)?)\s+"
        r"¥(?P<per_min>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<peak>[\d,]+)\s+"
        r"(?P<avg>[\d.]+)"
    )
    for match in pattern.finditer(section):
        anchors.append(
            {
                "主播": match.group("name"),
                "直播时长": match.group("duration"),
                "用户支付金额": match.group("pay"),
                "平均每分钟用户支付金额": match.group("per_min"),
                "最高在线人数": match.group("peak"),
                "平均在线人数": match.group("avg"),
            }
        )
    return anchors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Douyin professional dashboard stage.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    previous_result = load_previous_professional_result(args.result_output) if args.result_output else {}
    payload = load_payload(Path(args.config).resolve())
    driver = open_or_attach(build_browser_config(payload))
    try:
        active_tab_info = select_professional_tab(driver)
        current_url = driver.current_url
        title = driver.title
        page_kind = page_kind_from_url(current_url)
        if previous_result and not same_live_room(current_url, previous_result.get("current_url")):
            previous_result = {}

        overview_excerpt = body_excerpt(driver)
        flow_excerpt = try_click_text(driver, "流量分析") or overview_excerpt
        anchor_excerpt = click_anchor_analysis_and_collect(driver) or overview_excerpt
        audience_excerpt, watch_all_excerpt, buy_all_excerpt = click_sidebar_people_and_collect(driver)
        combined_audience_text = " ".join(
            part for part in [audience_excerpt, watch_all_excerpt, buy_all_excerpt] if part
        )
        audience_profiles = parse_audience_profiles(audience_excerpt or overview_excerpt)
        if all(value == "待补充" for value in audience_profiles["watch"].values()):
            watch_all = parse_single_audience_block(watch_all_excerpt)
            if any(value != "待补充" for value in watch_all.values()):
                audience_profiles["watch"] = watch_all
        if all(value == "待补充" for value in audience_profiles["buy"].values()):
            buy_all = parse_single_audience_block(buy_all_excerpt)
            if any(value != "待补充" for value in buy_all.values()):
                audience_profiles["buy"] = buy_all

        previous_profiles = previous_result.get("audience_profiles") or {}
        if not profile_has_real_values(audience_profiles["watch"]):
            previous_watch = previous_profiles.get("watch") or {}
            if profile_has_real_values(previous_watch):
                audience_profiles["watch"] = previous_watch
        if not profile_has_real_values(audience_profiles["buy"]):
            previous_buy = previous_profiles.get("buy") or {}
            if profile_has_real_values(previous_buy):
                audience_profiles["buy"] = previous_buy
        parsed_anchors = parse_anchor_analysis(anchor_excerpt) or parse_anchor_analysis(overview_excerpt)
        if not parsed_anchors:
            parsed_anchors = previous_result.get("anchors") or []
        parsed_products = parse_products(overview_excerpt)
        if not parsed_products:
            parsed_products = previous_result.get("products") or []
        parsed_flow_analysis = parse_flow_analysis(flow_excerpt or overview_excerpt)
        if not parsed_flow_analysis:
            parsed_flow_analysis = previous_result.get("flow_analysis") or []
        parsed_audience_status = parse_audience_status(combined_audience_text or audience_excerpt or overview_excerpt)
        if not profile_has_real_values(audience_profiles["watch"]) and (previous_result.get("audience_status") or {}).get("watch_status"):
            parsed_audience_status["watch_status"] = (previous_result.get("audience_status") or {}).get("watch_status")
        elif profile_has_real_values(audience_profiles["watch"]):
            parsed_audience_status["watch_status"] = "已提取全场画像"
        if not profile_has_real_values(audience_profiles["buy"]) and (previous_result.get("audience_status") or {}).get("buy_status"):
            parsed_audience_status["buy_status"] = (previous_result.get("audience_status") or {}).get("buy_status")
        elif profile_has_real_values(audience_profiles["buy"]):
            parsed_audience_status["buy_status"] = "已提取全场画像"

        status = "ready"
        message = "已从当前专业版页面提取总览、流量分析、人群和主播分析文本。"
        if "专业版" not in (title or "") and page_kind != "professional_dashboard":
            status = "wrong_page"
            message = "当前页面不是专业版大屏页。"

        result = ProfessionalStageResult(
            status=status,
            message=message,
            current_url=current_url,
            title=title,
            active_tab_info=active_tab_info,
            overview_excerpt=overview_excerpt,
            flow_excerpt=flow_excerpt,
            audience_excerpt=combined_audience_text or audience_excerpt,
            anchor_excerpt=anchor_excerpt,
            flow_analysis=parsed_flow_analysis,
            audience_status=parsed_audience_status,
            audience_profiles=audience_profiles,
            products=parsed_products,
            anchors=parsed_anchors,
        )
        result_json = json.dumps(asdict(result), ensure_ascii=False, indent=2)
        if args.result_output:
            output_path = Path(args.result_output).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result_json, encoding="utf-8-sig")
            raw_output_path = output_path.with_suffix(".raw.json")
            raw_output_path.write_text(result_json, encoding="utf-8-sig")
        print(result_json)
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
