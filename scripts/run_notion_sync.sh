#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/setup_workspace.sh" ]; then
    sh "$ROOT/setup_workspace.sh"
fi

CLASSIFY_ARGS=""
SYNC_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --nopause)
            ;;
        --no-persist-source-ids|--initialize-source-ids)
            CLASSIFY_ARGS="$CLASSIFY_ARGS $arg"
            ;;
        *)
            SYNC_ARGS="$SYNC_ARGS $arg"
            ;;
    esac
done

echo "======================================================================"
echo " [Log2Topic] Update Local Notes and Sync Optional Notion Integration"
echo " Execution Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

. "$SCRIPT_DIR/resolve_python.sh"

echo "1. Updating local Markdown research notes..."
# shellcheck disable=SC2086
if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json $CLASSIFY_ARGS; then
    echo "[WARNING] Local update failed. Syncing original daily notes only." >&2
    echo "[WARNING] Generated notes and all cleanup will be skipped." >&2
    # shellcheck disable=SC2086
    "$PYTHON_CMD" -u "$SCRIPT_DIR/sync_to_notion.py" $SYNC_ARGS --classification-failed || true
    echo "[PARTIAL FAILURE] Classification failed. See the sync report for original-note results." >&2
    exit 1
fi

echo "2. Syncing the optional Notion integration..."
# shellcheck disable=SC2086
if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/sync_to_notion.py" $SYNC_ARGS; then
    echo "[ERROR] Optional Notion sync failed. Local files remain available." >&2
    exit 1
fi

echo "======================================================================"
echo " [SUCCESS] Local update and optional Notion sync completed."
echo "======================================================================"
exit 0
