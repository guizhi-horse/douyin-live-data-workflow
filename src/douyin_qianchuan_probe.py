from __future__ import annotations

import json
import sys
from pathlib import Path

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


def main() -> int:
    payload = json.loads((ROOT / "config" / "douyin_workflow_config.json").read_text(encoding="utf-8"))
    driver = open_or_attach(build_browser_config(payload))
    try:
        tabs: list[dict[str, str]] = []
        target = None
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            tabs.append({"url": driver.current_url, "title": driver.title})
            if "qianchuan.jinritemai.com" in (driver.current_url or ""):
                target = handle
        if target:
            driver.switch_to.window(target)
        text = driver.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
        print(
            json.dumps(
                {
                    "current_url": driver.current_url,
                    "title": driver.title,
                    "tabs": tabs,
                    "excerpt": compact_dashboard_text(text)[:6000],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
