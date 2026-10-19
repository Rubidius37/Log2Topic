#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
SCRIPT_DIR="$ROOT/scripts"

if [ -f "$ROOT/setup_workspace.sh" ]; then
    sh "$ROOT/setup_workspace.sh"
fi

run_subcommand() {
    cmd="$1"
    shift
    case "$cmd" in
        update|local)
            exec sh "$SCRIPT_DIR/run_local.sh" --nopause "$@"
            ;;
        review|dashboard)
            exec sh "$SCRIPT_DIR/run_classification_review_dashboard.sh" "$@"
            ;;
        sync-daily)
            exec sh "$SCRIPT_DIR/run_notion_daily_sync.sh" --nopause "$@"
            ;;
        sync-originals|sync-daily-all)
            exec sh "$SCRIPT_DIR/run_notion_daily_sync.sh" --all-daily --nopause "$@"
            ;;
        sync|sync-full)
            exec sh "$SCRIPT_DIR/run_notion_sync.sh" --nopause "$@"
            ;;
        rebuild)
            exec sh "$SCRIPT_DIR/run_local_rebuild.sh" "$@"
            ;;
        cleanup-cloudinary)
            exec sh "$SCRIPT_DIR/run_cloudinary_cleanup.sh" --nopause "$@"
            ;;
        schedule|settings)
            . "$SCRIPT_DIR/resolve_python.sh"
            exec "$PYTHON_CMD" -u "$SCRIPT_DIR/configure_automation.py" "$@"
            ;;
        tray)
            . "$SCRIPT_DIR/resolve_python.sh"
            exec "$PYTHON_CMD" -u "$SCRIPT_DIR/log2topic_gui.py" "$@"
            ;;
        gui)
            . "$SCRIPT_DIR/resolve_python.sh"
            exec "$PYTHON_CMD" -u "$SCRIPT_DIR/log2topic_gui.py" --gui "$@"
            ;;
        help|--help|-h)
            echo "Usage: ./Log2Topic.sh [command] [args...]"
            echo ""
            echo "Commands:"
            echo "  tray             Launch system tray icon (pystray) or desktop GUI (tkinter)"
            echo "  gui              Open the desktop controller & settings window (tkinter)"
            echo "  update           Update local Subject and Topic_Reviews documents"
            echo "  review           Open the local classification review dashboard"
            echo "  sync-daily       Sync recent Daily_Logs notes to Notion"
            echo "  sync-originals   Sync all original Daily_Logs notes only to Notion"
            echo "  sync             Update local documents and run full Notion sync"
            echo "  rebuild          Rebuild Source ID markers after replacing Daily_Logs"
            echo "  schedule         Configure scheduled updates (systemd/cron) and autostart"
            exit 0
            ;;
        *)
            echo "[ERROR] Unknown command: $cmd" >&2
            echo "Run './Log2Topic.sh --help' for usage." >&2
            exit 2
            ;;
    esac
}

if [ "$#" -gt 0 ]; then
    run_subcommand "$@"
fi

echo "======================================================================"
echo " Log2Topic (Linux / POSIX Menu)"
echo "======================================================================"
echo " 1) Update local documents (로컬 문서 갱신)"
echo " 2) Open classification review dashboard (분류 검토 대시보드 열기)"
echo " 3) Notion: Sync recent logs (최근 일지 동기화)"
echo " 4) Notion: Sync original logs only (원본 일지만 동기화)"
echo " 5) Notion: Full sync (전체 동기화)"
echo " 6) Rebuild after replacing source logs (원본 일지 교체 후 ID 재생성)"
echo " 7) Show automation settings (자동 실행 설정 확인)"
echo " 8) Launch system tray / desktop GUI (시스템 트레이 / 데스크톱 GUI 열기)"
echo " 0) Exit"
echo "======================================================================"
printf "Select an action [0-8]: "
read -r choice

case "$choice" in
    1) exec sh "$SCRIPT_DIR/run_local.sh" ;;
    2) exec sh "$SCRIPT_DIR/run_classification_review_dashboard.sh" ;;
    3) exec sh "$SCRIPT_DIR/run_notion_daily_sync.sh" ;;
    4) exec sh "$SCRIPT_DIR/run_notion_daily_sync.sh" --all-daily ;;
    5) exec sh "$SCRIPT_DIR/run_notion_sync.sh" ;;
    6) exec sh "$SCRIPT_DIR/run_local_rebuild.sh" ;;
    7)
        . "$SCRIPT_DIR/resolve_python.sh"
        exec "$PYTHON_CMD" -u "$SCRIPT_DIR/configure_automation.py" --status
        ;;
    8)
        . "$SCRIPT_DIR/resolve_python.sh"
        exec "$PYTHON_CMD" -u "$SCRIPT_DIR/log2topic_gui.py"
        ;;
    0|"") exit 0 ;;
    *)
        echo "[ERROR] Invalid selection: $choice" >&2
        exit 1
        ;;
esac
