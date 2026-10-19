#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [ -f "$ROOT/setup_workspace.sh" ]; then
    sh "$ROOT/setup_workspace.sh"
fi

NO_PAUSE=0
DRY_RUN=0
set -- "$@"
CLASSIFY_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --nopause)
            NO_PAUSE=1
            ;;
        --dry-run)
            DRY_RUN=1
            CLASSIFY_ARGS="$CLASSIFY_ARGS $arg"
            ;;
        *)
            CLASSIFY_ARGS="$CLASSIFY_ARGS $arg"
            ;;
    esac
done

echo "======================================================================"
echo " [Log2Topic] Update Local Markdown Research Notes"
echo " Execution Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

. "$SCRIPT_DIR/resolve_python.sh"

# shellcheck disable=SC2086
if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json $CLASSIFY_ARGS; then
    echo "[ERROR] Local update failed!" >&2
    if [ "$NO_PAUSE" -eq 0 ] && [ -t 0 ]; then
        printf "Press Enter to continue..."
        read -r _
    fi
    exit 1
fi

echo "======================================================================"
if [ "$DRY_RUN" -eq 1 ]; then
    echo " [SUCCESS] Local dry-run completed. No files were updated."
else
    echo " [SUCCESS] Local Subject and Topic Review files were updated."
fi
echo "======================================================================"
exit 0
