#!/usr/bin/env python3
"""Cross-platform System Tray & Desktop GUI for Log2Topic (Linux / macOS / Windows).

Method A (Hybrid):
- Uses `pystray` + `Pillow` for a native system tray / macOS menu bar icon when installed.
- Falls back automatically to a zero-dependency `tkinter` desktop controller & settings window.
- Sends native desktop notifications via `notify-send` (Linux) or `osascript` (macOS).
"""

import argparse
import locale
import os
import shutil
import subprocess
import sys
import threading

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from atomic_io import load_json_state
from configure_automation import load_settings
from workspace_paths import resolve_workspace_dir as resolve_workspace_root

APP_VERSION = "1.1.2"
DEFAULT_CONFIG_PATH = os.path.join(SCRIPT_DIR, ".runtime", "tray_settings.json")


def detect_is_korean(settings=None):
    lang = "auto"
    if isinstance(settings, dict):
        lang = str(settings.get("ui_language", "auto") or "auto").strip().lower()
    if lang == "ko":
        return True
    if lang == "en":
        return False
    env_lang = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    ).lower()
    if env_lang.startswith("ko"):
        return True
    try:
        loc = locale.getlocale()[0] or ""
        if loc.lower().startswith("ko"):
            return True
    except Exception:
        pass
    return False


def tr(en_text, ko_text, is_korean=False):
    return ko_text if is_korean else en_text


def read_needs_review_count(scripts_root=SCRIPT_DIR):
    metadata_path = os.path.join(scripts_root, "organizer_metadata.json")
    try:
        data = load_json_state(
            metadata_path,
            missing_default={},
            expected_type=dict,
            label="organizer metadata",
        )
        stats = data.get("stats")
        if isinstance(stats, dict) and stats.get("needs_review") is not None:
            return max(0, int(stats["needs_review"]))
    except Exception:
        pass
    return 0


def format_local_update_notification(exit_code, needs_review, is_korean=False):
    if exit_code != 0:
        return tr(
            "Local document update failed. Check run logs.",
            "로컬 문서 갱신에 실패했습니다. 실행 로그를 확인하세요.",
            is_korean,
        )
    if needs_review > 0:
        return tr(
            f"Local documents updated ({needs_review} item(s) need review in dashboard).",
            f"로컬 문서 갱신 완료 (검토 필요 {needs_review}건 — 대시보드에서 확인하세요).",
            is_korean,
        )
    return tr(
        "Local documents updated (0 items need review).",
        "로컬 문서 갱신 완료 (검토 필요 0건).",
        is_korean,
    )


