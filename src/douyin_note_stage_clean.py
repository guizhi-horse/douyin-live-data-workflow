from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

from douyin_text_fix import fix_mojibake_data, fix_mojibake_text


@dataclass
class NoteStageResult:
    status: str
    message: str
    note_path: str
    note_name: str
    session_heading: str
    sessions_in_note: int
    missing_sections: list[str]
    used_sources: list[str]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_optional_json(path_str: str | None) -> dict[str, Any]:
    if not path_str:
        return {}
    path = Path(path_str).resolve()
    if not path.exists():
        return {}
    return load_json(path)


def normalize_text(value: Any, default: str = "待补充") -> str:
    if value is None:
        return default
    text = " ".join(str(value).split())
    text = STRING_ALIASES.get(text, text)
    if not text or text == "?":
        return default
    return text


def format_money(value: Any) -> str:
    text = normalize_text(value)
    if text in {"待补充", "暂无", "暂无，报名立享"}:
        return text
    if text.startswith("¥"):
        return text
    if re.fullmatch(r"[\d,]+(?:\.\d+)?", text):
        return f"¥{text}"
    return text


def load_professional_result(path_str: str | None) -> dict[str, Any]:
    if not path_str:
        return {}
    path = Path(path_str).resolve()
    raw_path = path.with_suffix(".raw.json")
    if raw_path.exists():
        return load_json(raw_path)
    return load_optional_json(path_str)


def load_full_workflow_professional_result() -> dict[str, Any]:
    path = ROOT / "output" / "douyin_full_workflow_result.json"
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    stages = data.get("stages") or {}
    professional = stages.get("professional") or {}
    if not professional:
        return {}
    professional = fix_mojibake_data(professional)
    flow_map = {
        "闁婚悷娆忔閹存繄绌挎繛": "短视频引流",
        "闁烩晛鐡ㄩ幐閬嶅箳閵娿劌绀": "直播推荐",
        "闁稿繑婀圭划": "其他",
        "闁瑰吋绮庨崒": "搜索",
        "闁硅埖鐗犻悡鍫曞疮閸℃冨帞闁规亽鍔忓畷": "抖音商城推荐",
        "闁稿繗娅曢弫": "关注",
        "濞戞挻绂嶆潪鏉跨槣濡&閹煎瓨鍛鎳&婵妤勪含閻": "个人主页&店铺&橱窗",
        "濠㈣泛鐡ㄥ奸悷妤勬硶閹": "头条西瓜",
    }
    anchor_key_map = {
        "濞戞挾绮幐": "主播",
        "闁烩晛鐡ㄩ幐閬嶅籍閸鏇熸瘣": "直播时长",
        "闁烩偓鍔嶉崺娑㈠绩濞寸姵锕㈤崳鐐紣": "用户支付金额",
        "妤犵偛鍟垮煎骸袙韫囨挸鐎婚梺鐣屽枔閺併倝骞嬮柨瀣鏆滃ù鐘筹耿閸ｇ偓锛": "平均每分钟用户支付金额",
        "闁哄牊顨囧Ο鐑樿含缂佹儳銇樺Ч澶愬极": "最高在线人数",
        "妤犵偛鍟垮煎酣宕烽妸褍娈犲ù婊呭劋閺": "平均在线人数",
    }
    duration_map = {
        "2閻忓繐绻戝59闁告帒妫濋幐": "2小时59分钟",
        "3閻忓繐绻戝": "3小时",
    }
    professional["flow_analysis"] = [
        {
            "channel": flow_map.get(str(item.get("channel")), str(item.get("channel"))),
            "ratio": item.get("ratio"),
        }
        for item in (professional.get("flow_analysis") or [])
    ]
    cleaned_anchors = []
    for item in professional.get("anchors") or []:
        cleaned_item: dict[str, Any] = {}
        for key, value in item.items():
            cleaned_key = anchor_key_map.get(str(key), str(key))
            cleaned_item[cleaned_key] = duration_map.get(str(value), value)
        cleaned_anchors.append(cleaned_item)
    professional["anchors"] = cleaned_anchors
    return professional


DASHBOARD_CORE_ALIASES = {
    "ֱ����ɽ����": "直播间成交金额",
    "ֱ�����û�֧�����": "直播间用户支付金额",
    "Ͷ�����ģ����̰󶨣�": "投放消耗（店铺绑定）",
    "Ͷ�����ģ����̱�Ͷ��": "投放消耗（店铺被投）",
    "ǧ�ιۿ��û�֧�����": "千次观看用户支付金额",
    "�˿���": "退款金额",
    "ֱ����ۿ�����": "直播间观看人数",
    "ֱ����ɽ�����": "直播间成交人数",
    "�ɽ�����": "成交件数",
    "���-�ɽ�ת����": "点击-成交转化率",
    "�ۼƹۿ�����": "累计观看人数",
    "������˿��": "新增粉丝数",
    "�˾��ۿ�ʱ��": "人均观看时长",
    "����ȯ����֧�����": "消费券引导支付金额",
    "����ȯ����֧��ռ��": "消费券引导支付占比",
    "ƽ����������": "平均在线人数",
    "�����������": "最高在线人数",
}

