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
    collect_detail_candidates,
    collect_matching_rows,
    open_first_detail,
    page_kind_from_url,
)
from douyin_workflow_runner import build_plan, load_launch_config


@dataclass
class ListStageResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    target_dates: list[str]
    active_tab_info: dict[str, Any] | None
    matched_rows: list[dict[str, Any]]
    row_samples: list[str]
    detail_candidates: list[dict[str, Any]]
    detail_open_result: dict[str, Any] | None


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Douyin list-page stage.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--result-output", default="")
    parser.add_argument("--candidate-index", type=int, default=0)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    config = load_launch_config(config_path)
    plan = build_plan(config)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        active_tab_info = activate_best_existing_tab(driver, preferred_kind="list")
        current_url = driver.current_url
        title = driver.title
        page_kind = page_kind_from_url(current_url)
        target_dates = [item.target_date for item in plan.daily_runs]

        matched_rows: list[dict[str, Any]] = []
        row_samples: list[str] = []
        detail_candidates: list[dict[str, Any]] = []
        detail_open_result = None
        status = "ready"
        message = "Ready on the current list page."

        if page_kind != "list":
            status = "wrong_page"
            message = "Current page is not the live room list page."
        else:
            matched_rows, row_samples = collect_matching_rows(driver, target_dates)
            detail_candidates = collect_detail_candidates(driver, target_dates)
            message = f"Found {len(matched_rows)} matching records for the target date on the current list page."
            if any(row.get("is_live") for row in matched_rows):
                status = "live_in_progress"
                message = "The target session is still live, so collection should stop."
            elif detail_candidates:
                detail_open_result = open_first_detail(driver, target_dates, candidate_index=args.candidate_index)
                if detail_open_result:
                    message = f"Opened detail candidate {args.candidate_index + 1} from the list page."
                else:
                    status = "candidate_not_found"
                    message = f"Detail candidate index {args.candidate_index} is not available."

        result = ListStageResult(
            status=status,
            message=message,
            current_url=current_url,
            title=title,
            target_dates=target_dates,
            active_tab_info=active_tab_info,
            matched_rows=matched_rows,
            row_samples=row_samples,
            detail_candidates=detail_candidates,
            detail_open_result=detail_open_result,
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