def send_desktop_notification(title, message):
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            subprocess.Popen(
                [
                    "osascript",
                    "-e",
                    "on run argv",
                    "-e",
                    "display notification (item 2 of argv) with title (item 1 of argv)",
                    "-e",
                    "end run",
                    "--",
                    str(title),
                    str(message),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        if shutil.which("notify-send"):
            subprocess.Popen(
                ["notify-send", "-a", "Log2Topic", str(title), str(message)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except Exception:
        pass
    return False


def open_path_in_file_manager(target_path, is_directory=True):
    if is_directory:
        os.makedirs(target_path, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            os.startfile(target_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_path])
        else:
            opener = shutil.which("xdg-open") or shutil.which("gio")
            if opener:
                cmd = [opener, "open", target_path] if opener.endswith("gio") else [opener, target_path]
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def build_configure_args(settings):
    mode = str(settings.get("schedule_mode", "Off") or "Off")
    service = str(settings.get("external_service", "Notion") or "Notion")
    time_str = str(settings.get("schedule_time", "09:00") or "09:00")
    days = settings.get("schedule_days") or ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    raw_lang = str(settings.get("ui_language", "Auto") or "Auto").strip()
    language = "Auto" if raw_lang.lower() == "auto" else raw_lang
    retention = int(settings.get("backup_retention_count", 100) or 100)

    args = [
        "--mode",
        mode,
        "--service",
        service,
        "--time",
        time_str,
        "--days",
        *list(days),
        "--language",
        language,
        "--backup-retention-count",
        str(max(1, min(10000, retention))),
    ]
    if settings.get("start_at_logon"):
        args.append("--enable-startup")
    if settings.get("run_missed"):
        args.append("--run-missed")
    if settings.get("prune_backups"):
        args.append("--prune-backups")
    if not settings.get("auto_check_updates", True):
        args.append("--disable-auto-update-check")
    if "workspace_path" in settings and settings["workspace_path"] is not None:
        args.extend(["--workspace-path", str(settings["workspace_path"])])
    if settings.get("rule_template"):
        args.extend(["--rule-template", str(settings["rule_template"])])
    return args


def run_log2topic_subcommand(subcommand, extra_args=(), on_complete=None):
    log2topic_py = os.path.join(ROOT_DIR, "log2topic.py")
    cmd = [sys.executable, "-u", log2topic_py, subcommand, *extra_args]

    def _worker():
        rc = 1
        try:
            proc = subprocess.run(cmd, cwd=ROOT_DIR)
            rc = proc.returncode
        except Exception:
            rc = 1
        if on_complete is not None:
            on_complete(rc)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def has_graphical_display():
    if sys.platform.startswith("win") or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_tkinter_gui(settings_only=False):
    if not has_graphical_display():
        return False
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception:
        return False

    settings = load_settings(DEFAULT_CONFIG_PATH)
    is_ko = detect_is_korean(settings)
    workspace_dir = resolve_workspace_root(ROOT_DIR)

    root = tk.Tk()
    root.title(
        tr(
            f"Log2Topic v{APP_VERSION} — Controller & Settings",
            f"Log2Topic v{APP_VERSION} — 컨트롤 및 설정",
            is_ko,
        )
    )
    root.geometry("560x680" if not settings_only else "560x500")
    root.resizable(False, False)

    icon_png = os.path.join(ROOT_DIR, "assets", "log2topic.png")
    if os.path.isfile(icon_png):
        try:
            icon_img = tk.PhotoImage(file=icon_png)
            root.iconphoto(True, icon_img)
        except Exception:
            pass

    status_var = tk.StringVar(
        value=tr("Ready.", "준비 완료.", is_ko)
    )

    def notify_status(msg):
        send_desktop_notification("Log2Topic", msg)
        try:
            root.after(0, lambda: status_var.set(msg))
        except Exception:
            pass

    def trigger_local_update():
        status_var.set(tr("Updating local documents...", "로컬 문서 갱신 중...", is_ko))

        def _done(rc):
            needs_review = read_needs_review_count(SCRIPT_DIR)
            msg = format_local_update_notification(rc, needs_review, is_ko)
            notify_status(msg)

        run_log2topic_subcommand("update", ["--nopause"], on_complete=_done)

    def trigger_dashboard():
        status_var.set(
            tr("Opening classification review dashboard...", "분류 검토 대시보드를 여는 중...", is_ko)
        )
        run_log2topic_subcommand("review", ["--nopause"])

    def trigger_sync(subcmd, start_label_en, start_label_ko):
        status_var.set(tr(start_label_en, start_label_ko, is_ko))

        def _done(rc):
            if rc == 0:
                notify_status(tr("Synchronization completed.", "동기화가 완료되었습니다.", is_ko))
            else:
                notify_status(
                    tr(
                        "Synchronization finished with errors. Check reports.",
                        "동기화 중 오류가 발생했습니다. 보고서를 확인하세요.",
                        is_ko,
                    )
                )

        run_log2topic_subcommand(subcmd, ["--nopause"], on_complete=_done)

    main_pad = ttk.Frame(root, padding=14)
    main_pad.pack(fill="both", expand=True)

    if not settings_only:
        actions_group = ttk.LabelFrame(
            main_pad,
            text=tr("Quick Actions", "빠른 실행", is_ko),
            padding=10,
        )
        actions_group.pack(fill="x", pady=(0, 10))

        btn_row1 = ttk.Frame(actions_group)
        btn_row1.pack(fill="x", pady=2)
        ttk.Button(
            btn_row1,
            text=tr("Update Local Documents", "로컬 문서 갱신", is_ko),
            command=trigger_local_update,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            btn_row1,
            text=tr("Open Review Dashboard", "분류 검토 대시보드 열기", is_ko),
            command=trigger_dashboard,
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        btn_row2 = ttk.Frame(actions_group)
        btn_row2.pack(fill="x", pady=2)
        ttk.Button(
            btn_row2,
            text=tr("Notion: Recent Logs", "Notion: 최근 일지", is_ko),
            command=lambda: trigger_sync(
                "sync-daily", "Syncing recent logs...", "최근 일지 동기화 중..."
            ),
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            btn_row2,
            text=tr("Notion: Originals Only", "Notion: 원본 일지만", is_ko),
            command=lambda: trigger_sync(
                "sync-originals", "Syncing all original logs...", "원본 일지 전체 동기화 중..."
            ),
        ).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(
            btn_row2,
            text=tr("Notion: Full Sync", "Notion: 전체 동기화", is_ko),
            command=lambda: trigger_sync(
                "sync", "Running full Notion sync...", "전체 Notion 동기화 중..."
            ),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        folders_row = ttk.Frame(actions_group)
        folders_row.pack(fill="x", pady=(6, 0))
        ttk.Button(
            folders_row,
            text=tr("Open Workspace", "Workspace 열기", is_ko),
            command=lambda: open_path_in_file_manager(workspace_dir, True),
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(
            folders_row,
            text=tr("Open Daily_Logs", "Daily_Logs 열기", is_ko),
            command=lambda: open_path_in_file_manager(
                os.path.join(workspace_dir, "Daily_Logs"), True
            ),
        ).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(
            folders_row,
            text=tr("Open Topic_Reviews", "Topic_Reviews 열기", is_ko),
            command=lambda: open_path_in_file_manager(
                os.path.join(workspace_dir, "Topic_Reviews"), True
            ),
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

    sched_group = ttk.LabelFrame(
        main_pad,
        text=tr("Automation & Sync Settings", "자동 실행 및 동기화 설정", is_ko),
        padding=10,
    )
    sched_group.pack(fill="both", expand=True)

    mode_options = [
        ("Off", tr("Do not use scheduled tasks", "정기 작업 사용 안 함", is_ko)),
        ("Local", tr("Update local documents only", "로컬 문서만 정기 갱신", is_ko)),
        (
            "ExternalOriginals",
            tr(
                "Sync original logs only (Notion)",
                "원본 일지만 외부 서비스 동기화 (Notion)",
                is_ko,
            ),
        ),
        (
            "External",
            tr(
                "Update local + full sync (Notion)",
                "로컬 갱신 후 전체 외부 동기화 (Notion)",
                is_ko,
            ),
        ),
    ]
    mode_var = tk.StringVar(value=str(settings.get("schedule_mode", "Off") or "Off"))
    for code, label in mode_options:
        ttk.Radiobutton(sched_group, text=label, value=code, variable=mode_var).pack(
            anchor="w", pady=1
        )

    time_row = ttk.Frame(sched_group)
    time_row.pack(fill="x", pady=(8, 4))
    ttk.Label(time_row, text=tr("Run time (24h HH:MM):", "실행 시간 (24시간 HH:MM):", is_ko)).pack(
        side="left"
    )
    time_var = tk.StringVar(value=str(settings.get("schedule_time", "09:00") or "09:00"))
    ttk.Entry(time_row, textvariable=time_var, width=10).pack(side="left", padx=8)

    days_row = ttk.Frame(sched_group)
    days_row.pack(fill="x", pady=4)
    day_codes = [
        ("MON", tr("Mon", "월", is_ko)),
        ("TUE", tr("Tue", "화", is_ko)),
        ("WED", tr("Wed", "수", is_ko)),
        ("THU", tr("Thu", "목", is_ko)),
        ("FRI", tr("Fri", "금", is_ko)),
        ("SAT", tr("Sat", "토", is_ko)),
        ("SUN", tr("Sun", "일", is_ko)),
    ]
    saved_days = {str(d).upper() for d in (settings.get("schedule_days") or [])}
    day_vars = {}
    for code, label in day_codes:
        var = tk.BooleanVar(value=(code in saved_days or not saved_days))
        day_vars[code] = var
        ttk.Checkbutton(days_row, text=label, variable=var).pack(side="left", padx=3)

    prune_row = ttk.Frame(sched_group)
    prune_row.pack(fill="x", pady=4)
    prune_var = tk.BooleanVar(value=bool(settings.get("prune_backups", False)))
    ttk.Checkbutton(
        prune_row,
        text=tr("Limit source backup history (batches):", "원본 백업 보관 개수 제한 (배치 수):", is_ko),
        variable=prune_var,
    ).pack(side="left")
    retention_var = tk.StringVar(
        value=str(int(settings.get("backup_retention_count", 100) or 100))
    )
    ttk.Entry(prune_row, textvariable=retention_var, width=8).pack(side="left", padx=6)

    lang_row = ttk.Frame(sched_group)
    lang_row.pack(fill="x", pady=4)
    ttk.Label(lang_row, text=tr("Language:", "표시 언어:", is_ko)).pack(side="left")
    lang_var = tk.StringVar(value=str(settings.get("ui_language", "auto") or "auto"))
    lang_combo = ttk.Combobox(
        lang_row,
        textvariable=lang_var,
        values=["auto", "en", "ko"],
        state="readonly",
        width=12,
    )
    lang_combo.pack(side="left", padx=8)

    ws_row = ttk.Frame(sched_group)
    ws_row.pack(fill="x", pady=4)
    ttk.Label(ws_row, text=tr("Workspace / Vault:", "작업공간 / Vault:", is_ko)).pack(side="left")
    ws_placeholder = tr("Default: Workspace/ (if left empty)", "비워 두면 기본 Workspace/ 폴더 사용", is_ko)
    initial_ws = str(settings.get("workspace_path", "") or "").strip()
    ws_var = tk.StringVar(value=initial_ws or ws_placeholder)
    ws_entry = tk.Entry(
        ws_row,
        textvariable=ws_var,
        width=32,
        fg="#111111" if initial_ws else "#888888",
    )
    ws_entry.pack(side="left", padx=6, fill="x", expand=True)

    def _on_ws_focus_in(_event):
        if ws_var.get() == ws_placeholder:
            ws_var.set("")
            ws_entry.configure(fg="#111111")

    def _on_ws_focus_out(_event):
        if not ws_var.get().strip():
            ws_var.set(ws_placeholder)
            ws_entry.configure(fg="#888888")

    ws_entry.bind("<FocusIn>", _on_ws_focus_in)
    ws_entry.bind("<FocusOut>", _on_ws_focus_out)

    def _get_effective_ws():
        val = ws_var.get().strip()
        return "" if val == ws_placeholder else val

    def browse_vault_folder():
        chosen = filedialog.askdirectory(
            initialdir=_get_effective_ws() or workspace_dir,
            title=tr(
                "Select Obsidian Vault or Workspace Folder",
                "사용할 Obsidian Vault 또는 작업공간 폴더 선택",
                is_ko,
            ),
        )
        if chosen:
            ws_var.set(chosen)
            ws_entry.configure(fg="#111111")

    ttk.Button(
        ws_row,
        text=tr("Browse...", "찾아보기...", is_ko),
        command=browse_vault_folder,
    ).pack(side="left")

    tpl_row = ttk.Frame(sched_group)
    tpl_row.pack(fill="x", pady=4)
    ttk.Label(tpl_row, text=tr("Rule template:", "분류 규칙 템플릿:", is_ko)).pack(side="left")
    tpl_choices = [
        ("", tr("Keep current Classification_Rules.md", "현재 Classification_Rules.md 유지", is_ko)),
        ("simple", tr("Simple 1-2 level (Beginner recommended)", "단순 과제형 1~2단계 (초보자 권장)", is_ko)),
        ("research", tr("Research & experiment notes (3-level)", "연구·실험 노트형 (3단계)", is_ko)),
        ("software", tr("Software & QA engineering (4-level)", "소프트웨어 개발·QA형 (3~4단계)", is_ko)),
    ]
    tpl_label_to_code = {label: code for code, label in tpl_choices}
    tpl_var = tk.StringVar(value=tpl_choices[0][1])
    tpl_combo = ttk.Combobox(
        tpl_row,
        textvariable=tpl_var,
        values=[label for _c, label in tpl_choices],
        state="readonly",
        width=36,
    )
    tpl_combo.pack(side="left", padx=6, fill="x", expand=True)

    def save_current_settings():
        selected_days = [code for code, var in day_vars.items() if var.get()]
        try:
            ret_num = int(retention_var.get().strip())
        except ValueError:
            ret_num = 100
        chosen_tpl = tpl_label_to_code.get(tpl_var.get(), "")
        if chosen_tpl:
            confirm = messagebox.askyesno(
                "Log2Topic",
                tr(
                    "Replace Classification_Rules.md with the selected starter template?\n"
                    "(Previous rules will be backed up under scripts/source_id_backups/rule_templates/.)",
                    "선택한 시작 템플릿으로 Classification_Rules.md를 교체할까요?\n"
                    "(기존 규칙 파일은 scripts/source_id_backups/rule_templates/에 자동 백업됩니다.)",
                    is_ko,
                ),
            )
            if not confirm:
                return
        new_settings = dict(settings)
        new_settings["schedule_mode"] = mode_var.get() if selected_days else "Off"
        new_settings["schedule_time"] = time_var.get().strip()
        new_settings["schedule_days"] = selected_days or ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        new_settings["prune_backups"] = bool(prune_var.get())
        new_settings["backup_retention_count"] = max(1, min(10000, ret_num))
        new_settings["ui_language"] = lang_var.get()
        new_settings["workspace_path"] = _get_effective_ws()
        new_settings["rule_template"] = chosen_tpl

        cfg_args = build_configure_args(new_settings)
        cmd = [
            sys.executable,
            "-u",
            os.path.join(SCRIPT_DIR, "configure_automation.py"),
            *cfg_args,
        ]
        proc = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True)
        if proc.returncode != 0:
            err_msg = (proc.stderr or proc.stdout or "Failed to save settings.").strip()
            messagebox.showerror("Log2Topic", err_msg)
            return
        status_var.set(tr("Settings saved.", "설정이 저장되었습니다.", is_ko))
        if settings_only:
            root.destroy()

    save_row = ttk.Frame(sched_group)
    save_row.pack(fill="x", pady=(10, 0))
    ttk.Button(
        save_row,
        text=tr("Save Settings", "설정 저장", is_ko),
        command=save_current_settings,
    ).pack(side="right")

    status_bar = ttk.Label(
        main_pad,
        textvariable=status_var,
        relief="sunken",
        anchor="w",
        padding=(6, 4),
    )
    status_bar.pack(fill="x", pady=(8, 0))

    root.mainloop()
    return True


def run_system_tray(show_settings=False):
    if show_settings:
        return run_tkinter_gui(settings_only=True)

    if not has_graphical_display():
        return False

    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return run_tkinter_gui(settings_only=False)

    settings = load_settings(DEFAULT_CONFIG_PATH)
    is_ko = detect_is_korean(settings)
    workspace_dir = resolve_workspace_root(ROOT_DIR)

    icon_path = os.path.join(ROOT_DIR, "assets", "log2topic.png")
    if os.path.isfile(icon_path):
        image = Image.open(icon_path)
    else:
        image = Image.new("RGBA", (64, 64), (37, 99, 235, 255))
        draw = ImageDraw.Draw(image)
        draw.rectangle([14, 14, 50, 50], fill=(255, 255, 255, 255))

    def on_local_update(icon, _item):
        send_desktop_notification(
            "Log2Topic",
            tr("Updating local documents.", "로컬 문서 갱신을 시작했습니다.", is_ko),
        )

        def _done(rc):
            needs_review = read_needs_review_count(SCRIPT_DIR)
            msg = format_local_update_notification(rc, needs_review, is_ko)
            send_desktop_notification("Log2Topic", msg)

        run_log2topic_subcommand("update", ["--nopause"], on_complete=_done)

    def on_open_review(_icon, _item):
        send_desktop_notification(
            "Log2Topic",
            tr("Opening classification review.", "분류 검토 대시보드를 여는 중입니다.", is_ko),
        )
        run_log2topic_subcommand("review", ["--nopause"])

    def on_sync(subcmd, msg_en, msg_ko):
        def _handler(_icon, _item):
            send_desktop_notification("Log2Topic", tr(msg_en, msg_ko, is_ko))
            run_log2topic_subcommand(subcmd, ["--nopause"])

        return _handler

    def on_open_settings(_icon, _item):
        threading.Thread(
            target=lambda: subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--settings"],
                cwd=ROOT_DIR,
            ),
            daemon=True,
        ).start()

    def on_exit(icon, _item):
        icon.stop()

    notion_menu = pystray.Menu(
        pystray.MenuItem(
            tr("Sync recent logs", "최근 일지 동기화", is_ko),
            on_sync(
                "sync-daily",
                "Started Notion recent-log sync.",
                "최근 일지 Notion 동기화를 시작했습니다.",
            ),
        ),
        pystray.MenuItem(
            tr("Sync original logs only", "원본 일지만 동기화", is_ko),
            on_sync(
                "sync-originals",
                "Syncing all original logs to Notion.",
                "원본 일지 전체 Notion 동기화를 시작했습니다.",
            ),
        ),
        pystray.MenuItem(
            tr("Full sync (logs + topics + reviews)", "전체 동기화 (일지 + 주제 + 리뷰)", is_ko),
            on_sync(
                "sync",
                "Started full Notion sync.",
                "전체 Notion 동기화를 시작했습니다.",
            ),
        ),
    )

    folders_menu = pystray.Menu(
        pystray.MenuItem(
            tr("Workspace", "작업공간 (Workspace)", is_ko),
            lambda _i, _m: open_path_in_file_manager(workspace_dir, True),
        ),
        pystray.MenuItem(
            tr("Daily logs (Daily_Logs)", "원본 일지 (Daily_Logs)", is_ko),
            lambda _i, _m: open_path_in_file_manager(
                os.path.join(workspace_dir, "Daily_Logs"), True
            ),
        ),
        pystray.MenuItem(
            tr("Subject documents (Subject)", "주제별 문서 (Subject)", is_ko),
            lambda _i, _m: open_path_in_file_manager(
                os.path.join(workspace_dir, "Subject"), True
            ),
        ),
        pystray.MenuItem(
            tr("Topic reviews (Topic_Reviews)", "주제별 리뷰 (Topic_Reviews)", is_ko),
            lambda _i, _m: open_path_in_file_manager(
                os.path.join(workspace_dir, "Topic_Reviews"), True
            ),
        ),
        pystray.MenuItem(
            tr("Classification rules (Classification_Rules.md)", "분류 규칙 (Classification_Rules.md)", is_ko),
            lambda _i, _m: open_path_in_file_manager(
                os.path.join(workspace_dir, "Classification_Rules.md"), False
            ),
        ),
        pystray.MenuItem(
            tr("Run reports (scripts/reports)", "실행 보고서 (scripts/reports)", is_ko),
            lambda _i, _m: open_path_in_file_manager(
                os.path.join(SCRIPT_DIR, "reports"), True
            ),
        ),
    )

    menu = pystray.Menu(
        pystray.MenuItem(f"Log2Topic v{APP_VERSION}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            tr("Update local documents", "로컬 문서 갱신", is_ko),
            on_local_update,
            default=True,
        ),
        pystray.MenuItem(
            tr("Open classification review", "분류 검토 대시보드 열기", is_ko),
            on_open_review,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(tr("Notion", "Notion", is_ko), notion_menu),
        pystray.MenuItem(
            tr("Open workspace folders", "작업공간 폴더 열기", is_ko),
            folders_menu,
        ),
        pystray.MenuItem(
            tr("Automation and sync settings...", "자동 실행 및 동기화 설정...", is_ko),
            on_open_settings,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(tr("Exit", "종료", is_ko), on_exit),
    )

    icon = pystray.Icon("Log2Topic", image, f"Log2Topic v{APP_VERSION}", menu)
    icon.run()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Launch the Log2Topic system tray icon or desktop controller GUI."
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Open the desktop controller & settings window directly (tkinter).",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="Open the automation & sync settings dialog directly.",
    )
    args = parser.parse_args(argv)

    if args.settings:
        ok = run_tkinter_gui(settings_only=True)
    elif args.gui:
        ok = run_tkinter_gui(settings_only=False)
    else:
        ok = run_system_tray(show_settings=False)

    if not ok:
        print(
            "Graphical display or tkinter is not available in this environment. "
            "Use './Log2Topic.sh' or 'python3 log2topic.py' for the terminal interface.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