DASHBOARD_PRODUCT_ALIASES = {
    "��Ʒ����": "商品名称",
    "���ּ�": "到手价",
    "�ع�-���ת����": "曝光-点击转化率",
    "���-�ɽ�ת����": "点击-成交转化率",
    "�ۼ��û�֧�����": "累计用户支付金额",
    "�ۼƳɽ�������": "累计成交订单数",
}

PROFESSIONAL_PRODUCT_ALIASES = {
    "商品名称": "商品名称",
    "�������": "讲解次数",
    "价格": "价格",
    "商品点击人数": "商品点击人数",
    "点击-成交�化率": "点击-成交转化率",
    "�计用户支付金�": "累计用户支付金额",
    "分钟�高用户支付金�": "分钟最高用户支付金额",
    "�\ue21d\ue178成交件数": "累计成交件数",
}

ANCHOR_ALIASES = {
    "主播": "主播",
    "直播时长": "直播时长",
    "用户�付金�": "用户支付金额",
    "平均每分钟用户支付金�": "平均每分钟用户支付金额",
    "�高在线人�": "最高在线人数",
    "平均在线人数": "平均在线人数",
    "濞戞挾绮幐": "主播",
    "闁烩晛鐡ㄩ幐閬嶅籍閸鏇熸瘣": "直播时长",
    "闁烩偓鍔嶉崺娑㈠绩濞寸姵锕㈤崳鐐紣": "用户支付金额",
    "妤犵偛鍟垮煎骸袙韫囨挸鐎婚梺鐣屽枔閺併倝骞嬮柨瀣鏆滃ù鐘筹耿閸ｇ偓锛": "平均每分钟用户支付金额",
    "闁哄牊顨囧Ο鐑樿含缂佹儳銇樺Ч澶愬极": "最高在线人数",
    "妤犵偛鍟垮煎酣宕烽妸褍娈犲ù婊呭劋閺": "平均在线人数",
    "娑撶粯鎸": "主播",
    "閻╁瓨鎸遍弮鍫曟毐": "直播时长",
    "閻€劍鍩涢弨娴犳﹢鍣炬０": "用户支付金额",
    "楠炲啿娼庡В蹇撳瀻闁界喓鏁ら幋閿嬫暜娴犳﹢鍣炬０": "平均每分钟用户支付金额",
    "閺堟妯烘躬缁惧じ姹夐弫": "最高在线人数",
    "楠炲啿娼庨崷銊у殠娴滅儤鏆": "平均在线人数",
}

AUDIENCE_KEY_ALIASES = {
    "�Ա�": "性别",
    "年龄": "年龄",
    "地域": "地域",
    "手机价格": "手机价格",
    "�\ue0a2��消费人群": "八大消费人群",
}

