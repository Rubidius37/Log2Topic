"""Cross-platform/Linux automation configuration for Log2Topic."""

import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys

from atomic_io import atomic_write_json, load_json_state
from workspace_paths import ensure_workspace_initialized, resolve_workspace_dir


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
RUNTIME_DIR = os.path.join(SCRIPT_DIR, ".runtime")
CONFIG_PATH = os.path.join(RUNTIME_DIR, "tray_settings.json")
VALID_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
SYSTEMD_DAY_ABBR = {
    "Monday": "Mon",
    "Tuesday": "Tue",
    "Wednesday": "Wed",
    "Thursday": "Thu",
    "Friday": "Fri",
    "Saturday": "Sat",
    "Sunday": "Sun",
}
CRON_DAY_NUM = {
    "Monday": "1",
    "Tuesday": "2",
    "Wednesday": "3",
    "Thursday": "4",
    "Friday": "5",
    "Saturday": "6",
    "Sunday": "0",
}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SYSTEMD_UNIT_NAME = "log2topic-update"
CRON_MARKER = "# LOG2TOPIC_SCHEDULED_UPDATE"


def default_settings():
    return {
        "version": 2,
        "start_at_logon": False,
        "schedule_mode": "Off",
        "external_service": "Notion",
        "schedule_time": "02:30",
        "schedule_days": list(VALID_DAYS),
        "run_missed": True,
        "ui_language": "Auto",
        "prune_backups": False,
        "backup_retention_count": 100,
        "auto_check_updates": True,
        "update_repo": "Rubidius37/Log2Topic",
        "skipped_update_version": "",
        "workspace_path": "",
    }


def load_settings(config_path=CONFIG_PATH):
    settings = default_settings()
    if not os.path.isfile(config_path):
        return settings
    try:
        loaded = load_json_state(config_path, missing_default={}, expected_type=dict)
    except Exception:
        return settings
    for key in settings:
        if key in loaded and loaded[key] is not None:
            settings[key] = loaded[key]
    if str(settings.get("schedule_mode", "")).casefold() == "notion":
        settings["schedule_mode"] = "External"
    return settings


def parse_days(days_list=None, days_csv=""):
    if days_csv and days_csv.strip():
        raw = [part.strip() for part in days_csv.split(",") if part.strip()]
    elif days_list:
        raw = [part.strip() for part in days_list if part.strip()]
    else:
        raw = list(VALID_DAYS)
    invalid = [day for day in raw if day not in VALID_DAYS]
    if invalid:
        raise ValueError(f"Invalid schedule day: {', '.join(invalid)}")
    return raw


