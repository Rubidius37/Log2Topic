import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from atomic_io import StateFileError, atomic_write_json, load_json_state
from sync_contracts import normalize_sync_key_part


NOTION_SYNC_STATE_FILENAME = "notion_sync_state.json"
NOTION_RENDER_VERSION = "2026-06-30-nested-list-v1"


@dataclass
class SyncFailure:
    stage: str
    path: str
    error: str


@dataclass
class SyncStageResult:
    stage: str
    expected: int
    succeeded: int = 0
    failures: list = field(default_factory=list)
    unresolved_links: list = field(default_factory=list)
    sync_keys: list = field(default_factory=list)

    @property
    def complete(self):
        return (
            self.succeeded == self.expected
            and not self.failures
            and not self.unresolved_links
        )


def load_notion_sync_state(script_dir, filename=NOTION_SYNC_STATE_FILENAME):
    state_filepath = os.path.join(script_dir, filename)
    state = load_json_state(
        state_filepath,
        missing_default={"pages": {}},
        expected_type=dict,
        label="Notion sync state",
    )
    if not isinstance(state.get("pages"), dict):
        raise StateFileError(
            f"Invalid Notion sync state {state_filepath}: 'pages' must be an object."
        )
    return state


def normalize_notion_page_id(page_id):
    value = str(page_id or "").strip()
    compact = value.replace("-", "")
    if re.fullmatch(r"[0-9a-fA-F]{32}", compact):
        return compact.casefold()
    return value.casefold()


def extract_notion_page_id_from_url(url):
    matches = re.findall(r"[0-9a-fA-F]{32}", str(url or ""))
    if not matches:
        return ""
    return normalize_notion_page_id(matches[-1])


def get_state_page_id_candidates(state_entry):
    if not isinstance(state_entry, dict):
        return []

    candidates = []
    direct_id = normalize_notion_page_id(state_entry.get("page_id"))
    if direct_id:
        candidates.append((direct_id, "sync state page_id"))
    url_id = extract_notion_page_id_from_url(state_entry.get("url"))
    if url_id and all(existing_id != url_id for existing_id, _reason in candidates):
        candidates.append((url_id, "sync state URL"))
    return candidates


def backfill_sync_state_page_ids(sync_state):
    if not isinstance(sync_state, dict):
        return 0
    pages = sync_state.get("pages", {})
    if not isinstance(pages, dict):
        return 0

    backfilled = 0
    for entry in pages.values():
        if not isinstance(entry, dict) or entry.get("page_id"):
            continue
        page_id = extract_notion_page_id_from_url(entry.get("url"))
        if page_id:
            entry["page_id"] = page_id
            backfilled += 1
    return backfilled


def save_notion_sync_state(script_dir, state, filename=NOTION_SYNC_STATE_FILENAME):
    state_filepath = os.path.join(script_dir, filename)
    atomic_write_json(state_filepath, state)


def add_cached_url_fallback(sync_state, sync_key, relative_path, url_map):
    if not isinstance(sync_state, dict) or not isinstance(url_map, dict):
        return False
    state_pages = sync_state.get("pages", {})
    if not isinstance(state_pages, dict):
        return False
    entry = state_pages.get(sync_key, {})
    cached_url = entry.get("url", "") if isinstance(entry, dict) else ""
    if not cached_url:
        return False
    url_map[normalize_sync_key_part(relative_path)] = cached_url
    print(f"-> Using last known Notion URL for dependent links: {relative_path}")
    return True


def hash_sync_payload(sync_key, markdown_content, category_path=None):
    payload = {
        "render_version": NOTION_RENDER_VERSION,
        "sync_key": sync_key,
        "category_path": category_path or "",
        "markdown_content": markdown_content,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def is_sync_run_complete(stage_results):
    return bool(stage_results) and all(result.complete for result in stage_results)


def should_run_orphan_cleanup(skip_requested, stage_results):
    return not skip_requested and is_sync_run_complete(stage_results)


def save_sync_state_checkpoint(
    script_dir,
    sync_state,
    state_filename,
    stage_results,
    checkpoint,
):
    try:
        save_notion_sync_state(script_dir, sync_state, state_filename)
        return True
    except Exception as exc:
        state_path = os.path.join(script_dir, state_filename)
        message = f"Could not save Notion sync state after {checkpoint}: {exc}"
        print(f"Error: {message}")
        result = SyncStageResult(stage="Local state", expected=1)
        result.failures.append(SyncFailure("Local state", state_path, message))
        stage_results.append(result)
        return False


def finish_after_state_save_failure(script_dir, stage_results, cleanup_status):
    report_path = os.path.join(script_dir, "reports", "notion_sync_report.md")
    try:
        write_notion_sync_report(
            report_path,
            stage_results,
            cleanup_status,
            success=False,
        )
    except Exception as exc:
        print(f"Warning: Could not write Notion sync failure report: {exc}")
    print(
        "\n[PARTIAL FAILURE] Notion sync stopped because local state could not "
        "be saved. No later sync or cleanup stages were run."
    )
    return 1


def record_cloudinary_cleanup_failure(stage_results):
    result = SyncStageResult(stage="Cloudinary cleanup", expected=1)
    result.failures.append(
        SyncFailure(
            "Cloudinary cleanup",
            "cloudinary_cache.json",
            "Cloudinary cleanup or its local cache/report update failed.",
        )
    )
    stage_results.append(result)


def write_notion_sync_report(report_path, stage_results, cleanup_status, success):
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    lines = [
        "# Notion Sync Report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Result: {'success' if success else 'partial failure'}",
        f"- Orphan cleanup: {cleanup_status}",
        "",
        "## Stages",
        "",
    ]
    for result in stage_results:
        lines.append(
            f"- {result.stage}: {result.succeeded}/{result.expected} succeeded, "
            f"{len(result.failures)} failures, "
            f"{len(result.unresolved_links)} unresolved links"
        )

    failures = [failure for result in stage_results for failure in result.failures]
    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            lines.append(f"- `{failure.stage}` / `{failure.path}`: {failure.error}")
    else:
        lines.append("- None")

    unresolved = [item for result in stage_results for item in result.unresolved_links]
    lines.extend(["", "## Unresolved Managed Links", ""])
    if unresolved:
        seen = set()
        for item in unresolved:
            key = (item.get("source_path", ""), item.get("target", ""))
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- `{key[0]}` -> `{key[1]}`")
    else:
        lines.append("- None")

    with open(report_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines).rstrip() + "\n")
