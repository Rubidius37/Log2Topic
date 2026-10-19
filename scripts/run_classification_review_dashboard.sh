#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

NO_PAUSE=0
for arg in "$@"; do
    if [ "$arg" = "--nopause" ]; then
        NO_PAUSE=1
    fi
done

if [ -f "$ROOT/setup_workspace.sh" ]; then
    sh "$ROOT/setup_workspace.sh"
fi

echo "======================================================================"
echo " [Log2Topic] Open Hierarchical Classification Review Dashboard"
echo "======================================================================"

. "$SCRIPT_DIR/resolve_python.sh"

if [ "$NO_PAUSE" -eq 1 ]; then
    mkdir -p "$SCRIPT_DIR/reports"
    {
        echo ""
        echo "======================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting classification review dashboard"
    } >> "$SCRIPT_DIR/reports/classification_review_dashboard.log"
    exec "$PYTHON_CMD" -u "$SCRIPT_DIR/classification_review_dashboard.py" "$@" >> "$SCRIPT_DIR/reports/classification_review_dashboard.log" 2>&1
fi

if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/classification_review_dashboard.py" "$@"; then
    echo ""
    echo "[ERROR] Failed to start the classification review dashboard." >&2
    echo "Check Classification_Rules.md and the console output above." >&2
    if [ -t 0 ]; then
        printf "Press Enter to continue..."
        read -r _
    fi
    exit 1
fi
exit 0
