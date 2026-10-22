#!/usr/bin/env python3
"""Cross-platform pure-Python CLI entrypoint for Log2Topic (Windows, macOS, Linux)."""

import os
import subprocess
import sys


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from workspace_paths import resolve_workspace_dir


def ensure_workspace():
    workspace_dir = resolve_workspace_dir(SCRIPTS_DIR)
    rules_path = os.path.join(workspace_dir, "Classification_Rules.md")
    if not os.path.isfile(rules_path):
        print(f"[ERROR] Classification rules were not found: {rules_path}", file=sys.stderr)
        return False
    daily_dir = os.path.join(workspace_dir, "Daily_Logs")
    attachments_dir = os.path.join(workspace_dir, "attachments")
    os.makedirs(daily_dir, exist_ok=True)
    os.makedirs(attachments_dir, exist_ok=True)

    metadata_path = os.path.join(SCRIPTS_DIR, "organizer_metadata.json")
    has_md = any(
        fname.lower().endswith(".md")
        for _r, _d, files in os.walk(daily_dir)
        for fname in files
    )
    bundled_workspace = os.path.join(ROOT_DIR, "Workspace")
    is_bundled = os.path.normcase(os.path.realpath(workspace_dir)) == os.path.normcase(
        os.path.realpath(bundled_workspace)
    )
    if is_bundled and not os.path.exists(metadata_path) and not has_md:
        sample1 = os.path.join(daily_dir, "2026-09-01-log.md")
        sample2 = os.path.join(daily_dir, "2026-09-02-log.md")
        try:
            with open(sample1, "w", encoding="utf-8", newline="\n") as f:
                f.write(
                    "# Projects\n## Sample Project\n### Testing\n#### Functional Test\n"
                    "Verified that clicking Save writes the input text to the file.\n\n"
                    "#### Regression Test\n"
                    "Confirmed that line breaks are preserved when reopening existing files.\n"
                )
            with open(sample2, "w", encoding="utf-8", newline="\n") as f:
                f.write(
                    "# Projects\n## Sample Project\n### Testing\n#### Functional Test\n"
                    "Verified saving and reopening files with Unicode filenames.\n"
                )
        except OSError:
            pass
    return True


def run_python_script(script_name, extra_args=()):
    cmd = [sys.executable, "-u", os.path.join(SCRIPTS_DIR, script_name), *extra_args]
    res = subprocess.run(cmd, cwd=ROOT_DIR)
    return res.returncode


def run_full_notion_sync(args):
    classify_args = []
    sync_args = []
    for arg in args:
        if arg == "--nopause":
            continue
        if arg in {"--no-persist-source-ids", "--initialize-source-ids"}:
            classify_args.append(arg)
        else:
            sync_args.append(arg)
    rc = run_python_script(
        "hierarchical_classifier.py",
        [
            "--production",
            "--output-dir",
            "Subject",
            "--review-dir",
            "Topic_Reviews",
            "--metadata-file",
            "organizer_metadata.json",
            *classify_args,
        ],
    )
    if rc != 0:
        print("[WARNING] Local update failed. Syncing original daily notes only.", file=sys.stderr)
        run_python_script("sync_to_notion.py", [*sync_args, "--classification-failed"])
        return 1
    return run_python_script("sync_to_notion.py", sync_args)


def print_help():
    print("Usage: python log2topic.py [command] [args...]")
    print("")
    print("Commands:")
    print("  tray             Launch system tray icon (pystray) or desktop GUI (tkinter)")
    print("  gui              Open the desktop controller & settings window (tkinter)")
    print("  update           Update local Subject/ and Topic_Reviews/ documents")
    print("  review           Open the local classification review dashboard")
    print("  sync-daily       Sync recent Daily_Logs notes to Notion")
    print("  sync-originals   Sync all original Daily_Logs notes only to Notion")
    print("  sync             Update local documents and run full Notion sync")
    print("  rebuild          Rebuild Source ID markers after replacing Daily_Logs")
    print("  schedule         Configure scheduled updates and startup settings")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"help", "--help", "-h"}:
        print_help()
        return 0

    if not ensure_workspace():
        return 1

    if args:
        cmd, rest = args[0], args[1:]
        if cmd in {"update", "local"}:
            filtered = [a for a in rest if a != "--nopause"]
            return run_python_script(
                "hierarchical_classifier.py",
                [
                    "--production",
                    "--output-dir",
                    "Subject",
                    "--review-dir",
                    "Topic_Reviews",
                    "--metadata-file",
                    "organizer_metadata.json",
                    *filtered,
                ],
            )
        if cmd in {"review", "dashboard"}:
            return run_python_script("classification_review_dashboard.py", rest)
        if cmd == "sync-daily":
            return run_python_script("sync_to_notion.py", ["--daily-only", *rest])
        if cmd in {"sync-originals", "sync-daily-all"}:
            return run_python_script("sync_to_notion.py", ["--daily-only", "--all-daily", *rest])
        if cmd in {"sync", "sync-full"}:
            return run_full_notion_sync(rest)
        if cmd == "rebuild":
            auto_yes = any(a in {"--yes", "-y"} for a in rest)
            if not auto_yes:
                print("This rebuilds Source ID markers after replacing the source-log corpus.")
                print("Existing source files are backed up under scripts/source_id_backups/rebuild.")
                try:
                    ans = input("Continue? [y/N] ").strip()
                except EOFError:
                    return 0
                if not ans.lower().startswith("y"):
                    return 0
            return run_python_script(
                "hierarchical_classifier.py",
                [
                    "--production",
                    "--output-dir",
                    "Subject",
                    "--review-dir",
                    "Topic_Reviews",
                    "--metadata-file",
                    "organizer_metadata.json",
                    "--rebuild-source-ids",
                ],
            )
        if cmd in {"schedule", "settings"}:
            return run_python_script("configure_automation.py", rest)
        if cmd == "tray":
            return run_python_script("log2topic_gui.py", rest)
        if cmd == "gui":
            return run_python_script("log2topic_gui.py", ["--gui", *rest])
        print(f"[ERROR] Unknown command: {cmd}", file=sys.stderr)
        print_help()
        return 2

    print("======================================================================")
    print(" Log2Topic (Cross-Platform Python CLI)")
    print("======================================================================")
    print(" 1) Update local documents (로컬 문서 갱신)")
    print(" 2) Open classification review dashboard (분류 검토 대시보드 열기)")
    print(" 3) Notion: Sync recent logs (최근 일지 동기화)")
    print(" 4) Notion: Sync original logs only (원본 일지만 동기화)")
    print(" 5) Notion: Full sync (전체 동기화)")
    print(" 6) Rebuild after replacing source logs (원본 일지 교체 후 ID 재생성)")
    print(" 7) Show automation settings (자동 실행 설정 확인)")
    print(" 8) Launch system tray / desktop GUI (시스템 트레이 / 데스크톱 GUI 열기)")
    print(" 0) Exit")
    print("======================================================================")
    try:
        choice = input("Select an action [0-8]: ").strip()
    except EOFError:
        return 0
    mapping = {
        "1": ["update"],
        "2": ["review"],
        "3": ["sync-daily"],
        "4": ["sync-originals"],
        "5": ["sync"],
        "6": ["rebuild"],
        "7": ["schedule", "--status"],
        "8": ["tray"],
    }
    if choice in {"0", ""}:
        return 0
    if choice not in mapping:
        print(f"[ERROR] Invalid selection: {choice}", file=sys.stderr)
        return 1
    return main(mapping[choice])


if __name__ == "__main__":
    raise SystemExit(main())