def build_systemd_units(root_dir, mode, service, time_str, days, run_missed):
    posix_root = root_dir.replace("\\", "/").rstrip("/")
    if mode == "External" and service == "Notion":
        launcher = "run_notion_sync.sh"
        launcher_args = "--nopause"
        description = "Update local Log2Topic documents and sync the optional Notion integration."
    elif mode == "ExternalOriginals" and service == "Notion":
        launcher = "run_notion_daily_sync.sh"
        launcher_args = "--all-daily --nopause"
        description = "Sync original Log2Topic daily logs only to the optional Notion integration."
    else:
        launcher = "run_local.sh"
        launcher_args = "--nopause"
        description = "Update local Log2Topic documents without external services."
    launcher_path = posixpath.join(posix_root, "scripts", launcher)
    day_spec = ",".join(SYSTEMD_DAY_ABBR[day] for day in days)
    service_content = (
        "[Unit]\n"
        f"Description={description}\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={posix_root}\n"
        f'ExecStart=/bin/sh "{launcher_path}" {launcher_args}\n'
    )
    timer_content = (
        "[Unit]\n"
        f"Description=Timer for {description}\n\n"
        "[Timer]\n"
        f"OnCalendar={day_spec} *-*-* {time_str}:00\n"
        f"Persistent={'true' if run_missed else 'false'}\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service_content, timer_content


def build_cron_line(root_dir, mode, service, time_str, days):
    match = TIME_RE.fullmatch(time_str)
    if not match:
        raise ValueError(f"Invalid time format: {time_str}")
    hour, minute = int(match.group(1)), int(match.group(2))
    dow = ",".join(CRON_DAY_NUM[day] for day in days)
    posix_root = root_dir.replace("\\", "/").rstrip("/")
    if mode == "External" and service == "Notion":
        launcher = "run_notion_sync.sh"
        launcher_args = "--nopause"
    elif mode == "ExternalOriginals" and service == "Notion":
        launcher = "run_notion_daily_sync.sh"
        launcher_args = "--all-daily --nopause"
    else:
        launcher = "run_local.sh"
        launcher_args = "--nopause"
    launcher_path = posixpath.join(posix_root, "scripts", launcher)
    return f'{minute} {hour} * * {dow} cd "{posix_root}" && /bin/sh "{launcher_path}" {launcher_args} >/dev/null 2>&1 {CRON_MARKER}'


def apply_linux_schedule(root_dir, mode, service, time_str, days, run_missed, systemd_dir=None):
    user_Unit_dir = systemd_dir or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "systemd",
        "user",
    )
    service_path = os.path.join(user_Unit_dir, f"{SYSTEMD_UNIT_NAME}.service")
    timer_path = os.path.join(user_Unit_dir, f"{SYSTEMD_UNIT_NAME}.timer")

    if mode == "Off":
        for path in (timer_path, service_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        if systemd_dir is None and shutil.which("systemctl"):
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"],
                capture_output=True,
                check=False,
            )
        _update_crontab(None)
        return "off"

    os.makedirs(user_Unit_dir, exist_ok=True)
    service_text, timer_text = build_systemd_units(
        root_dir, mode, service, time_str, days, run_missed
    )
    with open(service_path, "w", encoding="utf-8", newline="\n") as file_obj:
        file_obj.write(service_text)
    with open(timer_path, "w", encoding="utf-8", newline="\n") as file_obj:
        file_obj.write(timer_text)

    if systemd_dir is None and shutil.which("systemctl"):
        reload_res = subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True,
            check=False,
        )
        enable_res = subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT_NAME}.timer"],
            capture_output=True,
            check=False,
        )
        if reload_res.returncode == 0 and enable_res.returncode == 0:
            _update_crontab(None)
            return "systemd"

    if systemd_dir is None:
        cron_line = build_cron_line(root_dir, mode, service, time_str, days)
        if _update_crontab(cron_line):
            return "cron"
    return "systemd-files"


