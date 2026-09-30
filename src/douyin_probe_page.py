from __future__ import annotations

import argparse
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

from douyin_browser_automation import build_browser_config, load_payload, open_or_attach
from douyin_live_collector import activate_best_existing_tab


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the current Douyin tab content.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--preferred-kind", default="")
    parser.add_argument("--title-keyword", default="")
    args = parser.parse_args()

    payload = load_payload(Path(args.config).resolve())
    driver = open_or_attach(build_browser_config(payload))
    try:
        if args.title_keyword:
            info = None
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                if args.title_keyword in (driver.title or ""):
                    info = {
                        "selected_url": driver.current_url,
                        "selected_title": driver.title,
                        "candidate_count": len(driver.window_handles),
                        "page_kind": "manual_title_match",
                        "preferred_kind": args.preferred_kind or None,
                    }
                    break
            if info is None:
                info = activate_best_existing_tab(driver, preferred_kind=args.preferred_kind or None)
        else:
            info = activate_best_existing_tab(driver, preferred_kind=args.preferred_kind or None)
        tabs: list[dict[str, str]] = []
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            tabs.append(
                {
                    "url": driver.current_url,
                    "title": driver.title,
                }
            )
        if info.get("selected_url"):
            for handle in driver.window_handles:
                driver.switch_to.window(handle)
                if driver.current_url == info["selected_url"] and driver.title == info["selected_title"]:
                    break
        text = driver.execute_script("return document.body ? (document.body.innerText || '') : '';") or ""
        result = {
            "active_tab_info": info,
            "tabs": tabs,
            "current_url": driver.current_url,
            "title": driver.title,
            "excerpt": " ".join(text.split())[:3000],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
