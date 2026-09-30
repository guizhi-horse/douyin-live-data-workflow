from __future__ import annotations

import argparse
import json
import sys
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
from douyin_live_collector import (
    activate_best_existing_tab,
    open_live_dashboard,
    page_kind_from_url,
    wait_for_detail_page_ready,
)


@dataclass
class DetailStageResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    active_tab_info: dict[str, Any] | None
    detail_page_state: dict[str, Any] | None
    dashboard_open_result: dict[str, Any] | None


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Douyin detail-page stage.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        active_tab_info = activate_best_existing_tab(driver, preferred_kind="detail")
        current_url = driver.current_url
        title = driver.title
        page_kind = page_kind_from_url(current_url)
        detail_page_state = None
        dashboard_open_result = None
        status = "ready"
        message = "Ready on the current detail page."

        if page_kind != "detail":
            status = "wrong_page"
            message = "Current page is not a live detail page."
        else:
            detail_page_state = wait_for_detail_page_ready(driver, retries=3, wait_seconds=4.0)
            status = detail_page_state.get("state", "unknown")
            message = f"Detail page state: {status}."
            if status == "finished":
                dashboard_open_result = open_live_dashboard(driver)
                if dashboard_open_result:
                    message = "Detail page is finished, and opening the live dashboard was attempted."

        result = DetailStageResult(
            status=status,
            message=message,
            current_url=current_url,
            title=title,
            active_tab_info=active_tab_info,
            detail_page_state=detail_page_state,
            dashboard_open_result=dashboard_open_result,
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
