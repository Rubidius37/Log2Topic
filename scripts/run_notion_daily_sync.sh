#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/setup_workspace.sh" ]; then
    sh "$ROOT/setup_workspace.sh"
fi

echo "======================================================================"
echo " [Log2Topic] Fast Daily Note Sync - Optional Notion Integration"
echo " Execution Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

. "$SCRIPT_DIR/resolve_python.sh"

if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/sync_to_notion.py" --daily-only "$@"; then
    echo "[ERROR] Optional Notion Daily sync failed." >&2
    exit 1
fi

echo "======================================================================"
echo " [SUCCESS] Optional Notion Daily sync completed."
echo "======================================================================"
exit 0
