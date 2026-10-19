#!/usr/bin/env sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

echo "======================================================================"
echo " [Log2Topic] Cloudinary Image Cleanup"
echo " Execution Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

. "$SCRIPT_DIR/resolve_python.sh"

CLEANUP_ARGS=""
for arg in "$@"; do
    if [ "$arg" != "--nopause" ]; then
        CLEANUP_ARGS="$CLEANUP_ARGS $arg"
    fi
done

# shellcheck disable=SC2086
if ! "$PYTHON_CMD" -u "$SCRIPT_DIR/cloudinary_cleanup.py" $CLEANUP_ARGS; then
    echo "[ERROR] Cloudinary cleanup failed!" >&2
    exit 1
fi

echo "======================================================================"
echo " [SUCCESS] Cloudinary cleanup completed."
echo "======================================================================"
exit 0
