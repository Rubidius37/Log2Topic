import argparse
import json
import locale
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from atomic_io import atomic_write_json, atomic_write_text as _atomic_write_text, filesystem_path
from hierarchical_classifier import (
    CATEGORY_LEVELS,
    HEADING_RE,
    MERGE_ABOVE_MARKER_NAME,
    MERGE_ABOVE_RE,
    METADATA_SCHEMA_VERSION,
    SOURCE_ID_RE,
    is_category_header,
    is_document_preamble,
    is_prefix,
    is_table_divider,
    iter_active_category_lines,
    make_source_anchor,
    normalize_name,
    normalize_rel_path,
    parse_markdown_into_units,
    parse_rules_from_markdown,
    prune_backup_batches,
    resolve_backup_retention_limit,
    source_lines_with_code_context,
    source_unit_fingerprint,
    split_markdown_table_row,
)
from process_lock import (
    ProcessLockUnavailable,
    VaultProcessLock,
    command_text,
    delegated_lock_environment,
)
from workspace_paths import resolve_workspace_dir


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT_DIR = resolve_workspace_dir(SCRIPT_DIR)
STATIC_DIR = os.path.join(SCRIPT_DIR, "classification_review_ui")
METADATA_PATH = os.path.join(SCRIPT_DIR, "organizer_metadata.json")
RULES_PATH = os.path.join(VAULT_DIR, "Classification_Rules.md")
BACKUP_DIR = os.path.join(SCRIPT_DIR, "source_id_backups", "classification_review")
MAX_REQUEST_BYTES = 64 * 1024
SOURCE_ID_VALUE_RE = re.compile(r"^[a-fA-F0-9]{8,64}$")
DASHBOARD_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
CATEGORY_LINE_RE = re.compile(r"^(Category|분류)\s*:", re.IGNORECASE)
CLASSIFICATION_LOCK = threading.Lock()
DASHBOARD_CLOSE_GRACE_SECONDS = 3.0
TRAY_SETTINGS_PATH = os.path.join(SCRIPT_DIR, ".runtime", "tray_settings.json")
DASHBOARD_CSRF_TOKEN = secrets.token_urlsafe(24)
ALLOWED_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def resolve_ui_language(settings_path=TRAY_SETTINGS_PATH):
    requested = os.environ.get("LOG2TOPIC_LANGUAGE", "Auto")
    try:
        with open(settings_path, "r", encoding="utf-8") as file_obj:
            value = json.load(file_obj)
        if requested.casefold() == "auto" and isinstance(value, dict):
            requested = str(value.get("ui_language", requested))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    if requested.casefold() in {"ko", "ko-kr"}:
        return "ko"
    if requested.casefold() in {"en", "en-us"}:
        return "en"
    system_locale = locale.getlocale()[0] or ""
    return "ko" if system_locale.casefold().startswith("ko") else "en"


ERROR_TRANSLATIONS = {
    "분류 metadata가 없습니다. 먼저 계층형 분류를 실행하세요.": "Classification metadata is missing. Update local documents first.",
    "분류 metadata 형식이 올바르지 않습니다.": "The classification metadata format is invalid.",
    "분류 metadata가 이전 형식입니다. 계층형 분류를 다시 실행하세요.": "Classification metadata is outdated. Update local documents again.",
    "Classification_Rules.md에 오류가 있습니다.": "Classification_Rules.md contains errors.",
    "검토 대상 원본은 Daily_Logs 아래에 있어야 합니다.": "Review sources must be under Daily_Logs.",
    "허용되지 않은 원본 경로입니다.": "This source path is not allowed.",
    "동일한 Source ID marker가 원본에 중복되어 있습니다.": "The same Source ID marker appears more than once in the source.",
    "Source ID에 해당하는 원본 구간을 하나로 확정할 수 없습니다. 분류를 다시 실행하세요.": "The source section for this Source ID is ambiguous. Update local documents again.",
    "분류 metadata의 entries 형식이 올바르지 않습니다.": "The classification metadata entries are invalid.",
    "하나 이상의 분류 경로를 선택하세요.": "Select at least one category path.",
    "분류 경로 형식이 올바르지 않습니다.": "The category path format is invalid.",
    "분류 경로에 빈 단계가 있습니다.": "The category path contains an empty level.",
    "Source ID 형식이 올바르지 않습니다.": "The Source ID format is invalid.",
    "원본 fingerprint가 없습니다. 화면을 새로 고치세요.": "The source fingerprint is missing. Refresh the page.",
    "Source ID가 최신 metadata에 없습니다.": "The Source ID is not present in the latest metadata.",
    "원본 일지가 화면을 연 뒤 변경되었습니다. 새로 고친 후 다시 적용하세요.": "The source changed after this page opened. Refresh and apply again.",
    "요청 크기가 올바르지 않습니다.": "The request size is invalid.",
    "JSON 요청만 허용됩니다.": "Only JSON requests are allowed.",
    "요청 본문 형식이 올바르지 않습니다.": "The request body format is invalid.",
    "대시보드 세션 형식이 올바르지 않습니다.": "The dashboard session format is invalid.",
    "허용되지 않은 요청 출처입니다.": "This request origin is not allowed.",
    "허용되지 않은 요청 호스트입니다.": "This request host is not allowed.",
    "다른 분류 작업이 진행 중입니다.": "Another classification task is running.",
    "원본 분류는 저장했지만 계층형 결과 재생성에 실패했습니다.": "Source categories were saved, but hierarchical results could not be rebuilt.",
    "원본 분류와 계층형 결과를 갱신했습니다.": "Source categories and hierarchical results were updated.",
    "새 분류 규칙을 추가하고 계층형 결과를 갱신했습니다.": "Added the new classification rule and updated hierarchical results.",
    "분류 규칙은 저장했지만 계층형 결과 재생성에 실패했습니다.": "The classification rule was saved, but hierarchical results could not be rebuilt.",
    "분류 이름과 키워드에는 '|' 문자를 사용할 수 없습니다.": "Category names and keywords cannot contain the '|' character.",
    "Classification_Rules.md에서 규칙 표를 찾을 수 없습니다.": "Could not find the rules table in Classification_Rules.md.",
    "합칠 수 있는 상위/이전 구간이 없습니다.": "There is no preceding section to merge into.",
    "구간을 이전 구간에 병합하고 계층형 결과를 갱신했습니다.": "Merged the section into the previous section and updated hierarchical results.",
    "JSON 요청을 해석할 수 없습니다.": "The JSON request could not be parsed.",
}


