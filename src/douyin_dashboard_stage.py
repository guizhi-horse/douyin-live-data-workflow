from __future__ import annotations

import argparse
import json
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
from douyin_live_collector import activate_best_existing_tab, extract_core_metrics, page_kind_from_url


@dataclass
class DashboardStageResult:
    status: str
    message: str
    current_url: str | None
    title: str | None
    active_tab_info: dict[str, Any] | None
    core_metrics: dict[str, Any]
    products: list[dict[str, Any]]


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Douyin dashboard stage.")
    parser.add_argument("--config", default=str(ROOT / "config" / "douyin_workflow_config.json"))
    parser.add_argument("--result-output", default="")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    payload = load_payload(config_path)
    browser_config = build_browser_config(payload)
    driver = open_or_attach(browser_config)

    try:
        active_tab_info = activate_best_existing_tab(driver, preferred_kind="dashboard")
        current_url = driver.current_url
        title = driver.title
        page_kind = page_kind_from_url(current_url)
        status = "ready"
        message = "Ready on the current dashboard page."
        core_metrics: dict[str, Any] = {}
        products: list[dict[str, Any]] = []

        if page_kind == "professional_dashboard":
            base_dashboard_url = current_url.replace("/screen/live/shop", "/screen/shop/main", 1)
            driver.get(base_dashboard_url)
            time.sleep(3.0)
            current_url = driver.current_url
            title = driver.title
            page_kind = page_kind_from_url(current_url)

        if page_kind != "dashboard":
            status = "wrong_page"
            message = "Current page is not the live dashboard page."
        else:
            core_metrics = extract_core_metrics(driver)
            products = core_metrics.pop("products", [])
            message = "Extracted the first batch of core metrics from the current live dashboard."

        result = DashboardStageResult(
            status=status,
            message=message,
            current_url=current_url,
            title=title,
            active_tab_info=active_tab_info,
            core_metrics=core_metrics,
            products=products,
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
