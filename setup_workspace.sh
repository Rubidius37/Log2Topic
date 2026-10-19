#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE="$ROOT/Workspace"

if [ ! -f "$WORKSPACE/Classification_Rules.md" ]; then
    echo "[ERROR] Workspace/Classification_Rules.md was not found. Restore it from Git." >&2
    exit 1
fi

mkdir -p "$WORKSPACE/Daily_Logs" "$WORKSPACE/attachments"

if [ ! -f "$ROOT/scripts/organizer_metadata.json" ] && [ -z "$(find "$WORKSPACE/Daily_Logs" -name '*.md' -print -quit 2>/dev/null)" ]; then
    cat > "$WORKSPACE/Daily_Logs/260901 일지.md" << 'EOF'
# Projects
## Sample Project
### Testing
#### Functional Test
저장 버튼을 누르면 입력한 내용이 파일에 기록되는 것을 확인했다.

#### Regression Test
기존 파일을 다시 열었을 때 줄바꿈이 유지되는 것을 확인했다.
EOF
    cat > "$WORKSPACE/Daily_Logs/260902 일지.md" << 'EOF'
# Projects
## Sample Project
### Testing
#### Functional Test
한글 파일명으로 저장하고 다시 여는 동작을 확인했다.
EOF
fi

echo "Workspace setup is ready."
exit 0