def localize_message(message):
    if resolve_ui_language() == "ko":
        return message
    if message in ERROR_TRANSLATIONS:
        return ERROR_TRANSLATIONS[message]
    prefixes = {
        "분류 metadata를 읽을 수 없습니다: ": "Could not read classification metadata: ",
        "원본 파일을 찾을 수 없습니다: ": "Source file not found: ",
        "Classification_Rules.md에 없는 경로입니다: ": "Path not found in Classification_Rules.md: ",
        "이미 Classification_Rules.md에 존재하는 경로입니다: ": "Path already exists in Classification_Rules.md: ",
        "서버 오류가 발생했습니다: ": "Server error: ",
        "분류 적용 중 오류가 발생했습니다: ": "Error while applying categories: ",
    }
    for prefix, translated in prefixes.items():
        if message.startswith(prefix):
            return translated + message[len(prefix):]
    return message


class ReviewError(Exception):
    def __init__(self, message, status=HTTPStatus.BAD_REQUEST, details=None):
        super().__init__(message)
        self.message = message
        self.status = int(status)
        self.details = details or {}


class DashboardLifecycle:
    def __init__(self, close_delay=DASHBOARD_CLOSE_GRACE_SECONDS, busy_check=None):
        self.close_delay = close_delay
        self.busy_check = busy_check or (lambda: False)
        self.server = None
        self.sessions = set()
        self.lock = threading.RLock()
        self.shutdown_timer = None
        self.generation = 0

    def attach(self, server):
        self.server = server

    def open(self, session_id):
        with self.lock:
            self.sessions.add(session_id)
            self.generation += 1
            self._cancel_timer_locked()

    def close(self, session_id):
        with self.lock:
            if session_id not in self.sessions:
                return False
            self.sessions.remove(session_id)
            if not self.sessions:
                self._schedule_shutdown_locked()
            return True

    def stop(self):
        with self.lock:
            self.generation += 1
            self.sessions.clear()
            self._cancel_timer_locked()

    def _cancel_timer_locked(self):
        if self.shutdown_timer is not None:
            self.shutdown_timer.cancel()
            self.shutdown_timer = None

    def _schedule_shutdown_locked(self):
        self.generation += 1
        generation = self.generation
        self._cancel_timer_locked()
        timer = threading.Timer(self.close_delay, self._attempt_shutdown, (generation,))
        timer.daemon = True
        self.shutdown_timer = timer
        timer.start()

    def _attempt_shutdown(self, generation):
        with self.lock:
            if generation != self.generation or self.sessions:
                return
            self.shutdown_timer = None
            if self.busy_check():
                self._schedule_shutdown_locked()
                return
            server = self.server
        if server is not None:
            server.shutdown()


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            value = json.load(file_obj)
    except FileNotFoundError as exc:
        raise ReviewError(
            "분류 metadata가 없습니다. 먼저 계층형 분류를 실행하세요.",
            HTTPStatus.SERVICE_UNAVAILABLE,
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(
            f"분류 metadata를 읽을 수 없습니다: {exc}",
            HTTPStatus.SERVICE_UNAVAILABLE,
        ) from exc
    if not isinstance(value, dict):
        raise ReviewError("분류 metadata 형식이 올바르지 않습니다.", HTTPStatus.SERVICE_UNAVAILABLE)
    return value


def load_review_context(vault_dir=VAULT_DIR, metadata_path=METADATA_PATH, rules_path=RULES_PATH):
    metadata = load_json(metadata_path)
    schema_version = metadata.get("schema_version", 0)
    if schema_version < METADATA_SCHEMA_VERSION:
        raise ReviewError(
            "분류 metadata가 이전 형식입니다. 계층형 분류를 다시 실행하세요.",
            HTTPStatus.CONFLICT,
        )
    tree = parse_rules_from_markdown(rules_path)
    if tree.errors:
        raise ReviewError(
            "Classification_Rules.md에 오류가 있습니다.",
            HTTPStatus.CONFLICT,
            {"errors": tree.errors},
        )
    return metadata, tree


def resolve_source_path(vault_dir, source_rel_path):
    normalized = normalize_rel_path(source_rel_path or "").lstrip("/")
    if not normalized.casefold().startswith("daily_logs/"):
        raise ReviewError("검토 대상 원본은 Daily_Logs 아래에 있어야 합니다.")
    full_path = os.path.abspath(os.path.join(vault_dir, *normalized.split("/")))
    daily_root = os.path.abspath(os.path.join(vault_dir, "Daily_Logs"))
    try:
        is_inside = os.path.commonpath([full_path, daily_root]) == daily_root
    except ValueError:
        is_inside = False
    if not is_inside:
        raise ReviewError("허용되지 않은 원본 경로입니다.")
    if not os.path.isfile(full_path):
        raise ReviewError(f"원본 파일을 찾을 수 없습니다: {normalized}", HTTPStatus.NOT_FOUND)
    return full_path, normalized


def locate_source_unit(vault_dir, tree, source_id, entry):
    filepath, source_rel_path = resolve_source_path(vault_dir, entry.get("source_path"))
    _log_name, units = parse_markdown_into_units(filepath, tree)

    marker_matches = []
    for index, unit in enumerate(units):
        markers = SOURCE_ID_RE.finditer(unit.content)
        if any(marker.group(1).casefold() == source_id.casefold() for marker in markers):
            marker_matches.append((index, unit))
    if len(marker_matches) == 1:
        index, unit = marker_matches[0]
        return filepath, source_rel_path, units, index, unit
    if len(marker_matches) > 1:
        raise ReviewError("동일한 Source ID marker가 원본에 중복되어 있습니다.", HTTPStatus.CONFLICT)

    expected_anchor = entry.get("source_anchor", "")
    anchor_matches = [
        (index, unit)
        for index, unit in enumerate(units)
        if make_source_anchor(source_rel_path, unit) == expected_anchor
    ]
    if len(anchor_matches) == 1:
        index, unit = anchor_matches[0]
        return filepath, source_rel_path, units, index, unit

    expected_heading_path = tuple(
        normalize_name(value) for value in entry.get("source_heading_path", [])
    )
    expected_heading = normalize_name(entry.get("source_heading", ""))
    fallback_matches = []
    for index, unit in enumerate(units):
        heading_path = tuple(normalize_name(value) for value in unit.heading_path)
        if heading_path == expected_heading_path and normalize_name(unit.title) == expected_heading:
            fallback_matches.append((index, unit))
    if len(fallback_matches) == 1:
        index, unit = fallback_matches[0]
        return filepath, source_rel_path, units, index, unit

    raise ReviewError(
        "Source ID에 해당하는 원본 구간을 하나로 확정할 수 없습니다. 분류를 다시 실행하세요.",
        HTTPStatus.CONFLICT,
    )


def classify_review_kind(entry):
    reasons = entry.get("review_reasons", [])
    if not entry.get("primary_category"):
        return "missing-level-1"
    if any(
        "Unknown manual category" in reason
        or "conflicts with heading category" in reason
        for reason in reasons
    ):
        return "invalid-manual"
    if any("Stopped at parent category" in reason for reason in reasons):
        return "parent-category"
    return "other"


def clean_source_preview(content):
    cleaned = SOURCE_ID_RE.sub("", content)
    return MERGE_ABOVE_RE.sub("", cleaned).strip()


def build_review_items(vault_dir=VAULT_DIR, metadata_path=METADATA_PATH, rules_path=RULES_PATH):
    metadata, tree = load_review_context(vault_dir, metadata_path, rules_path)
    entries = metadata.get("entries", {})
    if not isinstance(entries, dict):
        raise ReviewError("분류 metadata의 entries 형식이 올바르지 않습니다.", HTTPStatus.CONFLICT)

    items = []
    for source_id, entry in entries.items():
        if not isinstance(entry, dict) or not entry.get("needs_review"):
            continue
        try:
            _filepath, source_rel_path, _units, _index, unit = locate_source_unit(
                vault_dir, tree, source_id, entry
            )
            fingerprint = source_unit_fingerprint(unit)
            current_categories = [
                value.get("path", [])
                for value in entry.get("matched_categories", [])
                if isinstance(value, dict) and value.get("path")
            ]
            has_manual_category = bool(list(iter_active_category_lines(unit.content)))
            can_merge_above = bool(
                unit.lines
                and HEADING_RE.match(unit.lines[0])
                and any(not is_document_preamble(u) for u in _units[:_index])
            )
            items.append(
                {
                    "source_id": source_id,
                    "source_path": source_rel_path,
                    "source_log": entry.get("source_log", ""),
                    "source_heading": entry.get("source_heading", unit.title),
                    "source_heading_path": entry.get("source_heading_path", []),
                    "source_line": unit.start_line,
                    "source_fingerprint": fingerprint,
                    "metadata_stale": fingerprint != entry.get("source_fingerprint"),
                    "primary_category": entry.get("primary_category", []),
                    "current_categories": current_categories,
                    "has_manual_category": has_manual_category,
                    "can_merge_above": can_merge_above,
                    "review_reasons": entry.get("review_reasons", []),
                    "review_kind": classify_review_kind(entry),
                    "content": clean_source_preview(unit.content),
                    "generated_paths": entry.get("generated_paths", []),
                }
            )
        except ReviewError as exc:
            items.append(
                {
                    "source_id": source_id,
                    "source_path": entry.get("source_path", ""),
                    "source_log": entry.get("source_log", ""),
                    "source_heading": entry.get("source_heading", ""),
                    "source_heading_path": entry.get("source_heading_path", []),
                    "source_line": entry.get("source_line", 0),
                    "source_fingerprint": entry.get("source_fingerprint", ""),
                    "metadata_stale": True,
                    "primary_category": entry.get("primary_category", []),
                    "current_categories": [],
                    "has_manual_category": False,
                    "can_merge_above": False,
                    "review_reasons": entry.get("review_reasons", []) + [exc.message],
                    "review_kind": "source-error",
                    "content": "",
                    "generated_paths": entry.get("generated_paths", []),
                }
            )
    return sorted(
        items,
        key=lambda item: (
            item["source_path"].casefold(),
            item["source_line"],
            item["source_id"],
        ),
    )


def build_category_list(tree):
    categories = []
    for path, node in sorted(
        tree.nodes.items(),
        key=lambda value: tuple(part.casefold() for part in value[0]),
    ):
        categories.append(
            {
                "path": list(path),
                "label": path[-1],
                "depth": len(path),
                "selectable": True,
                "has_children": tree.has_children(path),
            }
        )
    return categories


def validate_category_paths(tree, raw_paths):
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ReviewError("하나 이상의 분류 경로를 선택하세요.")
    canonical_paths = []
    seen = set()
    for raw_path in raw_paths:
        if not isinstance(raw_path, list) or not 1 <= len(raw_path) <= CATEGORY_LEVELS:
            raise ReviewError("분류 경로 형식이 올바르지 않습니다.")
        if any(not isinstance(value, str) or not value.strip() for value in raw_path):
            raise ReviewError("분류 경로에 빈 단계가 있습니다.")
        resolved = tree.resolve_manual_path([value.strip() for value in raw_path])
        node = tree.nodes.get(resolved) if resolved else None
        if not resolved or not node:
            raise ReviewError(f"Classification_Rules.md에 없는 경로입니다: {' > '.join(raw_path)}")
        if resolved not in seen:
            canonical_paths.append(resolved)
            seen.add(resolved)
    return canonical_paths


def find_existing_category_lines(lines, start_index, end_index):
    unit_slice = "\n".join(lines[start_index:end_index])
    return [start_index + idx for idx, _match in iter_active_category_lines(unit_slice)]


def find_existing_category_line(lines, start_index, end_index):
    indices = find_existing_category_lines(lines, start_index, end_index)
    return indices[0] if indices else None


def atomic_write_text(path, content):
    _atomic_write_text(path, content)


def _update_entry_manual_heading_path(metadata, entry, metadata_path, heading_path):
    if not isinstance(entry, dict) or not metadata_path or not os.path.exists(metadata_path):
        return
    if heading_path is None:
        if "manual_heading_path" not in entry:
            return
        entry.pop("manual_heading_path", None)
    else:
        if entry.get("manual_heading_path") == list(heading_path):
            return
        entry["manual_heading_path"] = list(heading_path)
    try:
        atomic_write_json(metadata_path, metadata)
    except OSError:
        pass


def apply_manual_categories(
    source_id,
    raw_category_paths,
    expected_fingerprint,
    vault_dir=VAULT_DIR,
    metadata_path=METADATA_PATH,
    rules_path=RULES_PATH,
    backup_dir=BACKUP_DIR,
):
    if not isinstance(source_id, str) or not SOURCE_ID_VALUE_RE.fullmatch(source_id):
        raise ReviewError("Source ID 형식이 올바르지 않습니다.")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise ReviewError("원본 fingerprint가 없습니다. 화면을 새로 고치세요.")

    metadata, tree = load_review_context(vault_dir, metadata_path, rules_path)
    entry = metadata.get("entries", {}).get(source_id)
    if not isinstance(entry, dict):
        raise ReviewError("Source ID가 최신 metadata에 없습니다.", HTTPStatus.NOT_FOUND)
    canonical_paths = validate_category_paths(tree, raw_category_paths)
    filepath, source_rel_path, units, unit_index, unit = locate_source_unit(
        vault_dir, tree, source_id, entry
    )
    current_fingerprint = source_unit_fingerprint(unit)
    if current_fingerprint != expected_fingerprint:
        raise ReviewError(
            "원본 일지가 화면을 연 뒤 변경되었습니다. 새로 고친 후 다시 적용하세요.",
            HTTPStatus.CONFLICT,
        )

    with open(filesystem_path(filepath), "r", encoding="utf-8", newline="") as file_obj:
        original = file_obj.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()
    start_index = unit.start_line - 1
    end_index = units[unit_index + 1].start_line - 1 if unit_index + 1 < len(units) else len(lines)
    category_line = "Category: " + ", ".join("/".join(path) for path in canonical_paths)
    existing_indices = find_existing_category_lines(lines, start_index, end_index)

    frontmatter_end = None
    if start_index == 0 and lines and lines[0].strip() == "---":
        for index in range(1, end_index):
            if lines[index].strip() == "---":
                frontmatter_end = index
                break
        if frontmatter_end is not None and not existing_indices:
            for index in range(1, frontmatter_end):
                if CATEGORY_LINE_RE.match(lines[index].strip()):
                    existing_indices = [index]
                    break

    if existing_indices:
        lines[existing_indices[0]] = category_line
        for dup_index in reversed(existing_indices[1:]):
            del lines[dup_index]
    else:
        insert_index = start_index
        if frontmatter_end is not None:
            insert_index = 1
        elif 0 <= start_index < len(lines) and HEADING_RE.match(lines[start_index]):
            insert_index += 1
        while insert_index < end_index and SOURCE_ID_RE.fullmatch(lines[insert_index].strip()):
            insert_index += 1
        lines.insert(insert_index, category_line)

    _update_entry_manual_heading_path(metadata, entry, metadata_path, unit.heading_path)
    updated = newline.join(lines)
    if had_final_newline:
        updated += newline
    if updated == original:
        return {"changed": False, "backup_path": None, "source_path": source_rel_path}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(backup_dir, timestamp, *source_rel_path.split("/"))
    os.makedirs(filesystem_path(os.path.dirname(backup_path)), exist_ok=True)
    shutil.copy2(filesystem_path(filepath), filesystem_path(backup_path))
    atomic_write_text(filepath, updated)
    retention = resolve_backup_retention_limit(script_dir=SCRIPT_DIR)
    if retention > 0:
        prune_backup_batches(backup_dir, retention)
    return {
        "changed": True,
        "backup_path": normalize_rel_path(os.path.relpath(backup_path, vault_dir)),
        "source_path": source_rel_path,
    }


def remove_manual_categories(
    source_id,
    expected_fingerprint,
    vault_dir=VAULT_DIR,
    metadata_path=METADATA_PATH,
    rules_path=RULES_PATH,
    backup_dir=BACKUP_DIR,
):
    if not isinstance(source_id, str) or not SOURCE_ID_VALUE_RE.fullmatch(source_id):
        raise ReviewError("Source ID 형식이 올바르지 않습니다.")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise ReviewError("원본 fingerprint가 없습니다. 화면을 새로 고치세요.")

    metadata, tree = load_review_context(vault_dir, metadata_path, rules_path)
    entry = metadata.get("entries", {}).get(source_id)
    if not isinstance(entry, dict):
        raise ReviewError("Source ID가 최신 metadata에 없습니다.", HTTPStatus.NOT_FOUND)
    filepath, source_rel_path, units, unit_index, unit = locate_source_unit(
        vault_dir, tree, source_id, entry
    )
    current_fingerprint = source_unit_fingerprint(unit)
    if current_fingerprint != expected_fingerprint:
        raise ReviewError(
            "원본 일지가 화면을 연 뒤 변경되었습니다. 새로 고친 후 다시 적용하세요.",
            HTTPStatus.CONFLICT,
        )

    with open(filesystem_path(filepath), "r", encoding="utf-8", newline="") as file_obj:
        original = file_obj.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()
    start_index = unit.start_line - 1
    end_index = units[unit_index + 1].start_line - 1 if unit_index + 1 < len(units) else len(lines)
    existing_indices = find_existing_category_lines(lines, start_index, end_index)
    for index in reversed(existing_indices):
        del lines[index]

    _update_entry_manual_heading_path(metadata, entry, metadata_path, None)
    updated = newline.join(lines)
    if had_final_newline:
        updated += newline
    if updated == original:
        return {"changed": False, "backup_path": None, "source_path": source_rel_path}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(backup_dir, timestamp, *source_rel_path.split("/"))
    os.makedirs(filesystem_path(os.path.dirname(backup_path)), exist_ok=True)
    shutil.copy2(filesystem_path(filepath), filesystem_path(backup_path))
    atomic_write_text(filepath, updated)
    retention = resolve_backup_retention_limit(script_dir=SCRIPT_DIR)
    if retention > 0:
        prune_backup_batches(backup_dir, retention)
    return {
        "changed": True,
        "backup_path": normalize_rel_path(os.path.relpath(backup_path, vault_dir)),
        "source_path": source_rel_path,
    }


def merge_unit_into_previous(
    source_id,
    expected_fingerprint,
    vault_dir=VAULT_DIR,
    metadata_path=METADATA_PATH,
    rules_path=RULES_PATH,
    backup_dir=BACKUP_DIR,
):
    if not isinstance(source_id, str) or not SOURCE_ID_VALUE_RE.fullmatch(source_id):
        raise ReviewError("Source ID 형식이 올바르지 않습니다.")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise ReviewError("원본 fingerprint가 없습니다. 화면을 새로 고치세요.")

    metadata, tree = load_review_context(vault_dir, metadata_path, rules_path)
    entry = metadata.get("entries", {}).get(source_id)
    if not isinstance(entry, dict):
        raise ReviewError("Source ID가 최신 metadata에 없습니다.", HTTPStatus.NOT_FOUND)
    filepath, source_rel_path, units, unit_index, unit = locate_source_unit(
        vault_dir, tree, source_id, entry
    )
    current_fingerprint = source_unit_fingerprint(unit)
    if current_fingerprint != expected_fingerprint:
        raise ReviewError(
            "원본 일지가 화면을 연 뒤 변경되었습니다. 새로 고친 후 다시 적용하세요.",
            HTTPStatus.CONFLICT,
        )

    with open(filesystem_path(filepath), "r", encoding="utf-8", newline="") as file_obj:
        original = file_obj.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()
    start_index = unit.start_line - 1
    end_index = units[unit_index + 1].start_line - 1 if unit_index + 1 < len(units) else len(lines)

    has_preceding = any(not is_document_preamble(u) for u in units[:unit_index])
    if not has_preceding or not (0 <= start_index < len(lines) and HEADING_RE.match(lines[start_index])):
        raise ReviewError("합칠 수 있는 상위/이전 구간이 없습니다.", HTTPStatus.CONFLICT)

    cat_indices = set(find_existing_category_lines(lines, start_index, end_index))
    cleaned_slice = []
    for offset, (raw_line, in_code) in enumerate(
        source_lines_with_code_context("\n".join(lines[start_index:end_index]))
    ):
        abs_idx = start_index + offset
        stripped = raw_line.strip()
        if not in_code and (
            abs_idx in cat_indices
            or SOURCE_ID_RE.fullmatch(stripped)
            or MERGE_ABOVE_RE.fullmatch(stripped)
        ):
            continue
        cleaned_slice.append(raw_line)
        if not in_code and HEADING_RE.match(raw_line):
            cleaned_slice.append(f"<!-- {MERGE_ABOVE_MARKER_NAME} -->")

    lines[start_index:end_index] = cleaned_slice
    updated = newline.join(lines)
    if had_final_newline:
        updated += newline
    if updated == original:
        return {"changed": False, "backup_path": None, "source_path": source_rel_path}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(backup_dir, timestamp, *source_rel_path.split("/"))
    os.makedirs(filesystem_path(os.path.dirname(backup_path)), exist_ok=True)
    shutil.copy2(filesystem_path(filepath), filesystem_path(backup_path))
    atomic_write_text(filepath, updated)
    retention = resolve_backup_retention_limit(script_dir=SCRIPT_DIR)
    if retention > 0:
        prune_backup_batches(backup_dir, retention)
    return {
        "changed": True,
        "backup_path": normalize_rel_path(os.path.relpath(backup_path, vault_dir)),
        "source_path": source_rel_path,
    }


def add_classification_rule(
    raw_path,
    keywords="",
    vault_dir=VAULT_DIR,
    rules_path=RULES_PATH,
    backup_dir=BACKUP_DIR,
):
    if isinstance(raw_path, str):
        parts = [value.strip() for value in re.split(r"[/>]", raw_path) if value.strip()]
    elif isinstance(raw_path, list):
        if any(not isinstance(value, str) or not value.strip() for value in raw_path):
            raise ReviewError("분류 경로에 빈 단계가 있습니다.")
        parts = [value.strip() for value in raw_path]
    else:
        raise ReviewError("분류 경로 형식이 올바르지 않습니다.")

    if not 1 <= len(parts) <= CATEGORY_LEVELS:
        raise ReviewError("분류 경로 형식이 올바르지 않습니다.")
    raw_keywords = str(keywords or "").strip()
    if any("|" in part or "\n" in part or "\r" in part for part in parts) or (
        "|" in raw_keywords or "\n" in raw_keywords or "\r" in raw_keywords
    ):
        raise ReviewError("분류 이름과 키워드에는 '|' 문자를 사용할 수 없습니다.")

    tree = parse_rules_from_markdown(rules_path)
    if tree.errors:
        raise ReviewError(
            "Classification_Rules.md에 오류가 있습니다.",
            HTTPStatus.CONFLICT,
            {"errors": tree.errors},
        )

    canonical = []
    current = ()
    for part in parts:
        matched = tree.match_child(current, part) if current is not None else None
        if matched:
            canonical.append(matched[-1])
            current = matched
        else:
            canonical.append(part)
            current = None
    canonical_path = tuple(canonical)
    existing_node = tree.nodes.get(canonical_path)
    if existing_node and existing_node.explicit:
        raise ReviewError(
            f"이미 Classification_Rules.md에 존재하는 경로입니다: {' > '.join(canonical_path)}",
            HTTPStatus.CONFLICT,
        )

    with open(filesystem_path(rules_path), "r", encoding="utf-8", newline="") as file_obj:
        original = file_obj.read()
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()

    inherited = [""] * CATEGORY_LEVELS
    table_rows = []
    for line_index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped.startswith("|"):
            continue
        cells = split_markdown_table_row(stripped)
        if len(cells) < CATEGORY_LEVELS:
            continue
        if is_table_divider(cells) or is_category_header(cells):
            continue
        for col_index, cell in enumerate(cells[:CATEGORY_LEVELS]):
            if cell:
                inherited[col_index] = cell
                for child_col in range(col_index + 1, CATEGORY_LEVELS):
                    inherited[child_col] = ""
        populated = [col_index for col_index, val in enumerate(inherited) if val]
        if not populated:
            continue
        row_path = tuple(inherited[: max(populated) + 1])
        table_rows.append((line_index, row_path))

    if not table_rows:
        raise ReviewError(
            "Classification_Rules.md에서 규칙 표를 찾을 수 없습니다.",
            HTTPStatus.CONFLICT,
        )

    best_common_len = 0
    insert_after_line = table_rows[-1][0]
    for line_index, row_path in table_rows:
        common_len = 0
        for a, b in zip(row_path, canonical_path):
            if normalize_name(a) == normalize_name(b):
                common_len += 1
            else:
                break
        if common_len > 0 and common_len >= best_common_len:
            best_common_len = common_len
            insert_after_line = line_index

    keyword_clean = ", ".join(
        item.strip() for item in raw_keywords.split(",") if item.strip()
    )
    row_cells = [
        canonical_path[idx] if idx < len(canonical_path) else ""
        for idx in range(CATEGORY_LEVELS)
    ]
    new_row_line = f"| {' | '.join(row_cells)} | {keyword_clean} |"
    lines.insert(insert_after_line + 1, new_row_line)

    updated = newline.join(lines)
    if had_final_newline:
        updated += newline

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(backup_dir, timestamp, "Classification_Rules.md")
    os.makedirs(filesystem_path(os.path.dirname(backup_path)), exist_ok=True)
    shutil.copy2(filesystem_path(rules_path), filesystem_path(backup_path))
    atomic_write_text(rules_path, updated)
    retention = resolve_backup_retention_limit(script_dir=SCRIPT_DIR)
    if retention > 0:
        prune_backup_batches(backup_dir, retention)
    return {
        "changed": True,
        "path": list(canonical_path),
        "backup_path": normalize_rel_path(os.path.relpath(backup_path, vault_dir)),
    }


def run_production_classifier(vault_dir=VAULT_DIR, lock_held_by_parent=False):
    command = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "hierarchical_classifier.py"),
        "--production",
        "--output-dir",
        "Subject",
        "--review-dir",
        "Topic_Reviews",
        "--metadata-file",
        "organizer_metadata.json",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=vault_dir,
            env=delegated_lock_environment() if lock_held_by_parent else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "returncode": None, "output": str(exc)}
    output = "\n".join(value.strip() for value in (result.stdout, result.stderr) if value.strip())
    return {"ok": result.returncode == 0, "returncode": result.returncode, "output": output[-8000:]}


