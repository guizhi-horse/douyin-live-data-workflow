from __future__ import annotations

import time
from typing import Any

import douyin_professional_stage_clean as base


def has_explicit_unavailable_profile(text: str) -> bool:
    return "无法展示画像" in (text or "") or "鏃犳硶灞曠ず鐢诲儚" in (text or "")


def wait_for_profile_loaded(driver: Any, timeout_seconds: float = 18.0, poll_seconds: float = 1.5) -> str:
    deadline = time.time() + timeout_seconds
    best_text = base.body_excerpt(driver, limit=30000)
    loaded_hits = 0

    while time.time() < deadline:
        text = base.body_excerpt(driver, limit=30000)
        if text:
            best_text = text
        if base.is_profile_loaded(text):
            loaded_hits += 1
            if loaded_hits >= 2:
                return text
        else:
            loaded_hits = 0
        time.sleep(poll_seconds)

    return best_text


def click_sidebar_people_and_collect(driver: Any) -> tuple[str, str, str]:
    # The left navigation item is icon-only in the professional dashboard.  Text
    # clicking can hit hidden labels, so open the documented route directly.
    crowd_url = (driver.current_url or "").split("#", 1)[0] + "#crowd"
    driver.get(crowd_url)
    time.sleep(2.0)

    # The first render may briefly show the realtime cards' "无法展示画像"
    # placeholders before the all-session summary arrives.  Those placeholders
    # are not a terminal state: wait specifically for actual profile values.
    audience_excerpt = wait_for_profile_loaded(driver, timeout_seconds=30.0)
    if not base.is_profile_loaded(audience_excerpt):
        driver.refresh()
        time.sleep(2.0)
        audience_excerpt = wait_for_profile_loaded(driver, timeout_seconds=30.0) or audience_excerpt

    # The page renders watch and purchase summaries together.  Reusing the same
    # complete snapshot avoids switching back to short realtime intervals.
    return audience_excerpt, audience_excerpt, audience_excerpt


def main() -> int:
    base.wait_for_profile_loaded = wait_for_profile_loaded
    base.click_sidebar_people_and_collect = click_sidebar_people_and_collect
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