def _update_crontab(new_line):
    if not shutil.which("crontab"):
        return False
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if res.returncode == 0:
        existing = res.stdout.splitlines()
    elif "no crontab" in (res.stderr or "").casefold():
        existing = []
    else:
        return False
    filtered = [line for line in existing if CRON_MARKER not in line]
    if new_line:
        filtered.append(new_line)
    if filtered == existing:
        return True
    payload = ("\n".join(filtered).strip() + "\n") if filtered else ""
    write_res = subprocess.run(
        ["crontab", "-"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    return write_res.returncode == 0


def apply_linux_autostart(root_dir, enabled, autostart_dir=None):
    target_dir = autostart_dir or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "autostart",
    )
    desktop_path = os.path.join(target_dir, "log2topic.desktop")
    if not enabled:
        if os.path.exists(desktop_path):
            try:
                os.remove(desktop_path)
            except OSError:
                pass
        return desktop_path

    os.makedirs(target_dir, exist_ok=True)
    posix_root = root_dir.replace("\\", "/").rstrip("/")
    launcher = posixpath.join(posix_root, "Log2Topic.sh")
    icon = posixpath.join(posix_root, "assets", "log2topic.png")
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Log2Topic\n"
        "Comment=Local-first Markdown research log organizer\n"
        f'Exec=/bin/sh "{launcher}" update\n'
        f"Path={posix_root}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    with open(desktop_path, "w", encoding="utf-8", newline="\n") as file_obj:
        file_obj.write(content)
    return desktop_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Configure Log2Topic automation settings.")
    parser.add_argument(
        "--mode",
        choices=("Off", "Local", "External", "ExternalOriginals", "Notion"),
        default="Off",
    )
    parser.add_argument("--service", choices=("Notion",), default="Notion")
    parser.add_argument("--time", default="02:30")
    parser.add_argument("--days", nargs="*", default=None)
    parser.add_argument("--days-csv", default="")
    parser.add_argument("--language", choices=("Auto", "auto", "en", "ko"), default="Auto")
    parser.add_argument("--prune-backups", action="store_true")
    parser.add_argument("--backup-retention-count", type=int, default=100)
    parser.add_argument("--disable-auto-update-check", action="store_true")
    parser.add_argument("--enable-startup", action="store_true")
    parser.add_argument("--run-missed", action="store_true")
    parser.add_argument("--workspace-path", default=None)
    parser.add_argument(
        "--rule-template",
        choices=("", "simple", "research", "software"),
        default="",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--config-path", default=CONFIG_PATH)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.status:
        current = load_settings(args.config_path)
        print(json.dumps(current, indent=2, ensure_ascii=False))
        return 0

    if not TIME_RE.fullmatch(args.time):
        print(f"Error: Invalid time '{args.time}'. Expected HH:MM (24-hour).", file=sys.stderr)
        return 2
    if not 1 <= args.backup_retention_count <= 10000:
        print("Error: --backup-retention-count must be between 1 and 10000.", file=sys.stderr)
        return 2

    try:
        effective_days = parse_days(args.days, args.days_csv)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    effective_mode = "External" if args.mode == "Notion" else args.mode
    if effective_mode != "Off" and not effective_days:
        print("Error: At least one day must be selected for automatic updates.", file=sys.stderr)
        return 2

    for script_name in ("run_local.sh", "run_notion_sync.sh", "run_notion_daily_sync.sh"):
        script_path = os.path.join(SCRIPT_DIR, script_name)
        if not os.path.isfile(script_path):
            print(f"Error: Scheduled launcher was not found: {script_path}", file=sys.stderr)
            return 2

    if args.validate_only:
        print("Log2Topic automation configuration is valid.")
        return 0

    if os.name == "posix":
        apply_linux_schedule(
            VAULT_ROOT,
            effective_mode,
            args.service,
            args.time,
            effective_days,
            args.run_missed,
        )
        apply_linux_autostart(VAULT_ROOT, args.enable_startup)

    existing = load_settings(args.config_path)
    if args.workspace_path is None:
        workspace_path_val = str(existing.get("workspace_path", "") or "").strip()
    else:
        raw_wp = args.workspace_path.strip()
        bundled_default = os.path.abspath(os.path.join(VAULT_ROOT, "Workspace"))
        if not raw_wp or os.path.normcase(os.path.abspath(os.path.expanduser(raw_wp))) == os.path.normcase(bundled_default):
            workspace_path_val = ""
        else:
            workspace_path_val = os.path.abspath(os.path.expanduser(raw_wp))

    settings = {
        "version": 2,
        "start_at_logon": bool(args.enable_startup),
        "schedule_mode": effective_mode,
        "external_service": args.service,
        "schedule_time": args.time,
        "schedule_days": list(effective_days),
        "run_missed": bool(args.run_missed),
        "ui_language": args.language,
        "prune_backups": bool(args.prune_backups),
        "backup_retention_count": int(args.backup_retention_count),
        "auto_check_updates": not bool(args.disable_auto_update_check),
        "update_repo": existing.get("update_repo", "Rubidius37/Log2Topic"),
        "skipped_update_version": existing.get("skipped_update_version", ""),
        "workspace_path": workspace_path_val,
    }
    atomic_write_json(args.config_path, settings)
    target_ws = workspace_path_val or resolve_workspace_dir(SCRIPT_DIR)
    if workspace_path_val or args.rule_template:
        ensure_workspace_initialized(
            target_ws,
            template_name=args.rule_template or None,
            backup_root=os.path.join(SCRIPT_DIR, "source_id_backups"),
        )
    print("Log2Topic automation settings were updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