QIANCHUAN_ALIASES = {
    "净成交订单数": "净成交订单数",
    "净成交订单成本（元）": "净成交订单成本（元）",
    "净成交订单成本(元)": "净成交订单成本（元）",
    "用户实际支付净成交金额（元）": "用户实际支付净成交金额（元）",
    "用户实际支付净成交金额(元)": "用户实际支付净成交金额（元）",
    "净成交金额结算率": "净成交金额结算率",
    "净成交订单结算率": "净成交订单结算率",
    "1小时内退款订单数": "1小时内退款订单数",
    "1小时内退款金额（元）": "1小时内退款金额（元）",
    "1小时内退款金额(元)": "1小时内退款金额（元）",
    "1小时内退款率": "1小时内退款率",
    "整体成交订单数": "整体成交订单数",
    "GPM（元）": "GPM（元）",
    "GPM(元)": "GPM（元）",
    "观看成交转化率": "观看成交转化率",
    "整体成交订单成本（元）": "整体成交订单成本（元）",
    "整体成交订单成本(元)": "整体成交订单成本（元）",
    "用户实际支付金额（元）": "用户实际支付金额（元）",
    "用户实际支付金额(元)": "用户实际支付金额（元）",
    "整体成交智能优惠券金额（元）": "整体成交智能优惠券金额（元）",
    "整体成交智能优惠券金额(元)": "整体成交智能优惠券金额（元）",
    "电商平台补贴金额（元）": "电商平台补贴金额（元）",
    "电商平台补贴金额(元)": "电商平台补贴金额（元）",
    "直播间退款金额（元）": "直播间退款金额（元）",
    "直播间退款金额(元)": "直播间退款金额（元）",
    "直播间退款率": "直播间退款率",
    "直播间整体曝光次数": "直播间整体曝光次数",
    "曝光观看率（次数）": "曝光观看率（次数）",
    "曝光观看率(次数)": "曝光观看率（次数）",
    "直播间整体观看人数": "直播间整体观看人数",
    "直播间平均停留时长": "直播间平均停留时长",
    "直播间平均停留时长（整场）": "直播间平均停留时长",
    "直播间平均停留时长(整场)": "直播间平均停留时长",
    "直播间整体新增粉丝数": "直播间整体新增粉丝数",
    "直播间评论次数": "直播间评论次数",
    "直播间商品曝光次数": "直播间商品曝光次数",
    "直播间商品点击次数": "直播间商品点击次数",
    "分享次数": "分享次数",
    "分享率": "分享率",
    "整体消耗（元）": "整体消耗（元）",
    "整体消耗(元)": "整体消耗（元）",
    "综合成本（元）": "综合成本（元）",
    "综合成本(元)": "综合成本（元）",
    "整体支付ROI": "整体支付ROI",
    "综合营销ROI": "综合营销ROI",
    "整体成交金额（元）": "整体成交金额（元）",
    "整体成交金额(元)": "整体成交金额（元）",
    "净成交ROI": "净成交ROI",
    "净成交金额（元，常规口径）": "净成交金额（元，常规口径）",
    "净成交金额（元，乘方投放期间）": "净成交金额（元，乘方投放期间）",
    "乘方投放状态": "乘方投放状态",
    "���ɽ�������": "净成交订单数",
    "���ɽ������ɱ���Ԫ��": "净成交订单成本（元）",
    "�û�ʵ��֧�����ɽ���Ԫ��": "用户实际支付净成交金额（元）",
    "���ɽ���������": "净成交金额结算率",
    "���ɽ�����������": "净成交订单结算率",
    "1Сʱ���˿����": "1小时内退款订单数",
    "1Сʱ���˿��Ԫ��": "1小时内退款金额（元）",
    "1Сʱ���˿���": "1小时内退款率",
    "����ɽ�������": "整体成交订单数",
    "GPM��Ԫ��": "GPM（元）",
    "�ۿ��ɽ�ת����": "观看成交转化率",
    "����ɽ������ɱ���Ԫ��": "整体成交订单成本（元）",
    "�û�ʵ��֧����Ԫ��": "用户实际支付金额（元）",
    "����ɽ������Ż�ȯ��Ԫ��": "整体成交智能优惠券金额（元）",
    "����ƽ̨������Ԫ��": "电商平台补贴金额（元）",
    "ֱ�����˿��Ԫ��": "直播间退款金额（元）",
    "ֱ�����˿���": "直播间退款率",
    "ֱ���������ع����": "直播间整体曝光次数",
    "�ع�ۿ��ʣ�������": "曝光观看率（次数）",
    "ֱ��������ۿ�����": "直播间整体观看人数",
    "ֱ����ƽ��ͣ��ʱ��": "直播间平均停留时长",
    "ֱ��������������˿��": "直播间整体新增粉丝数",
    "ֱ�������۴���": "直播间评论次数",
    "ֱ������Ʒ�ع����": "直播间商品曝光次数",
    "ֱ������Ʒ�������": "直播间商品点击次数",
    "��������": "分享次数",
    "������": "分享率",
    "�������ģ�Ԫ��": "整体消耗（元）",
    "����֧��ROI": "整体支付ROI",
    "����ɽ���Ԫ��": "整体成交金额（元）",
    "���ɽ�ROI": "净成交ROI",
    "���ɽ���Ԫ��": "净成交金额（元）",
}

STRING_ALIASES = {
    "�视�引�": "短视频引流",
    "�人主�&店铺&橱窗": "个人主页&店铺&橱窗",
    "直播间在线人数过� 无法展示画像": "直播间在线人数过少，无法展示画像",
    "�5分钟成交人数过少 无法展示画像": "近5分钟成交人数过少，无法展示画像",
    "闁婚悷娆忔閹存繄绌挎繛": "短视频引流",
    "闁烩晛鐡ㄩ幐閬嶅箳閵娿劌绀": "直播推荐",
    "闁稿繑婀圭划": "其他",
    "闁瑰吋绮庨崒": "搜索",
    "闁硅埖鐗犻悡鍫曞疮閸℃冨帞闁规亽鍔忓畷": "抖音商城推荐",
    "闁稿繗娅曢弫": "关注",
    "濞戞挻绂嶆潪鏉跨槣濡&閹煎瓨鍛鎳&婵妤勪含閻": "个人主页&店铺&橱窗",
    "濠㈣泛鐡ㄥ奸悷妤勬硶閹": "头条西瓜",
    "2閻忓繐绻戝59闁告帒妫濋幐": "2小时59分钟",
    "3閻忓繐绻戝": "3小时",
    "閻鐟欏棝鎴濈穿濞": "短视频引流",
    "閻╁瓨鎸遍幒銊ㄥ礃": "直播推荐",
    "閸忔湹绮": "其他",
    "閹兼粎鍌": "搜索",
    "閹舵牠鐓堕崯鍡楃厔閹恒劏宕": "抖音商城推荐",
    "閸忚櫕鏁": "关注",
    "娑撴禍杞板瘜妞&鎼存呮懙&濮楄京鐛": "个人主页&店铺&橱窗",
    "婢跺瓨娼鐟楄法鎽": "头条西瓜",
    "2鐏忓繑妞59閸掑棝鎸": "2小时59分钟",
    "3鐏忓繑妞": "3小时",
}