def is_local_origin(origin, allow_empty=True):
    if not origin:
        return allow_empty
    parsed = urllib.parse.urlparse(origin)
    return (parsed.hostname or "").casefold() in {"127.0.0.1", "localhost", "::1"}


def is_local_host(host_header):
    if not host_header or not isinstance(host_header, str):
        return False
    value = host_header.strip()
    if not value or any(ch in value for ch in ("/", "\\", "@", " ")):
        return False
    try:
        parsed = urllib.parse.urlsplit("//" + value)
    except ValueError:
        return False
    hostname = (parsed.hostname or "").casefold()
    return hostname in ALLOWED_LOCAL_HOSTS


class ClassificationReviewHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    vault_dir = VAULT_DIR
    metadata_path = METADATA_PATH
    rules_path = RULES_PATH
    static_dir = STATIC_DIR

    def log_message(self, format_string, *args):
        print(f"[Dashboard] {format_string % args}")

    def send_json(self, value, status=HTTPStatus.OK):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, error):
        self.send_json(
            {"status": "error", "message": localize_message(error.message), **error.details},
            error.status,
        )

    def send_static(self, filename, content_type):
        path = os.path.join(self.static_dir, filename)
        try:
            with open(path, "rb") as file_obj:
                payload = file_obj.read()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload)

    def read_json_payload(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ReviewError("요청 크기가 올바르지 않습니다.", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ReviewError("JSON 요청만 허용됩니다.", HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ReviewError("요청 본문 형식이 올바르지 않습니다.")
        return payload

    def validate_dashboard_session_id(self, session_id):
        if not isinstance(session_id, str) or not DASHBOARD_SESSION_ID_RE.fullmatch(session_id):
            raise ReviewError("대시보드 세션 형식이 올바르지 않습니다.")
        return session_id

    def dashboard_session_id(self, payload):
        return self.validate_dashboard_session_id(payload.get("session_id"))

    def csrf_token(self):
        return getattr(self.server, "csrf_token", DASHBOARD_CSRF_TOKEN)

    def validate_local_request(self, require_post_origin_or_token=False):
        if not is_local_host(self.headers.get("Host")):
            raise ReviewError("허용되지 않은 요청 호스트입니다.", HTTPStatus.FORBIDDEN)
        sec_fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().casefold()
        if sec_fetch_site and sec_fetch_site not in {"same-origin", "none"}:
            raise ReviewError("허용되지 않은 요청 출처입니다.", HTTPStatus.FORBIDDEN)
        origin = self.headers.get("Origin")
        if origin and not is_local_origin(origin, allow_empty=False):
            raise ReviewError("허용되지 않은 요청 출처입니다.", HTTPStatus.FORBIDDEN)
        if require_post_origin_or_token:
            token = self.headers.get("X-Log2Topic-Token", "")
            has_valid_token = bool(token) and secrets.compare_digest(token, self.csrf_token())
            has_valid_origin = is_local_origin(origin, allow_empty=False)
            if not (has_valid_origin or has_valid_token):
                raise ReviewError("허용되지 않은 요청 출처입니다.", HTTPStatus.FORBIDDEN)

    def serve_dashboard_session(self, session_id):
        connection_id = f"{session_id}:{id(self)}"
        self.server.dashboard_lifecycle.open(connection_id)
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            while True:
                self.wfile.write(b": dashboard-connected\n\n")
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.dashboard_lifecycle.close(connection_id)
            self.close_connection = True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            self.validate_local_request(require_post_origin_or_token=False)
            if path in {"/", "/index.html"}:
                self.send_static("index.html", "text/html; charset=utf-8")
            elif path == "/dashboard.css":
                self.send_static("dashboard.css", "text/css; charset=utf-8")
            elif path == "/dashboard.js":
                self.send_static("dashboard.js", "text/javascript; charset=utf-8")
            elif path == "/api/review-items":
                items = build_review_items(self.vault_dir, self.metadata_path, self.rules_path)
                self.send_json({"items": items, "count": len(items)})
            elif path == "/api/categories":
                _metadata, tree = load_review_context(
                    self.vault_dir, self.metadata_path, self.rules_path
                )
                self.send_json({"categories": build_category_list(tree)})
            elif path == "/api/locale":
                self.send_json({"language": resolve_ui_language(), "csrf_token": self.csrf_token()})
            elif path == "/api/session/watch":
                values = urllib.parse.parse_qs(parsed.query).get("session_id", [])
                session_id = self.validate_dashboard_session_id(values[0] if len(values) == 1 else None)
                self.serve_dashboard_session(session_id)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ReviewError as exc:
            self.send_error_json(exc)
        except Exception as exc:
            self.send_error_json(
                ReviewError(f"서버 오류가 발생했습니다: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            )

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path not in {"/api/classify", "/api/rules/add", "/api/session/open", "/api/session/close"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            self.validate_local_request(require_post_origin_or_token=True)
            payload = self.read_json_payload()
            if path == "/api/session/open":
                session_id = self.dashboard_session_id(payload)
                self.server.dashboard_lifecycle.open(session_id)
                self.send_json({"status": "success"})
                return
            if path == "/api/session/close":
                session_id = self.dashboard_session_id(payload)
                closed = self.server.dashboard_lifecycle.close(session_id)
                self.send_json({"status": "success", "closed": closed})
                return
            if not CLASSIFICATION_LOCK.acquire(blocking=False):
                raise ReviewError("다른 분류 작업이 진행 중입니다.", HTTPStatus.CONFLICT)
            try:
                try:
                    with VaultProcessLock(
                        self.vault_dir,
                        "classification-review",
                        command=command_text(__file__, ["dashboard-save"]),
                    ):
                        if path == "/api/rules/add":
                            edit_result = add_classification_rule(
                                payload.get("path"),
                                payload.get("keywords", ""),
                                self.vault_dir,
                                self.rules_path,
                            )
                        elif payload.get("merge_above"):
                            edit_result = merge_unit_into_previous(
                                payload.get("source_id"),
                                payload.get("source_fingerprint"),
                                self.vault_dir,
                                self.metadata_path,
                                self.rules_path,
                            )
                        elif payload.get("clear_manual"):
                            edit_result = remove_manual_categories(
                                payload.get("source_id"),
                                payload.get("source_fingerprint"),
                                self.vault_dir,
                                self.metadata_path,
                                self.rules_path,
                            )
                        else:
                            edit_result = apply_manual_categories(
                                payload.get("source_id"),
                                payload.get("category_paths"),
                                payload.get("source_fingerprint"),
                                self.vault_dir,
                                self.metadata_path,
                                self.rules_path,
                            )
                        rebuild = run_production_classifier(
                            self.vault_dir,
                            lock_held_by_parent=True,
                        )
                except ProcessLockUnavailable as exc:
                    raise ReviewError(
                        str(exc),
                        HTTPStatus.CONFLICT,
                        {"lock_owner": exc.owner},
                    ) from exc
            finally:
                CLASSIFICATION_LOCK.release()
            if not rebuild["ok"]:
                err_msg = (
                    "분류 규칙은 저장했지만 계층형 결과 재생성에 실패했습니다."
                    if path == "/api/rules/add"
                    else "원본 분류는 저장했지만 계층형 결과 재생성에 실패했습니다."
                )
                self.send_json(
                    {
                        "status": "error",
                        "saved": True,
                        "regenerated": False,
                        "message": localize_message(err_msg),
                        "details": rebuild["output"],
                        **edit_result,
                    },
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            remaining = build_review_items(self.vault_dir, self.metadata_path, self.rules_path)
            ok_msg = (
                "새 분류 규칙을 추가하고 계층형 결과를 갱신했습니다."
                if path == "/api/rules/add"
                else "구간을 이전 구간에 병합하고 계층형 결과를 갱신했습니다."
                if payload.get("merge_above")
                else "원본 분류와 계층형 결과를 갱신했습니다."
            )
            self.send_json(
                {
                    "status": "success",
                    "saved": True,
                    "regenerated": True,
                    "message": localize_message(ok_msg),
                    "remaining": len(remaining),
                    **edit_result,
                }
            )
        except ReviewError as exc:
            self.send_error_json(exc)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error_json(ReviewError("JSON 요청을 해석할 수 없습니다."))
        except Exception as exc:
            self.send_error_json(
                ReviewError(f"분류 적용 중 오류가 발생했습니다: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
            )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Open the local hierarchical classification review dashboard.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--nopause", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    args = parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("Error: port must be between 1 and 65535.")
        return 2

    print("Refreshing hierarchical classification metadata...")
    initial = run_production_classifier(VAULT_DIR)
    if not initial["ok"]:
        print(initial["output"])
        print("Error: Could not refresh hierarchical classification metadata.")
        return 1

    address = ("127.0.0.1", args.port)
    try:
        server = ThreadingHTTPServer(address, ClassificationReviewHandler)
    except OSError as exc:
        print(f"Error: Could not start dashboard on http://127.0.0.1:{args.port}: {exc}")
        return 1

    lifecycle = DashboardLifecycle(busy_check=CLASSIFICATION_LOCK.locked)
    lifecycle.attach(server)
    server.dashboard_lifecycle = lifecycle

    url = f"http://127.0.0.1:{args.port}"
    print(f"Classification review dashboard: {url}")
    print("Close every dashboard browser tab to stop automatically.")
    print("Press Ctrl+C to stop manually.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"Warning: Could not open the browser automatically: {exc}")
    try:
        with server:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        lifecycle.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
