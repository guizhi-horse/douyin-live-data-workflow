from __future__ import annotations

import argparse
import json
import os
import shutil
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def target_note_path(config: dict[str, Any], summary: dict[str, Any]) -> Path | None:
    note_stage = ((summary.get("stages") or {}).get("note") or {})
    note_path = note_stage.get("note_path")
    if note_path:
        return Path(str(note_path))

    target_date = str(config.get("target_date") or "").strip()
    output_dir = str(config.get("obsidian_output_path") or "").strip()
    if not target_date or not output_dir:
        return None

    year, month, day = target_date.split("-")
    note_name = f"{int(year)}.{int(month)}.{int(day)}直播数据.md"
    return Path(output_dir) / note_name


def backup_run(config_path: Path, summary_path: Path, backup_root: Path) -> dict[str, Any]:
    config = load_json(config_path)
    summary = load_json(summary_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []

    def copy_if_exists(source: Path, relative_name: str | None = None) -> None:
        if not source.exists():
            return
        destination = backup_dir / (relative_name or source.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_files.append(str(destination))

    copy_if_exists(config_path)
    copy_if_exists(summary_path)

    output_dir = ROOT / "output"
    for result_name in [
        "douyin_list_stage_result.json",
        "douyin_detail_stage_result.json",
        "douyin_dashboard_stage_result.json",
        "douyin_professional_stage_result.json",
        "douyin_professional_stage_result.raw.json",
        "douyin_qianchuan_stage_result.json",
        "douyin_note_stage_result.json",
        "douyin_full_workflow_result.json",
    ]:
        copy_if_exists(output_dir / result_name, f"output/{result_name}")

    note_path = target_note_path(config, summary)
    if note_path:
        copy_if_exists(note_path, f"note/{note_path.name}")

    manifest = {
        "status": "ready",
        "message": "Created workflow backup bundle.",
        "backup_dir": str(backup_dir),
        "copied_files": copied_files,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_json(backup_dir / "manifest.json", manifest)
    return manifest


def build_failure_message(config: dict[str, Any], summary: dict[str, Any]) -> tuple[str, str]:
    target_date = str(config.get("target_date") or "unknown-date")
    final_status = str(summary.get("final_status") or "failed")
    error_text = str(summary.get("error") or "No explicit error message was recorded.")
    stages = summary.get("stages") or {}

    lines = [
        "抖音直播数据采集流程执行失败",
        "",
        f"目标日期：{target_date}",
        f"最终状态：{final_status}",
        f"错误信息：{error_text}",
        "",
        "阶段状态：",
    ]
    for stage_name, stage_payload in stages.items():
        if isinstance(stage_payload, dict):
            lines.append(f"- {stage_name}: {stage_payload.get('status')}")
    lines.extend(
        [
            "",
            f"总汇文件：{ROOT / 'output' / 'douyin_full_workflow_result.json'}",
            f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        ]
    )
    return f"[Douyin Workflow Failed] {target_date}", "\n".join(lines)


def load_smtp_settings(config: dict[str, Any]) -> dict[str, Any]:
    config_smtp = config.get("smtp") if isinstance(config.get("smtp"), dict) else {}

    def pick(name: str, default: str = "") -> str:
        env_name = f"DOUYIN_SMTP_{name.upper()}"
        env_value = os.getenv(env_name, "").strip()
        if env_value:
            return env_value
        return str(config_smtp.get(name, default) or default).strip()

    def pick_bool(name: str, default: bool = False) -> bool:
        env_name = f"DOUYIN_SMTP_{name.upper()}"
        env_value = os.getenv(env_name, "").strip().lower()
        if env_value:
            return env_value in {"1", "true", "yes", "on"}
        value = config_smtp.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    port_text = pick("port", "587")
    try:
        port = int(port_text)
    except ValueError:
        port = 587

    return {
        "enabled": pick_bool("enabled", False),
        "host": pick("host"),
        "port": port,
        "username": pick("username"),
        "password": pick("password"),
        "from": pick("from"),
        "use_ssl": pick_bool("ssl", False),
    }


def draft_failure_email(
    recipient: str,
    subject: str,
    body: str,
    drafts_root: Path,
    smtp_settings: dict[str, Any],
    error_message: str = "",
) -> dict[str, Any]:
    drafts_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    draft_path = drafts_root / f"failure-email-{timestamp}.txt"
    diagnostic = f"\n发送失败原因：{error_message}\n" if error_message else ""

    draft_path.write_text(
        (
            f"To: {recipient or '未填写'}\n"
            f"Subject: {subject}\n"
            f"SMTP Enabled: {smtp_settings.get('enabled')}\n"
            f"SMTP Host: {smtp_settings.get('host') or '未填写'}\n"
            f"SMTP From: {smtp_settings.get('from') or '未填写'}\n"
            f"SMTP Username: {smtp_settings.get('username') or '未填写'}\n"
            f"SMTP SSL: {smtp_settings.get('use_ssl')}\n"
            f"{diagnostic}\n"
            f"{body}\n"
        ),
        encoding="utf-8-sig",
    )
    return {
        "status": "drafted",
        "message": "SMTP 未发送成功，已生成邮件草稿文件。",
        "recipient": recipient,
        "subject": subject,
        "draft_path": str(draft_path),
        "smtp_enabled": smtp_settings.get("enabled"),
        "required_fields": ["host", "port", "username", "password", "from"],
        "error": error_message or None,
    }


def send_failure_email(config_path: Path, summary_path: Path, drafts_root: Path) -> dict[str, Any]:
    config = load_json(config_path)
    summary = load_json(summary_path)
    recipient = str(config.get("failure_email") or "").strip()
    subject, body = build_failure_message(config, summary)

    smtp_settings = load_smtp_settings(config)
    smtp_host = str(smtp_settings.get("host") or "").strip()
    smtp_port = int(smtp_settings.get("port") or 587)
    smtp_username = str(smtp_settings.get("username") or "").strip()
    smtp_password = str(smtp_settings.get("password") or "").strip()
    smtp_from = str(smtp_settings.get("from") or "").strip() or smtp_username
    use_ssl = bool(smtp_settings.get("use_ssl"))
    enabled = bool(smtp_settings.get("enabled"))

    if recipient and enabled and smtp_host and smtp_username and smtp_password and smtp_from:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = smtp_from
        message["To"] = recipient
        message.set_content(body)

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                    server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)

            return {
                "status": "sent",
                "message": "Failure email was sent successfully.",
                "recipient": recipient,
                "subject": subject,
            }
        except Exception as exc:
            return draft_failure_email(
                recipient=recipient,
                subject=subject,
                body=body,
                drafts_root=drafts_root,
                smtp_settings=smtp_settings,
                error_message=str(exc),
            )

    return draft_failure_email(
        recipient=recipient,
        subject=subject,
        body=body,
        drafts_root=drafts_root,
        smtp_settings=smtp_settings,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup workflow results and send failure notifications.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--config", required=True)
    backup_parser.add_argument("--summary", required=True)
    backup_parser.add_argument("--backup-root", default=str(ROOT / "output" / "archives"))

    notify_parser = subparsers.add_parser("notify-failure")
    notify_parser.add_argument("--config", required=True)
    notify_parser.add_argument("--summary", required=True)
    notify_parser.add_argument("--drafts-root", default=str(ROOT / "output" / "mail-drafts"))

    args = parser.parse_args()

    if args.command == "backup":
        payload = backup_run(
            config_path=Path(args.config).resolve(),
            summary_path=Path(args.summary).resolve(),
            backup_root=Path(args.backup_root).resolve(),
        )
    else:
        payload = send_failure_email(
            config_path=Path(args.config).resolve(),
            summary_path=Path(args.summary).resolve(),
            drafts_root=Path(args.drafts_root).resolve(),
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