def canonicalize_dict(data: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        canonical_key = aliases.get(key, key)
        if isinstance(value, str):
            value = STRING_ALIASES.get(value, value)
        result[canonical_key] = value
    return result


def canonicalize_dashboard_result(data: dict[str, Any]) -> dict[str, Any]:
    core = canonicalize_dict(data.get("core_metrics") or {}, DASHBOARD_CORE_ALIASES)
    products = [
        canonicalize_dict(item, DASHBOARD_PRODUCT_ALIASES)
        for item in (data.get("products") or [])
    ]
    data["core_metrics"] = core
    data["products"] = products
    return data


def canonicalize_professional_result(data: dict[str, Any]) -> dict[str, Any]:
    data["flow_analysis"] = [
        {"channel": STRING_ALIASES.get(item.get("channel"), item.get("channel")), "ratio": item.get("ratio")}
        for item in (data.get("flow_analysis") or [])
    ]
    status = data.get("audience_status") or {}
    data["audience_status"] = {
        "watch_status": STRING_ALIASES.get(status.get("watch_status"), status.get("watch_status")),
        "buy_status": STRING_ALIASES.get(status.get("buy_status"), status.get("buy_status")),
    }
    profiles = data.get("audience_profiles") or {}
    data["audience_profiles"] = {
        "watch": canonicalize_dict(profiles.get("watch") or {}, AUDIENCE_KEY_ALIASES),
        "buy": canonicalize_dict(profiles.get("buy") or {}, AUDIENCE_KEY_ALIASES),
    }
    data["products"] = [
        canonicalize_dict(item, PROFESSIONAL_PRODUCT_ALIASES)
        for item in (data.get("products") or [])
    ]
    data["anchors"] = [
        canonicalize_dict(item, ANCHOR_ALIASES)
        for item in (data.get("anchors") or [])
    ]
    return data


def merge_professional_result(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        return primary
    merged = dict(primary)
    for key in ("flow_analysis", "products", "anchors"):
        if not merged.get(key):
            merged[key] = fallback.get(key) or []

    primary_status = merged.get("audience_status") or {}
    fallback_status = fallback.get("audience_status") or {}
    merged["audience_status"] = {
        "watch_status": primary_status.get("watch_status") or fallback_status.get("watch_status"),
        "buy_status": primary_status.get("buy_status") or fallback_status.get("buy_status"),
    }

    primary_profiles = merged.get("audience_profiles") or {}
    fallback_profiles = fallback.get("audience_profiles") or {}
    merged_profiles: dict[str, dict[str, Any]] = {}
    for group in ("watch", "buy"):
        primary_group = primary_profiles.get(group) or {}
        fallback_group = fallback_profiles.get(group) or {}
        merged_group: dict[str, Any] = {}
        for field in ("性别", "年龄", "地域", "手机价格", "八大消费人群"):
            primary_value = primary_group.get(field)
            fallback_value = fallback_group.get(field)
            merged_group[field] = (
                primary_value
                if normalize_text(primary_value) != "待补充"
                else fallback_value
            )
        merged_profiles[group] = merged_group
    merged["audience_profiles"] = merged_profiles
    return merged


def canonicalize_qianchuan_result(data: dict[str, Any]) -> dict[str, Any]:
    data["core_metrics"] = canonicalize_dict(data.get("core_metrics") or {}, QIANCHUAN_ALIASES)
    metrics = data.get("core_metrics") or {}
    excerpt = normalize_text(metrics.get("page_excerpt"), "")
    current_duration = normalize_text(metrics.get("直播间平均停留时长"))
    if excerpt and current_duration in {"1", "待补充"}:
        match = re.search(r"直播间平均停留时长(?:\(整场\)|（整场）)?\s*([0-9]+分)\s*([0-9]+秒)", excerpt)
        if match:
            metrics["直播间平均停留时长"] = f"{match.group(1)}{match.group(2)}"
        else:
            match = re.search(r"直播间平均停留时长(?:\(整场\)|（整场）)?\s*([0-9]+分钟)\s*([0-9]+秒)", excerpt)
            if match:
                metrics["直播间平均停留时长"] = f"{match.group(1)}{match.group(2)}"
    return data


def clean_numeric_text(text: str) -> str:
    text = text.replace(" ", "")
    text = text.replace("¥", "")
    return text


def fill_dashboard_core_from_excerpt(core: dict[str, Any], supplementary_text: str = "") -> dict[str, Any]:
    excerpt = " ".join(
        part
        for part in [normalize_text(core.get("page_excerpt"), ""), normalize_text(supplementary_text, "")]
        if part
    )
    if not excerpt:
        return core
    patterns = {
        "直播间用户支付金额": r"直播间用户支付金额\s*¥?\s*([\d,\s.]+)",
        "成交件数": r"成交件数\s*([\d,]+)",
        "直播间成交人数": r"成交人数\s*([\d,]+)",
        "点击-成交转化率": r"(?:点击-成交转化率|商品点击-成交率(?:\(人数\))?)\s*([\d.]+%)",
        "千次观看用户支付金额": r"千次观看用户支付金额\s*¥?\s*([\d,\s.]+)",
        "消费券引导支付金额": r"消费券引导支付金额\s*([^\s]+)",
        "平均在线人数": r"平均在线人数\s*([\d,]+)",
        "累计观看人数": r"累计观看人数\s*([\d,]+)",
        "新增粉丝数": r"新增粉丝数\s*([\d,]+)",
        "人均观看时长": r"人均观看时长\s*([^\s]+)",
        "消费券引导支付占比": r"消费券引导支付占比\s*([^\s]+)",
    }
    for key, pattern in patterns.items():
        current = normalize_text(core.get(key))
        if current != "待补充" and current not in {"85,8783838,888"}:
            continue
        match = re.search(pattern, excerpt)
        if match:
            value = clean_numeric_text(match.group(1)) if "金额" in key else match.group(1)
            core[key] = value
    return core


def extract_time_range(detail_result: dict[str, Any]) -> tuple[str, str]:
    candidates = [
        normalize_text(((detail_result.get("detail_page_state") or {}).get("page_excerpt")), ""),
        normalize_text(((detail_result.get("detail_open_result") or {}).get("row_text")), ""),
    ]
    patterns = [
        r"直播时间\s+\d{4}/\d{2}/\d{2}\s+(\d{2}:\d{2})\s*-\s*\d{4}/\d{2}/\d{2}\s+(\d{2}:\d{2})",
        r"\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})\s*~\s*\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2})",
        r"(\d{2}:\d{2})\s*~\s*(\d{2}:\d{2})",
    ]
    for text in candidates:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1), match.group(2)
        times = re.findall(r"\b(\d{2}:\d{2})\b", text)
        if len(times) >= 2:
            return times[0], times[1]
    return "00:00", "00:00"


def note_name_from_date(target_date: str) -> str:
    year, month, day = target_date.split("-")
    return f"{int(year)}.{int(month)}.{int(day)}直播数据"


def resolve_note_path(target_date: str, output_dir: str) -> tuple[Path, str]:
    configured_dir = output_dir.strip()
    if not configured_dir or configured_dir.startswith("请改成"):
        raise ValueError("配置中的 obsidian_output_path 未设置为有效目录。")
    note_dir = Path(configured_dir)
    note_dir.mkdir(parents=True, exist_ok=True)
    note_name = note_name_from_date(target_date)
    return note_dir / f"{note_name}.md", note_name


def extract_from_text(pattern: str, text: str, default: str = "待补充") -> str:
    match = re.search(pattern, text)
    if not match:
        return default
    return normalize_text(match.group(1), default)


def build_people_section(core: dict[str, Any]) -> list[str]:
    return [
        "### 人气数据",
        f"- 平均在线人数：{normalize_text(core.get('平均在线人数'))}",
        f"- 累计观看人数：{normalize_text(core.get('累计观看人数'))}",
        f"- 新增粉丝数：{normalize_text(core.get('新增粉丝数'))}",
        f"- 人均观看时长：{normalize_text(core.get('人均观看时长'))}",
        f"- 消费券引导支付占比：{normalize_text(core.get('消费券引导支付占比'))}",
        "",
    ]


def extract_money_after_label(text: str, label: str, default: str = "待补充") -> str:
    match = re.search(rf"{re.escape(label)}\s*¥?\s*([\d,\s.]+)", text)
    if not match:
        return default
    value = clean_numeric_text(match.group(1))
    return value or default


def choose_more_precise_numeric(*values: Any) -> str:
    best = "待补充"
    best_score = -1
    for value in values:
        text = normalize_text(value)
        if text == "待补充":
            continue
        candidate = clean_numeric_text(text)
        score = len(candidate)
        if "." in candidate:
            score += 10
        if score > best_score:
            best = candidate
            best_score = score
    return best


def build_sales_section(core: dict[str, Any], detail_text: str, dashboard_text: str, professional_text: str) -> list[str]:
    watch_deal_rate = extract_from_text(r"观看-成交率\(人数\)\s*([\d.]+%)", detail_text)
    fan_ratio = extract_from_text(r"成交粉丝占比\s*([\d.]+%)", dashboard_text)
    user_payment = choose_more_precise_numeric(
        extract_money_after_label(professional_text, "直播间用户支付金额"),
        extract_money_after_label(dashboard_text, "直播间用户支付金额"),
        core.get("直播间用户支付金额"),
    )
    return [
        "### 带货数据",
        f"- 直播间用户支付金额（含异常交易）：{format_money(user_payment)}",
        f"- 成交件数：{normalize_text(core.get('成交件数'))}",
        f"- 成交人数：{normalize_text(core.get('直播间成交人数'))}",
        f"- 点击成交率：{normalize_text(core.get('点击-成交转化率'))}",
        f"- 观看-成交率（人数）：{watch_deal_rate}",
        f"- 千次观看用户支付金额：{format_money(core.get('千次观看用户支付金额'))}",
        f"- 成交粉丝占比：{fan_ratio}",
        f"- 消费券引导支付金额：{normalize_text(core.get('消费券引导支付金额'))}",
        "",
    ]


def build_flow_section(pro_result: dict[str, Any]) -> list[str]:
    items = pro_result.get("flow_analysis") or []
    if not items:
        return ["### 流量分析", "- 待专业屏补充", ""]
    lines = ["### 流量分析"]
    for item in items:
        channel = normalize_text(item.get("channel"))
        ratio = normalize_text(item.get("ratio"))
        lines.append(f"- {channel}：{ratio}")
    lines.append("")
    return lines


def build_audience_section(pro_result: dict[str, Any]) -> list[str]:
    profiles = pro_result.get("audience_profiles") or {}
    watch = profiles.get("watch") or {}
    buy = profiles.get("buy") or {}
    status = pro_result.get("audience_status") or {}
    return [
        "### 人群分析",
        "### 看播核心用户画像",
        f"- 性别：{normalize_text(watch.get('性别'))}",
        f"- 年龄：{normalize_text(watch.get('年龄'))}",
        f"- 地域：{normalize_text(watch.get('地域'))}",
        f"- 手机价格：{normalize_text(watch.get('手机价格'))}",
        f"- 八大消费人群：{normalize_text(watch.get('八大消费人群'))}",
        f"- 状态：{normalize_text(status.get('watch_status'))}",
        "",
        "### 购买核心用户画像",
        f"- 性别：{normalize_text(buy.get('性别'))}",
        f"- 年龄：{normalize_text(buy.get('年龄'))}",
        f"- 地域：{normalize_text(buy.get('地域'))}",
        f"- 手机价格：{normalize_text(buy.get('手机价格'))}",
        f"- 八大消费人群：{normalize_text(buy.get('八大消费人群'))}",
        f"- 状态：{normalize_text(status.get('buy_status'))}",
        "",
    ]


def build_summary_section(pro_result: dict[str, Any]) -> list[str]:
    profiles = pro_result.get("audience_profiles") or {}
    watch = profiles.get("watch") or {}
    buy = profiles.get("buy") or {}
    watch_seg = normalize_text(watch.get("八大消费人群"))
    buy_seg = normalize_text(buy.get("八大消费人群"))
    watch_gender = normalize_text(watch.get("性别"))
    watch_age = normalize_text(watch.get("年龄"))
    buy_gender = normalize_text(buy.get("性别"))
    buy_age = normalize_text(buy.get("年龄"))

    if watch_seg == "待补充" and buy_seg == "待补充":
        status = pro_result.get("audience_status") or {}
        return [
            "### 画像总结",
            f"- 看播画像当前状态：{normalize_text(status.get('watch_status'))}。",
            f"- 购买画像当前状态：{normalize_text(status.get('buy_status'))}。",
            "",
        ]

    return [
        "### 画像总结",
        f"- 看播画像以{watch_seg}为主，{watch_gender}、{watch_age}更集中。",
        f"- 购买画像以{buy_seg}为主，{buy_gender}、{buy_age}占比更高。",
        "",
    ]


def merge_products(
    dashboard_products: list[dict[str, Any]],
    professional_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pro_map: dict[str, dict[str, Any]] = {}
    for item in professional_products:
        name = normalize_text(item.get("商品名称"))
        if name != "待补充":
            pro_map[name] = item

    merged: list[dict[str, Any]] = []
    for item in dashboard_products:
        name = normalize_text(item.get("商品名称"))
        if name == "待补充":
            continue
        pro_item = pro_map.get(name, {})
        merged.append(
            {
                "商品名称": name,
                "价格": normalize_text(item.get("到手价")),
                "成交件数": normalize_text(item.get("累计成交订单数")),
                "成交金额": normalize_text(item.get("累计用户支付金额")),
                "曝光-点击转化率": normalize_text(item.get("曝光-点击转化率")),
                "点击-成交转化率": normalize_text(item.get("点击-成交转化率")),
                "讲解次数": normalize_text(pro_item.get("讲解次数")),
            }
        )
    return merged


def build_products_section(products: list[dict[str, Any]]) -> list[str]:
    lines = ["### 当前购物车商品"]
    if not products:
        return ["### 当前购物车商品", "- 待补充", ""]
    for item in products:
        lines.extend(
            [
                f"### {normalize_text(item.get('商品名称'))}",
                f"- 价格：{format_money(item.get('价格'))}",
                f"- 成交件数：{normalize_text(item.get('成交件数'))}",
                f"- 成交金额：{format_money(item.get('成交金额'))}",
                f"- 曝光-点击转化率：{normalize_text(item.get('曝光-点击转化率'))}",
                f"- 点击-成交转化率：{normalize_text(item.get('点击-成交转化率'))}",
                f"- 讲解次数：{normalize_text(item.get('讲解次数'))}",
            ]
        )
    lines.append("")
    return lines


def build_anchor_section(pro_result: dict[str, Any]) -> list[str]:
    anchors = pro_result.get("anchors") or []
    if not anchors:
        return ["### 主播分析", "- 待专业屏补充", ""]

    lines = ["### 主播分析", f"本场直播共{len(anchors)}位主播接力：", ""]
    for idx, item in enumerate(anchors, start=1):
        lines.extend(
            [
                f"### {normalize_text(item.get('主播'))}（第{idx}时段）",
                f"- 直播时长：{normalize_text(item.get('直播时长'))}",
                f"- 用户支付金额：{format_money(item.get('用户支付金额'))}",
                f"- 平均每分钟用户支付金额：{format_money(item.get('平均每分钟用户支付金额'))}",
                f"- 最高在线人数：{normalize_text(item.get('最高在线人数'))}",
                f"- 平均在线人数：{normalize_text(item.get('平均在线人数'))}",
                "- 能力图谱维度：引流、互动、转化、加团、转粉、留存",
                "",
            ]
        )

    if len(anchors) >= 2:
        sorted_anchors = sorted(
            anchors,
            key=lambda item: (
                float(str(normalize_text(item.get("平均在线人数"), "0")).replace("%", "") or "0"),
                float(str(normalize_text(item.get("平均每分钟用户支付金额"), "0")).replace(",", "") or "0"),
            ),
            reverse=True,
        )
        first, second = sorted_anchors[:2]
        lines.append(
            f"> **主播对比**：{normalize_text(first.get('主播'))}平均在线更高"
            f"（{normalize_text(first.get('平均在线人数'))} vs {normalize_text(second.get('平均在线人数'))}），"
            f"且均分钟产出更高（{format_money(first.get('平均每分钟用户支付金额'))} vs {format_money(second.get('平均每分钟用户支付金额'))}）。"
        )
        lines.append("")
    return lines


def build_qianchuan_section(qianchuan_result: dict[str, Any]) -> list[str]:
    metrics = qianchuan_result.get("core_metrics") or {}
    if not metrics:
        return ["### 千川核心数据", "- 待补充", ""]

    field_order = [
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
    lines = ["### 千川核心数据"]
    money_fields = {
        "净成交订单成本（元）",
        "用户实际支付净成交金额（元）",
        "1小时内退款金额（元）",
        "GPM（元）",
        "整体成交订单成本（元）",
        "用户实际支付金额（元）",
        "整体成交智能优惠券金额（元）",
        "电商平台补贴金额（元）",
        "直播间退款金额（元）",
        "整体消耗（元）",
        "综合成本（元）",
        "整体成交金额（元）",
        "净成交金额（元，常规口径）",
        "净成交金额（元，乘方投放期间）",
    }
    for field in field_order:
        value = metrics.get(field)
        if field == "净成交金额（元，乘方投放期间）" and not value:
            rendered = "不适用"
        else:
            rendered = format_money(value) if field in money_fields else normalize_text(value)
        lines.append(f"- {field}：{rendered}")
    lines.append("")
    return lines


def build_session_body(
    detail_result: dict[str, Any],
    dashboard_result: dict[str, Any],
    professional_result: dict[str, Any],
    qianchuan_result: dict[str, Any],
) -> list[str]:
    core = dashboard_result.get("core_metrics") or {}
    dashboard_products = dashboard_result.get("products") or []
    professional_products = professional_result.get("products") or []
    products = merge_products(dashboard_products, professional_products)
    detail_text = normalize_text(((detail_result.get("detail_page_state") or {}).get("page_excerpt")), "")
    dashboard_text = normalize_text(core.get("page_excerpt"), "")
    professional_text = normalize_text(professional_result.get("overview_excerpt"), "")

    lines: list[str] = []
    lines.extend(build_people_section(core))
    lines.extend(build_sales_section(core, detail_text, dashboard_text, professional_text))
    lines.extend(build_flow_section(professional_result))
    lines.extend(build_audience_section(professional_result))
    lines.extend(build_summary_section(professional_result))
    lines.extend(build_products_section(products))
    lines.extend(build_anchor_section(professional_result))
    lines.extend(build_qianchuan_section(qianchuan_result))
    return lines


def parse_existing_sessions(note_text: str) -> list[dict[str, str]]:
    pattern = re.compile(r"(?ms)^## 第(\d+)场 (\d{2}:\d{2})-(\d{2}:\d{2})\n(.*?)(?=^## 第\d+场 |\Z)")
    sessions: list[dict[str, str]] = []
    for match in pattern.finditer(note_text):
        start_hm, end_hm, body = match.group(2), match.group(3), match.group(4).rstrip()
        if start_hm == "00:00" and end_hm == "00:00":
            continue
        sessions.append({"start": start_hm, "end": end_hm, "body": body})
    return sessions


def render_sessions(sessions: list[dict[str, str]]) -> str:
    sessions = sorted(sessions, key=lambda item: item["start"])
    blocks: list[str] = []
    for idx, item in enumerate(sessions, start=1):
        heading = f"## 第{idx}场 {item['start']}-{item['end']}"
        body = item["body"].strip()
        blocks.append(f"{heading}\n{body}")
    return "\n\n".join(blocks).strip() + "\n"


def upsert_session(note_path: Path, start_hm: str, end_hm: str, body_lines: list[str]) -> tuple[str, int]:
    existing_text = note_path.read_text(encoding="utf-8-sig") if note_path.exists() else ""
    sessions = parse_existing_sessions(existing_text)
    new_body = "\n".join(body_lines).strip()

    replaced = False
    for item in sessions:
        if item["start"] == start_hm and item["end"] == end_hm:
            item["body"] = new_body
            replaced = True
            break

    if not replaced:
        sessions.append({"start": start_hm, "end": end_hm, "body": new_body})

    rendered = render_sessions(sessions)
    note_path.write_text(rendered, encoding="utf-8-sig")

    sorted_sessions = sorted(sessions, key=lambda item: item["start"])
    session_index = next(
        idx for idx, item in enumerate(sorted_sessions, start=1)
        if item["start"] == start_hm and item["end"] == end_hm
    )
    return f"## 第{session_index}场 {start_hm}-{end_hm}", len(sorted_sessions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write collected Douyin data into an Obsidian note.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--detail-result", required=True)
    parser.add_argument("--dashboard-result", required=True)
    parser.add_argument("--professional-result", default="")
    parser.add_argument("--qianchuan-result", default="")
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    config = load_json(Path(args.config).resolve())
    detail_result = load_json(Path(args.detail_result).resolve())
    dashboard_result = canonicalize_dashboard_result(load_json(Path(args.dashboard_result).resolve()))
    professional_result = canonicalize_professional_result(load_professional_result(args.professional_result))
    full_workflow_professional = canonicalize_professional_result(load_full_workflow_professional_result())
    professional_result = merge_professional_result(professional_result, full_workflow_professional)
    dashboard_result["core_metrics"] = fill_dashboard_core_from_excerpt(
        dashboard_result.get("core_metrics") or {},
        str(professional_result.get("overview_excerpt") or ""),
    )
    qianchuan_result = canonicalize_qianchuan_result(load_optional_json(args.qianchuan_result))

    target_date = str(config.get("target_date") or "2026-06-03")
    note_path, note_name = resolve_note_path(target_date, str(config.get("obsidian_output_path") or ""))
    start_hm, end_hm = extract_time_range(detail_result)

    session_body = build_session_body(detail_result, dashboard_result, professional_result, qianchuan_result)
    session_heading, sessions_in_note = upsert_session(note_path, start_hm, end_hm, session_body)

    missing_sections: list[str] = []
    if not professional_result:
        missing_sections.extend(["流量分析", "人群分析", "画像总结", "主播分析"])
    if not qianchuan_result:
        missing_sections.append("千川核心数据")

    result = NoteStageResult(
        status="ready",
        message="Created or updated the Obsidian note from the current collected results.",
        note_path=str(note_path),
        note_name=note_name,
        session_heading=session_heading,
        sessions_in_note=sessions_in_note,
        missing_sections=missing_sections,
        used_sources=[
            "douyin_detail_stage_result.json",
            "douyin_dashboard_stage_result.json",
            *(["douyin_professional_stage_result.json"] if professional_result else []),
            *(["douyin_qianchuan_stage_result.json"] if qianchuan_result else []),
        ],
    )
    result_json = json.dumps(asdict(result), ensure_ascii=False, indent=2)
    if args.result_output:
        output_path = Path(args.result_output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_json, encoding="utf-8-sig")
    print(result_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
