from __future__ import annotations

from typing import Any


def _cjk_score(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")


def fix_mojibake_text(text: str) -> str:
    if not text:
        return text

    candidates = [text]
    for decoder in ("gb18030", "gbk"):
        try:
            candidates.append(text.encode("utf-8", errors="ignore").decode(decoder, errors="ignore"))
        except Exception:
            pass

    best = text
    best_score = (_cjk_score(text), -text.count("�"))
    for candidate in candidates[1:]:
        score = (_cjk_score(candidate), -candidate.count("�"))
        if score > best_score:
            best = candidate
            best_score = score
    return best


def fix_mojibake_data(value: Any) -> Any:
    if isinstance(value, str):
        return fix_mojibake_text(value)
    if isinstance(value, list):
        return [fix_mojibake_data(item) for item in value]
    if isinstance(value, dict):
        return {fix_mojibake_text(str(key)): fix_mojibake_data(item) for key, item in value.items()}
    return value
