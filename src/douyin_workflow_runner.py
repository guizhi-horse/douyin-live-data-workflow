from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_CONFIG_PATH = Path("config/douyin_workflow_config.json")
DEFAULT_PLAN_PATH = Path("output/douyin_workflow_plan.json")


@dataclass
class LaunchConfig:
    mode: str
    date_mode: str
    timezone: str
    target_date: str | None
    start_date: str | None
    end_date: str | None
    scheduled_time: str | None
    retry_delay_hours: int
    failure_action: str
    failure_email: str
    smtp: dict[str, Any] | None
    obsidian_output_path: str
    prompt_file: str
    rules: dict[str, Any]
    chrome_debug_port: int | None = None
    chrome_profile_dir: str | None = None
    chrome_start_url: str | None = None
    chrome_path: str | None = None
    chromedriver_path: str | None = None
    luopan_entry_url: str | None = None
    luopan_bookmark_label: str | None = None
    resume_from_current_page: bool = False
    navigation_steps: list[dict[str, Any]] | None = None
    headless: bool = False
    page_load_timeout_seconds: int = 30
    implicit_wait_seconds: int = 2


@dataclass
class DailyRun:
    target_date: str
    note_name: str
    note_path: str
    run_label: str
    collection_basis: str


@dataclass
class RunPlan:
    generated_at: str
    mode: str
    timezone: str
    date_mode: str
    scheduled_time: str | None
    retry_delay_hours: int
    failure_action: str
    failure_email: str
    prompt_file: str
    obsidian_output_path: str
    total_days: int
    daily_runs: list[DailyRun]
    execution_notes: list[str]


def load_launch_config(config_path: Path) -> LaunchConfig:
    with config_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return LaunchConfig(**payload)


def validate_config(config: LaunchConfig) -> None:
    if config.mode not in {"manual", "scheduled"}:
        raise ValueError("mode must be 'manual' or 'scheduled'")
    if config.date_mode not in {"today", "single_date", "date_range"}:
        raise ValueError("date_mode must be 'today', 'single_date', or 'date_range'")
    if config.mode == "scheduled" and not config.scheduled_time:
        raise ValueError("scheduled_time is required when mode is 'scheduled'")
    if config.date_mode == "single_date" and not config.target_date:
        raise ValueError("target_date is required when date_mode is 'single_date'")
    if config.date_mode == "date_range" and (not config.start_date or not config.end_date):
        raise ValueError("start_date and end_date are required when date_mode is 'date_range'")


def parse_date(raw: str) -> date:
    match = re.fullmatch(r"\s*(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*", raw)
    if not match:
        raise ValueError(f"Invalid date {raw!r}; expected YYYY-MM-DD")
    return date(*(int(part) for part in match.groups()))


def format_note_name(target: date) -> str:
    return f"{target.year}.{target.month}.{target.day}直播数据"


def list_target_dates(config: LaunchConfig) -> list[date]:
    zone = ZoneInfo(config.timezone)
    today = datetime.now(zone).date()

    if config.date_mode == "today":
        return [today]
    if config.date_mode == "single_date":
        return [parse_date(config.target_date or "")]

    start = parse_date(config.start_date or "")
    end = parse_date(config.end_date or "")
    if start > end:
        raise ValueError("start_date must be earlier than or equal to end_date")

    dates: list[date] = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def build_daily_runs(config: LaunchConfig, dates: list[date]) -> list[DailyRun]:
    output_root = Path(config.obsidian_output_path)
    daily_runs: list[DailyRun] = []

    for index, target in enumerate(dates, start=1):
        note_name = format_note_name(target)
        note_path = output_root / f"{note_name}.md"
        daily_runs.append(
            DailyRun(
                target_date=target.isoformat(),
                note_name=note_name,
                note_path=str(note_path),
                run_label=f"day-{index}",
                collection_basis="按开播时间判断归属日期",
            )
        )

    return daily_runs


def build_execution_notes(config: LaunchConfig, dates: list[date]) -> list[str]:
    notes = [
        "同一天多场直播写入同一篇笔记。",
        "日期范围模式下一天生成一篇笔记。",
        "直播未结束时延后指定小时数重试。",
        "失败时停止执行并记录页面原文。",
    ]

    if config.mode == "scheduled":
        notes.append(f"定时执行时间：{config.scheduled_time} ({config.timezone})。")
    if len(dates) > 1:
        notes.append("多天任务会按日期从早到晚依次处理。")

    return notes


def build_plan(config: LaunchConfig) -> RunPlan:
    validate_config(config)
    dates = list_target_dates(config)
    daily_runs = build_daily_runs(config, dates)

    return RunPlan(
        generated_at=datetime.now(ZoneInfo(config.timezone)).isoformat(),
        mode=config.mode,
        timezone=config.timezone,
        date_mode=config.date_mode,
        scheduled_time=config.scheduled_time,
        retry_delay_hours=int(config.retry_delay_hours),
        failure_action=config.failure_action,
        failure_email=config.failure_email,
        prompt_file=config.prompt_file,
        obsidian_output_path=config.obsidian_output_path,
        total_days=len(daily_runs),
        daily_runs=daily_runs,
        execution_notes=build_execution_notes(config, dates),
    )


def write_plan(plan: RunPlan, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(plan)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def render_console_summary(plan: RunPlan) -> str:
    lines = [
        "直播数据工作流执行计划",
        f"- 模式: {plan.mode}",
        f"- 日期模式: {plan.date_mode}",
        f"- 时区: {plan.timezone}",
        f"- 计划天数: {plan.total_days}",
    ]
    if plan.scheduled_time:
        lines.append(f"- 定时执行时间: {plan.scheduled_time}")
    lines.append(f"- 失败通知邮箱: {plan.failure_email}")
    lines.append("- 任务清单:")
    for item in plan.daily_runs:
        lines.append(f"  - {item.target_date} -> {item.note_path}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a run plan from the Douyin workflow launcher config.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the launcher JSON config.",
    )
    parser.add_argument(
        "--plan-output",
        default=str(DEFAULT_PLAN_PATH),
        help="Path to write the expanded run plan JSON.",
    )
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    plan_path = Path(args.plan_output).resolve()

    config = load_launch_config(config_path)
    plan = build_plan(config)
    write_plan(plan, plan_path)
    print(render_console_summary(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
