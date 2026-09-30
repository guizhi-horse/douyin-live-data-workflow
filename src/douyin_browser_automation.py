from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options


DEFAULT_DEBUG_PORT = 9222
DEFAULT_PROFILE_DIR = ROOT / ".chrome-automation"


def resolve_config_path(raw_path: str | None) -> str | None:
    """Resolve package-relative paths independently of the launch directory."""
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((ROOT / path).resolve())


@dataclass
class BrowserConfig:
    chrome_path: str
    chromedriver_path: str | None
    debug_port: int
    profile_dir: str
    start_url: str
    headless: bool
    page_load_timeout_seconds: int
    implicit_wait_seconds: int


@dataclass
class BrowserSessionResult:
    connected: bool
    chrome_path: str
    debug_port: int
    profile_dir: str
    current_url: str
    title: str


def find_chrome_executable() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find chrome.exe in the standard install paths.")


def build_browser_config(payload: dict[str, Any]) -> BrowserConfig:
    chrome_path = payload.get("chrome_path") or str(find_chrome_executable())
    profile_dir = resolve_config_path(payload.get("chrome_profile_dir")) or str(DEFAULT_PROFILE_DIR)
    return BrowserConfig(
        chrome_path=chrome_path,
        chromedriver_path=resolve_config_path(payload.get("chromedriver_path")),
        debug_port=int(payload.get("chrome_debug_port", DEFAULT_DEBUG_PORT)),
        profile_dir=profile_dir,
        start_url=payload.get("chrome_start_url", "about:blank"),
        headless=bool(payload.get("headless", False)),
        page_load_timeout_seconds=int(payload.get("page_load_timeout_seconds", 30)),
        implicit_wait_seconds=int(payload.get("implicit_wait_seconds", 2)),
    )


def load_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def launch_debug_chrome(config: BrowserConfig) -> subprocess.Popen[str]:
    Path(config.profile_dir).mkdir(parents=True, exist_ok=True)
    args = [
        config.chrome_path,
        f"--remote-debugging-port={config.debug_port}",
        f"--user-data-dir={config.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        config.start_url,
    ]
    if config.headless:
        args.extend(["--headless=new", "--disable-gpu"])
    return subprocess.Popen(args)


def connect_to_debug_chrome(config: BrowserConfig) -> webdriver.Chrome:
    options = Options()
    options.debugger_address = f"127.0.0.1:{config.debug_port}"
    if config.chromedriver_path:
        service = Service(executable_path=config.chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(config.page_load_timeout_seconds)
    driver.implicitly_wait(config.implicit_wait_seconds)
    try:
        driver.set_script_timeout(max(config.page_load_timeout_seconds, 60))
    except Exception:
        pass
    return driver


def open_or_attach(config: BrowserConfig, launch_wait_seconds: float = 3.0) -> webdriver.Chrome:
    try:
        return connect_to_debug_chrome(config)
    except Exception:
        launch_debug_chrome(config)
        time.sleep(launch_wait_seconds)
        return connect_to_debug_chrome(config)


def smoke_test(config: BrowserConfig) -> BrowserSessionResult:
    driver = open_or_attach(config)
    try:
        driver.get(config.start_url)
        return BrowserSessionResult(
            connected=True,
            chrome_path=config.chrome_path,
            debug_port=config.debug_port,
            profile_dir=config.profile_dir,
            current_url=driver.current_url,
            title=driver.title,
        )
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Chrome automation bridge.")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config" / "douyin_workflow_config.json"),
        help="Path to the launcher JSON config.",
    )
    args = parser.parse_args()

    payload = load_payload(Path(args.config).resolve())
    browser_config = build_browser_config(payload)
    result = smoke_test(browser_config)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
