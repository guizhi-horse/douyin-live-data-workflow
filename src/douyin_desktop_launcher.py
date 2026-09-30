from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from datetime import date, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "douyin_workflow_config.json"
DEFAULT_CONFIG_PATH = ROOT / "config" / "douyin_workflow_config.example.json"
FULL_WORKFLOW_SCRIPT = ROOT / "run_douyin_full_workflow.ps1"
LAUNCH_CHROME_SCRIPT = ROOT / "launch_douyin_chrome.ps1"


def normalize_date_input(raw: str) -> str:
    match = re.fullmatch(r"\s*(\d{4})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*", raw)
    if not match:
        raise ValueError("日期格式不正确，请使用 YYYY-MM-DD，例如 2026-07-09。")
    try:
        return date(*(int(part) for part in match.groups())).isoformat()
    except ValueError as exc:
        raise ValueError("日期无效，请检查年、月、日是否正确。") from exc


def load_json_file(path: Path, default: dict | list) -> dict | list:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def load_default_config() -> dict:
    source = CONFIG_PATH if CONFIG_PATH.exists() else DEFAULT_CONFIG_PATH
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    data["mode"] = data.get("mode") or "manual"
    data["date_mode"] = data.get("date_mode") or "single_date"
    data["target_date"] = data.get("target_date") or date.today().isoformat()
    try:
        data["target_date"] = normalize_date_input(str(data["target_date"]))
    except ValueError:
        pass
    data["scheduled_time"] = data.get("scheduled_time") or "22:30"
    return data


