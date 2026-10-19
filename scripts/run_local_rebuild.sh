#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

NO_PAUSE=0
AUTO_YES=0
for arg in "$@"; do
    case "$arg" in
        --nopause) NO_PAUSE=1 ;;
        --yes|-y) AUTO_YES=1 ;;
    esac
done

. "$SCRIPT_DIR/resolve_python.sh"

echo "This rebuilds Source ID markers after replacing the source-log corpus."
echo "Existing source files are backed up under scripts/source_id_backups/rebuild."
echo ""
if [ "$AUTO_YES" -eq 0 ]; then
    printf "Continue? [y/N] "
    read -r answer
    case "$answer" in
        [Yy]*) ;;
        *) exit 0 ;;
    esac
fi

if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json --rebuild-source-ids; then
    echo "[ERROR] Source ID rebuild failed." >&2
    if [ "$NO_PAUSE" -eq 0 ] && [ -t 0 ]; then
        printf "Press Enter to continue..."
        read -r _
    fi
    exit 1
fi

exit 0
