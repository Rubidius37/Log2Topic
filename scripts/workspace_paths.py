"""Resolve the Markdown workspace independently from the application folder."""

from datetime import datetime
import json
import os
import shutil


WORKSPACE_DIRECTORY_NAME = "Workspace"
RULES_FILENAME = "Classification_Rules.md"
WORKSPACE_ENV_VAR = "LOG2TOPIC_WORKSPACE"

RULE_TEMPLATE_TABLES = {
    "simple": """\
| 대분류 (Level 1) | 중분류 (Level 2) | 소분류 (Level 3) | 상세 분류 (Level 4) | 세부 태스크 (Level 5) | 매칭 키워드 (쉼표: OR, 띄어쓰기: AND) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Projects | Project A | | | | project a |
| | Project B | | | | project b |
| Notes | General | | | | note, memo |""",
    "research": """\
| 대분류 (Level 1) | 중분류 (Level 2) | 소분류 (Level 3) | 상세 분류 (Level 4) | 세부 태스크 (Level 5) | 매칭 키워드 (쉼표: OR, 띄어쓰기: AND) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Research | Topic A | Experiment | | | experiment, 실험 |
| | | Analysis | | | analysis, 분석 |
| | | Literature | | | paper, 논문, 문헌 |
| | Topic B | Experiment | | | |
| | | Analysis | | | |
| Knowledge | Methods | | | | method, 방법론 |""",
    "software": """\
| 대분류 (Level 1) | 중분류 (Level 2) | 소분류 (Level 3) | 상세 분류 (Level 4) | 세부 태스크 (Level 5) | 매칭 키워드 (쉼표: OR, 띄어쓰기: AND) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Projects | Sample Project | Planning | Requirements | | requirement, plan |
| | | Testing | Functional Test | | functional test |
| | | | Regression Test | | regression test |
| Knowledge | Methods | Data Analysis | | | analysis, dataset |
| | References | | | | reference, document |""",
}


def render_rule_template(template_name="software"):
    key = str(template_name or "software").strip().lower()
    if key not in RULE_TEMPLATE_TABLES:
        raise ValueError(f"Unknown rule template: {template_name}")
    table = RULE_TEMPLATE_TABLES[key]
    return (
        "# 분류 규칙\n\n"
        "아래 표가 실제 자동 분류 규칙입니다. **표의 여섯 열과 열 순서는 바꾸지 마세요.** "
        "새 Level 1은 첫 번째 열에 이름을 적은 행을 추가하면 됩니다.\n\n"
        "## 실제 분류 규칙\n\n"
        f"{table}\n\n"
        "## 사용 방법\n\n"
        "1. 일지의 `#`부터 `#####`까지를 표의 Level 1부터 Level 5까지의 이름과 맞춥니다 (초보자는 Level 1~2만 작성해도 동작합니다).\n"
        "2. Heading이 분류명과 정확히 일치하면 키워드는 없어도 됩니다.\n"
        "3. 새 경로를 추가한 뒤 Log2Topic에서 `로컬 문서 갱신`을 실행해 결과를 확인합니다.\n"
    )


def ensure_workspace_initialized(workspace_dir, template_name=None, backup_root=None):
    workspace_dir = os.path.abspath(os.path.expanduser(workspace_dir))
    os.makedirs(os.path.join(workspace_dir, "Daily_Logs"), exist_ok=True)
    os.makedirs(os.path.join(workspace_dir, "attachments"), exist_ok=True)
    rules_path = os.path.join(workspace_dir, RULES_FILENAME)
    if template_name:
        if os.path.isfile(rules_path) and backup_root:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target_backup_dir = os.path.join(backup_root, "rule_templates", stamp)
            os.makedirs(target_backup_dir, exist_ok=True)
            shutil.copy2(rules_path, os.path.join(target_backup_dir, RULES_FILENAME))
        with open(rules_path, "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(render_rule_template(template_name))
    elif not os.path.isfile(rules_path):
        with open(rules_path, "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(render_rule_template("software"))
    return workspace_dir


def get_application_root(script_dir):
    """Return the distribution root that contains the scripts directory."""
    return os.path.abspath(os.path.join(script_dir, ".."))


def _read_configured_workspace_path(script_dir):
    settings_path = os.path.join(os.path.abspath(script_dir), ".runtime", "tray_settings.json")
    if not os.path.isfile(settings_path):
        return ""
    try:
        with open(settings_path, "r", encoding="utf-8-sig") as file_obj:
            data = json.load(file_obj)
        if isinstance(data, dict):
            raw = str(data.get("workspace_path", "") or "").strip()
            if raw:
                return os.path.abspath(os.path.expanduser(raw))
    except Exception:
        pass
    return ""


def resolve_workspace_dir(script_dir):
    """Use an explicit workspace override, bundled Workspace, or legacy layout."""
    env_override = (os.environ.get(WORKSPACE_ENV_VAR) or "").strip()
    if env_override:
        return os.path.abspath(os.path.expanduser(env_override))

    configured = _read_configured_workspace_path(script_dir)
    if configured:
        return configured

    application_root = get_application_root(script_dir)
    workspace_dir = os.path.join(application_root, WORKSPACE_DIRECTORY_NAME)
    workspace_rules = os.path.join(workspace_dir, RULES_FILENAME)
    if os.path.isfile(workspace_rules):
        return os.path.abspath(workspace_dir)
    return application_root


def resolve_workspace_state_dir(script_dir, workspace_dir):
    """Keep runtime state beside scripts for bundled workspaces and legacy vaults."""
    script_dir = os.path.abspath(script_dir)
    workspace_dir = os.path.abspath(workspace_dir)
    bundled_workspace = resolve_workspace_dir(script_dir)
    if os.path.normcase(workspace_dir) == os.path.normcase(bundled_workspace):
        return script_dir
    return os.path.join(workspace_dir, "scripts")