class DesktopLauncher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("抖音直播数据采编启动器")
        self.root.geometry("1080x780")
        self.root.minsize(920, 640)
        self.root.configure(bg="#f4ede3")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None

        self.mode_var = tk.StringVar()
        self.date_mode_var = tk.StringVar()
        self.target_date_var = tk.StringVar()
        self.scheduled_time_var = tk.StringVar()
        self.failure_email_var = tk.StringVar()
        self.retry_delay_var = tk.StringVar()
        self.launch_chrome_var = tk.BooleanVar(value=False)

        self.smtp_enabled_var = tk.BooleanVar(value=False)
        self.smtp_host_var = tk.StringVar()
        self.smtp_port_var = tk.StringVar()
        self.smtp_username_var = tk.StringVar()
        self.smtp_password_var = tk.StringVar()
        self.smtp_from_var = tk.StringVar()
        self.smtp_ssl_var = tk.BooleanVar(value=True)

        self.obsidian_path_var = tk.StringVar()
        self.prompt_file_var = tk.StringVar()
        self.chrome_start_url_var = tk.StringVar()
        self.luopan_entry_url_var = tk.StringVar()

        self.save_status_var = tk.StringVar(value="还没有保存本次设置。")

        self._load_config()
        self._build_ui()
        self._refresh_date_mode()
        self.root.after(200, self._drain_log_queue)

    def _load_config(self) -> None:
        config = load_default_config()
        self.mode_var.set(str(config.get("mode") or "manual"))
        self.date_mode_var.set(str(config.get("date_mode") or "single_date"))
        self.target_date_var.set(str(config.get("target_date") or date.today().isoformat()))
        self.scheduled_time_var.set(str(config.get("scheduled_time") or "22:30"))
        self.failure_email_var.set(str(config.get("failure_email") or ""))
        self.retry_delay_var.set(str(config.get("retry_delay_hours") or 1))

        smtp = config.get("smtp") if isinstance(config.get("smtp"), dict) else {}
        self.smtp_enabled_var.set(bool(smtp.get("enabled", False)))
        self.smtp_host_var.set(str(smtp.get("host") or ""))
        self.smtp_port_var.set(str(smtp.get("port") or 587))
        self.smtp_username_var.set(str(smtp.get("username") or ""))
        self.smtp_password_var.set("")
        self.smtp_from_var.set(str(smtp.get("from") or ""))
        self.smtp_ssl_var.set(bool(smtp.get("ssl", True)))

        self.obsidian_path_var.set(str(config.get("obsidian_output_path") or ""))
        self.prompt_file_var.set(str(config.get("prompt_file") or ""))
        self.chrome_start_url_var.set(str(config.get("chrome_start_url") or ""))
        self.luopan_entry_url_var.set(str(config.get("luopan_entry_url") or ""))

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Card.TFrame", background="#fff9f1")
        style.configure("Root.TFrame", background="#f4ede3")
        style.configure("TLabel", background="#fff9f1", foreground="#2f2419")
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Hint.TLabel", foreground="#6d5a45")
        style.configure("TButton", font=("Microsoft YaHei UI", 10))
        style.configure("TRadiobutton", background="#fff9f1")
        style.configure("TCheckbutton", background="#fff9f1")
        style.configure("TLabelframe", background="#fff9f1")
        style.configure("TLabelframe.Label", background="#fff9f1", foreground="#2f2419")

        outer = ttk.Frame(self.root, style="Root.TFrame")
        outer.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(outer, bg="#f4ede3", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.wrapper = ttk.Frame(self.canvas, style="Root.TFrame", padding=18)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.wrapper, anchor="nw")
        self.wrapper.bind("<Configure>", self._on_wrapper_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        hero = ttk.Frame(self.wrapper, style="Card.TFrame", padding=18)
        hero.pack(fill="x")
        ttk.Label(hero, text="抖音直播数据采编桌面启动器", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            text="适合日常切换单日日期。你可以在这里保存设置，并直接启动完整流程。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        body = ttk.Frame(self.wrapper, style="Root.TFrame")
        body.pack(fill="both", expand=True, pady=(16, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Card.TFrame", padding=18)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(body, style="Card.TFrame", padding=18)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_left_panel(left)
        self._build_right_panel(right)
        self._bind_scroll_targets(self.wrapper)

    def _bind_scroll_targets(self, widget: tk.Misc) -> None:
        non_scroll_types = (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox)
        if not isinstance(widget, non_scroll_types):
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_scroll_targets(child)

    def _on_mousewheel(self, event: tk.Event) -> str:
        step = 3
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-step, "units")
            return "break"
        if getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(step, "units")
            return "break"

        delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
        if delta:
            self.canvas.yview_scroll(delta * step, "units")
            return "break"
        return ""

    def _on_wrapper_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(parent, text="执行模式").grid(row=row, column=0, sticky="w")
        mode_box = ttk.Frame(parent, style="Card.TFrame")
        mode_box.grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(mode_box, text="手动执行", variable=self.mode_var, value="manual").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_box, text="定时执行", variable=self.mode_var, value="scheduled").pack(side="left")

        row += 1
        ttk.Label(parent, text="日期模式").grid(row=row, column=0, sticky="w", pady=(16, 0))
        date_box = ttk.Frame(parent, style="Card.TFrame")
        date_box.grid(row=row, column=1, sticky="w", pady=(16, 0))
        ttk.Radiobutton(
            date_box,
            text="指定单日（推荐）",
            variable=self.date_mode_var,
            value="single_date",
            command=self._refresh_date_mode,
        ).pack(anchor="w")
        ttk.Radiobutton(
            date_box,
            text="当天",
            variable=self.date_mode_var,
            value="today",
            command=self._refresh_date_mode,
        ).pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(
            date_box,
            text="日期范围（备用）",
            variable=self.date_mode_var,
            value="date_range",
            command=self._refresh_date_mode,
        ).pack(anchor="w", pady=(6, 0))

        row += 1
        ttk.Label(parent, text="目标日期").grid(row=row, column=0, sticky="w", pady=(16, 0))
        target_row = ttk.Frame(parent, style="Card.TFrame")
        target_row.grid(row=row, column=1, sticky="ew", pady=(16, 0))
        target_row.columnconfigure(0, weight=1)
        self.target_date_entry = ttk.Entry(target_row, textvariable=self.target_date_var)
        self.target_date_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(target_row, text="今天", command=self._set_today).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(target_row, text="昨天", command=self._set_yesterday).grid(row=0, column=2, padx=(8, 0))
        ttk.Label(parent, text="格式：YYYY-MM-DD", style="Hint.TLabel").grid(row=row + 1, column=1, sticky="w", pady=(4, 0))

        row += 2
        ttk.Label(parent, text="定时执行时间").grid(row=row, column=0, sticky="w", pady=(16, 0))
        self.scheduled_entry = ttk.Entry(parent, textvariable=self.scheduled_time_var)
        self.scheduled_entry.grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Label(parent, text="未结束重试间隔").grid(row=row, column=0, sticky="w", pady=(16, 0))
        retry_combo = ttk.Combobox(parent, textvariable=self.retry_delay_var, state="readonly", values=["1"])
        retry_combo.grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Label(parent, text="失败通知邮箱").grid(row=row, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(parent, textvariable=self.failure_email_var).grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        smtp_box = ttk.LabelFrame(parent, text="失败邮件发送", padding=12)
        smtp_box.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        smtp_box.columnconfigure(1, weight=1)
        ttk.Checkbutton(smtp_box, text="启用 SMTP 自动发送", variable=self.smtp_enabled_var).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(smtp_box, text="SMTP Host").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(smtp_box, textvariable=self.smtp_host_var).grid(row=1, column=1, sticky="ew", pady=(12, 0))
        ttk.Label(smtp_box, text="SMTP Port").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(smtp_box, textvariable=self.smtp_port_var).grid(row=2, column=1, sticky="ew", pady=(12, 0))
        ttk.Label(smtp_box, text="SMTP Username").grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(smtp_box, textvariable=self.smtp_username_var).grid(row=3, column=1, sticky="ew", pady=(12, 0))
        ttk.Label(smtp_box, text="SMTP 授权码").grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(smtp_box, textvariable=self.smtp_password_var, show="*").grid(
            row=4, column=1, sticky="ew", pady=(12, 0)
        )
        ttk.Label(smtp_box, text="SMTP From").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(smtp_box, textvariable=self.smtp_from_var).grid(row=5, column=1, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(smtp_box, text="使用 SSL", variable=self.smtp_ssl_var).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )
        ttk.Label(
            smtp_box,
            text="授权码只在本次运行时传入子进程，不会写入配置文件或历史记录。",
            style="Hint.TLabel",
            wraplength=420,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        row += 1
        ttk.Label(parent, text="笔记输出目录").grid(row=row, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(parent, textvariable=self.obsidian_path_var).grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Label(parent, text="提示词文件").grid(row=row, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(parent, textvariable=self.prompt_file_var).grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Label(parent, text="Chrome 启动页").grid(row=row, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(parent, textvariable=self.chrome_start_url_var).grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Label(parent, text="罗盘入口 URL").grid(row=row, column=0, sticky="w", pady=(16, 0))
        ttk.Entry(parent, textvariable=self.luopan_entry_url_var).grid(row=row, column=1, sticky="ew", pady=(16, 0))

        row += 1
        ttk.Checkbutton(
            parent,
            text="运行前顺手打开专用 Chrome",
            variable=self.launch_chrome_var,
            style="TCheckbutton",
        ).grid(row=row, column=1, sticky="w", pady=(18, 0))

        row += 1
        action_row = ttk.Frame(parent, style="Card.TFrame")
        action_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(22, 0))
        ttk.Button(action_row, text="保存配置", command=self._save_config).pack(side="left")
        ttk.Button(action_row, text="开始运行", command=self._run_full_workflow).pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="只打开 Chrome", command=self._launch_chrome).pack(side="left", padx=(10, 0))

        row += 1
        ttk.Label(parent, textvariable=self.save_status_var, style="Hint.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="当前准备", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="默认已切到单日模式。建议每次只改目标日期，然后直接点开始运行。",
            style="Hint.TLabel",
            justify="left",
            wraplength=320,
        ).pack(anchor="w", pady=(8, 16))

        hint_box = ttk.LabelFrame(parent, text="中文提示说明", padding=12)
        hint_box.pack(fill="x", pady=(0, 14))
        ttk.Label(
            hint_box,
            text=(
                "如果流程中断：\n"
                "1. 先看下方运行日志最后几行。\n"
                "2. 如果邮件没发出去，系统会自动在 output/mail-drafts 里留一份草稿。\n"
                "3. 现在页面上大部分非输入区域都可以直接滚动，滚动幅度也更大。"
            ),
            justify="left",
            wraplength=320,
        ).pack(anchor="w")

        ttk.Label(parent, text="运行日志", style="Header.TLabel").pack(anchor="w")
        log_frame = ttk.Frame(parent, style="Card.TFrame")
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=24, wrap="word", bg="#241a12", fg="#f8f3ea")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "这里会显示保存配置、打开 Chrome 和运行流程的结果。\n")
        self.log_text.configure(state="disabled")

    def _refresh_date_mode(self) -> None:
        mode = self.date_mode_var.get()
        if mode == "today":
            self.target_date_entry.configure(state="disabled")
        else:
            self.target_date_entry.configure(state="normal")

    def _set_today(self) -> None:
        self.target_date_var.set(date.today().isoformat())

    def _set_yesterday(self) -> None:
        self.target_date_var.set((date.today() - timedelta(days=1)).isoformat())

    def _build_payload(self) -> dict:
        date_mode = self.date_mode_var.get() or "single_date"
        raw_target_date = self.target_date_var.get().strip() or date.today().isoformat()
        target_date = normalize_date_input(raw_target_date)
        try:
            smtp_port = int((self.smtp_port_var.get() or "587").strip())
        except ValueError as exc:
            raise ValueError("SMTP 端口需要是数字。") from exc
        payload = load_default_config()
        payload["mode"] = self.mode_var.get() or "manual"
        payload["date_mode"] = date_mode
        payload["target_date"] = target_date if date_mode == "single_date" else None
        payload["start_date"] = None
        payload["end_date"] = None
        payload["scheduled_time"] = self.scheduled_time_var.get().strip() if payload["mode"] == "scheduled" else None
        payload["retry_delay_hours"] = int(self.retry_delay_var.get() or "1")
        payload["failure_email"] = self.failure_email_var.get().strip()
        payload["smtp"] = {
            "enabled": bool(self.smtp_enabled_var.get()),
            "host": self.smtp_host_var.get().strip(),
            "port": smtp_port,
            "username": self.smtp_username_var.get().strip(),
            "password": "",
            "from": self.smtp_from_var.get().strip(),
            "ssl": bool(self.smtp_ssl_var.get()),
        }
        payload["obsidian_output_path"] = self.obsidian_path_var.get().strip()
        payload["prompt_file"] = self.prompt_file_var.get().strip()
        payload["chrome_start_url"] = self.chrome_start_url_var.get().strip()
        payload["luopan_entry_url"] = self.luopan_entry_url_var.get().strip()
        return payload

    def _save_config(self) -> bool:
        try:
            payload = self._build_payload()
        except ValueError as exc:
            messagebox.showerror("保存失败", str(exc))
            return False

        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.save_status_var.set(f"已保存：{payload['date_mode']} / {payload.get('target_date') or '当天'}")
        self._append_log("配置已保存。\n")
        return True

    def _build_runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        password = self.smtp_password_var.get().strip()
        if password:
            env["DOUYIN_SMTP_PASSWORD"] = password
        else:
            env.pop("DOUYIN_SMTP_PASSWORD", None)
        return env

    def _launch_chrome(self) -> None:
        if not self._save_config():
            return
        self._start_process(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(LAUNCH_CHROME_SCRIPT)],
            "正在打开专用 Chrome...\n",
        )

    def _run_full_workflow(self) -> None:
        if not self._save_config():
            return
        command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(FULL_WORKFLOW_SCRIPT)]
        if self.launch_chrome_var.get():
            command.append("-LaunchChrome")
        self._start_process(command, "正在启动完整流程...\n")

    def _start_process(self, command: list[str], header: str) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("流程正在运行", "当前已经有一个流程在运行，请等它结束后再启动新的。")
            return
        self._append_log(header)
        runtime_env = self._build_runtime_env()

        def runner() -> None:
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=str(ROOT),
                    env=runtime_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                assert self.process.stdout is not None
                for line in self.process.stdout:
                    self.log_queue.put(line)
                code = self.process.wait()
                self.log_queue.put(f"\n流程已结束，退出码：{code}\n")
            except Exception as exc:
                self.log_queue.put(f"\n启动失败：{exc}\n")

        threading.Thread(target=runner, daemon=True).start()

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain_log_queue(self) -> None:
        while not self.log_queue.empty():
            self._append_log(self.log_queue.get_nowait())
        self.root.after(200, self._drain_log_queue)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    DesktopLauncher().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
