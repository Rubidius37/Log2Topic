import os
import sys
import re
import json
import copy
import hashlib
import argparse
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

import notion_render
from image_assets import (
    ImageReferenceError,
    image_mime_type,
    resolve_local_image_path,
    validate_local_image_file,
)
from atomic_io import StateFileError, atomic_write_json, load_json_state
from notion_api import (
    NOTION_RETRY_NON_IDEMPOTENT,
    NOTION_RETRY_SAFE,
    NotionAmbiguousWriteError,
    append_block_chunks,
    append_notion_block_tree,
    archive_notion_page,
    build_notion_page_url,
    delete_notion_blocks,
    get_database_property_names,
    get_notion_block_children,
    get_top_level_block_ids,
    notion_api_request,
    notion_block_fits_single_request,
    query_page_by_property,
    query_pages_by_property,
    replace_page_content_in_place,
)
from notion_render import (
    build_managed_wikilink_targets,
    convert_wikilinks_to_notion_links,
    extract_generated_note_metadata,
    get_page_properties,
    has_notion_property,
    strip_internal_comments,
)
from notion_state import (
    NOTION_RENDER_VERSION,
    NOTION_SYNC_STATE_FILENAME,
    SyncFailure,
    SyncStageResult,
    add_cached_url_fallback,
    backfill_sync_state_page_ids,
    finish_after_state_save_failure,
    get_state_page_id_candidates,
    hash_sync_payload,
    is_sync_run_complete,
    load_notion_sync_state,
    normalize_notion_page_id,
    record_cloudinary_cleanup_failure,
    save_notion_sync_state,
    save_sync_state_checkpoint,
    should_run_orphan_cleanup,
    write_notion_sync_report,
)
from process_lock import (
    LOCK_BUSY_EXIT_CODE,
    ProcessLockUnavailable,
    VaultProcessLock,
    command_text,
    lock_is_delegated_by_parent,
    print_lock_error,
)
from sync_cleanup import (
    CanonicalPageSelection,
    OrphanCleanupPlan,
    assess_orphan_cleanup_safety,
    build_orphan_cleanup_plan,
    cleanup_orphan_pages,
    get_all_notion_sync_keys,
    notion_page_id,
    resolve_cloudinary_cleanup_mode,
    run_cloudinary_cleanup_after_sync,
    select_canonical_notion_page,
    write_orphan_cleanup_plan_report,
)
from sync_contracts import (
    NOTION_PROP_SOURCE_HEADING,
    NOTION_PROP_SOURCE_ID,
    NOTION_PROP_SYNC_KEY,
    normalize_sync_key_part,
)
from workspace_paths import resolve_workspace_dir, resolve_workspace_state_dir

REVIEW_DIR_NAME = "Topic_Reviews"
LEGACY_REVIEW_PREFIX = "_Generated/Timelines/"
NOTION_IMAGE_DELIVERY_CLOUDINARY_VERSION = "2026-08-16-cloudinary-strict-v1"
NOTION_IMAGE_DELIVERY_EXTERNAL_ONLY_VERSION = "2026-08-21-external-only-v1"
CLOUDINARY_ASSET_PENDING = "pending"
CLOUDINARY_ASSET_COMMITTED = "committed"
IMAGE_TOKEN_RE = re.compile(
    r"!\[\[([^\]]+)\]\]|!\[[^\]\n]*\]\(([^)\n]+)\)"
)
class CloudinaryUploadError(RuntimeError):
    """Raised when a configured Cloudinary image cannot be made available."""


_cloudinary_cache = None
_image_sha1_cache = {}

def load_cloudinary_cache(vault_dir):
    global _cloudinary_cache
    if _cloudinary_cache is not None:
        return _cloudinary_cache

    cache_filepath = os.path.join(
        resolve_workspace_state_dir(os.path.dirname(os.path.abspath(__file__)), vault_dir),
        "cloudinary_cache.json",
    )
    _cloudinary_cache = load_json_state(
        cache_filepath,
        missing_default={},
        expected_type=dict,
        label="Cloudinary cache",
    )
    return _cloudinary_cache

def save_cloudinary_cache(vault_dir, cache_data):
    cache_filepath = os.path.join(
        resolve_workspace_state_dir(os.path.dirname(os.path.abspath(__file__)), vault_dir),
        "cloudinary_cache.json",
    )
    try:
        atomic_write_json(cache_filepath, cache_data)
    except Exception as e:
        raise CloudinaryUploadError(
            f"Could not save Cloudinary cache {cache_filepath}: {e}"
        ) from e

def upload_to_cloudinary(filepath, cloud_name, upload_preset):
    """Uploads a local image to Cloudinary using unsigned upload preset (urllib only)."""
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    import uuid

    filename = os.path.basename(filepath)
    try:
        mime_type = image_mime_type(filepath)
    except ImageReferenceError as exc:
        raise CloudinaryUploadError(str(exc)) from exc

    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"

    try:
        with open(filepath, "rb") as f:
            file_data = f.read()
    except Exception as e:
        raise CloudinaryUploadError(
            f"Could not read image for Cloudinary upload: {filepath} ({e})"
        ) from e

    # Build multipart request body
    parts = []

    # upload_preset field
    parts.append(f"--{boundary}")
    parts.append('Content-Disposition: form-data; name="upload_preset"')
    parts.append('')
    parts.append(upload_preset)

    # file field
    parts.append(f"--{boundary}")
    parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"')
    parts.append(f'Content-Type: {mime_type}')
    parts.append('')

    body = b''
    for part in parts:
        body += part.encode('utf-8') + b'\r\n'
    body += file_data + b'\r\n'
    body += f"--{boundary}--\r\n".encode('utf-8')

    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body))
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            res_data = json.loads(res.read().decode("utf-8"))
            secure_url = res_data.get("secure_url")
            if not secure_url:
                raise CloudinaryUploadError(
                    f"Cloudinary upload returned no secure_url for {filename}."
                )
            print(f"Successfully uploaded {filename} to Cloudinary: {secure_url}")
            return {
                "url": secure_url,
                "public_id": res_data.get("public_id", ""),
                "uploaded_at": (
                    res_data.get("created_at")
                    or datetime.now().astimezone().isoformat(timespec="seconds")
                ),
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        raise CloudinaryUploadError(
            f"Cloudinary upload failed for {filename}: HTTP {e.code} - {error_body}"
        ) from e
    except CloudinaryUploadError:
        raise
    except Exception as e:
        raise CloudinaryUploadError(
            f"Cloudinary upload failed for {filename}: {e}"
        ) from e

def get_file_sha1(filepath):
    digest = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_cached_file_sha1(filepath):
    absolute_path = os.path.abspath(filepath)
    stat_result = os.stat(absolute_path)
    cache_key = (
        os.path.normcase(absolute_path),
        stat_result.st_size,
        stat_result.st_mtime_ns,
    )
    cached = _image_sha1_cache.get(cache_key)
    if cached:
        return cached

    normalized_path = cache_key[0]
    stale_keys = [
        key for key in _image_sha1_cache
        if key[0] == normalized_path and key != cache_key
    ]
    for key in stale_keys:
        _image_sha1_cache.pop(key, None)

    file_sha1 = get_file_sha1(absolute_path)
    _image_sha1_cache[cache_key] = file_sha1
    return file_sha1


def get_or_upload_cloudinary_image(filepath, cloudinary_config, vault_dir):
    try:
        filepath = validate_local_image_file(filepath, vault_dir)
    except ImageReferenceError as exc:
        raise CloudinaryUploadError(str(exc)) from exc

    cache = load_cloudinary_cache(vault_dir)
    filename = os.path.basename(filepath)
    filename_lower = filename.lower()
    try:
        file_sha1 = get_cached_file_sha1(filepath)
    except Exception as e:
        print(f"Warning: Failed to hash image {filepath}: {e}")
        file_sha1 = ""
    content_key = f"sha1:{file_sha1}" if file_sha1 else ""

    # 1. Cache hit
    if content_key and content_key in cache:
        cached = cache[content_key]
        if isinstance(cached, dict):
            return cached.get("url")
        return cached

    legacy_cached = cache.get(filename_lower)
    if legacy_cached:
        if isinstance(legacy_cached, dict):
            if not file_sha1 or legacy_cached.get("sha1") == file_sha1:
                return legacy_cached.get("url")
        else:
            if content_key:
                cache[content_key] = {
                    "url": legacy_cached,
                    "sha1": file_sha1,
                    "filename": filename
                }
                try:
                    save_cloudinary_cache(vault_dir, cache)
                except Exception:
                    cache.pop(content_key, None)
                    raise
            return legacy_cached

    # 2. Cache miss -> Upload to Cloudinary
    cloud_name = cloudinary_config.get("cloud_name")
    upload_preset = cloudinary_config.get("upload_preset")
    if not cloud_name or not upload_preset:
        raise CloudinaryUploadError(
            "Cloudinary is enabled but CLOUDINARY_CLOUD_NAME or "
            "CLOUDINARY_UPLOAD_PRESET is missing."
        )

    upload_result = upload_to_cloudinary(filepath, cloud_name, upload_preset)
    if isinstance(upload_result, dict):
        uploaded_url = upload_result.get("url", "")
        public_id = upload_result.get("public_id", "")
        uploaded_at = upload_result.get("uploaded_at", "")
    else:
        uploaded_url = upload_result
        public_id = ""
        uploaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    if not uploaded_url:
        raise CloudinaryUploadError(
            f"Cloudinary upload returned no URL for {filename}."
        )

    missing = object()
    previous_filename_entry = cache.get(filename_lower, missing)
    previous_content_entry = cache.get(content_key, missing) if content_key else missing
    cache[filename_lower] = {
        "url": uploaded_url,
        "sha1": file_sha1,
        "filename": filename,
        "public_id": public_id,
        "uploaded_at": uploaded_at,
        "status": CLOUDINARY_ASSET_PENDING,
    }
    if content_key:
        cache[content_key] = {
            "url": uploaded_url,
            "sha1": file_sha1,
            "filename": filename,
            "public_id": public_id,
            "uploaded_at": uploaded_at,
            "status": CLOUDINARY_ASSET_PENDING,
        }
    try:
        save_cloudinary_cache(vault_dir, cache)
    except Exception:
        if previous_filename_entry is missing:
            cache.pop(filename_lower, None)
        else:
            cache[filename_lower] = previous_filename_entry
        if content_key:
            if previous_content_entry is missing:
                cache.pop(content_key, None)
            else:
                cache[content_key] = previous_content_entry
        raise
    return uploaded_url


def mark_cloudinary_manifest_committed(vault_dir, image_asset_manifest):
    sha1s = {
        record.get("sha1")
        for record in image_asset_manifest
        if record.get("status") == "ok" and record.get("sha1")
    }
    if not sha1s:
        return 0

    cache = load_cloudinary_cache(vault_dir)
    original_cache = copy.deepcopy(cache)
    committed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    changed = 0
    for key, value in cache.items():
        if not isinstance(value, dict):
            continue
        entry_sha1 = value.get("sha1", "")
        if key.startswith("sha1:"):
            entry_sha1 = key.split(":", 1)[1]
        if entry_sha1 not in sha1s:
            continue
        if value.get("status", CLOUDINARY_ASSET_COMMITTED) != CLOUDINARY_ASSET_PENDING:
            continue
        value["status"] = CLOUDINARY_ASSET_COMMITTED
        value["committed_at"] = committed_at
        value.pop("stale_since", None)
        value.pop("unused_full_sync_count", None)
        changed += 1

    if not changed:
        return 0
    try:
        save_cloudinary_cache(vault_dir, cache)
    except Exception:
        cache.clear()
        cache.update(original_cache)
        raise
    return changed

def load_env(filepath):
    """Loads environment variables from a .env file if it exists."""
    if os.path.exists(filepath):
        print(f"Loading environment variables from {filepath}...")
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip()
    else:
        print(f"Warning: env file '{filepath}' not found.")

def get_required_env(key):
    """Retrieves an environment variable or exits if not found."""
    val = os.environ.get(key)
    if not val or val.startswith("your_") or val == "secret_xxxxxxxxxxxxxxx" or val == "xxxxxxxxxxxxxxxx":
        print(f"Error: Environment variable '{key}' is not set correctly in .env file.")
        sys.exit(1)
    return val

def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync Log2Topic Markdown documents to Notion."
    )
    parser.add_argument(
        "daily_paths",
        nargs="*",
        help="Daily_Logs markdown files to sync in fast daily-only mode.",
    )
    parser.add_argument(
        "--daily-only",
        action="store_true",
        help="Sync only selected original Daily_Logs notes, then skip generated notes and cleanup.",
    )
    parser.add_argument(
        "--classification-failed",
        action="store_true",
        help="Fallback after classification failure: sync all original notes, skip cleanup, and report partial failure.",
    )
    parser.add_argument(
        "--daily",
        nargs="+",
        metavar="PATH",
        help="Daily_Logs markdown files to sync.",
    )
    parser.add_argument(
        "--recent-daily",
        type=int,
        metavar="N",
        help="Sync the N most recently modified Daily_Logs markdown files.",
    )
    parser.add_argument(
        "--cloudinary-cleanup",
        choices=["off", "report", "auto", "delete"],
        help=(
            "Run Cloudinary cleanup after sync. Full sync defaults to auto cleanup "
            "for old uncommitted uploads; daily-only defaults to off. Legacy delete "
            "mode is restricted to the same pending-only policy."
        ),
    )
    parser.add_argument(
        "--cloudinary-cleanup-delete",
        action="store_true",
        help="Legacy shortcut; now restricted to delayed pending-upload cleanup.",
    )
    parser.add_argument(
        "--cloudinary-cleanup-limit",
        type=int,
        default=0,
        help="Further limit pending Cloudinary assets auto-deleted after sync.",
    )
    parser.add_argument(
        "--cloudinary-cleanup-invalidate",
        action="store_true",
        help="Ask Cloudinary to invalidate CDN cache for deleted assets.",
    )
    parser.add_argument(
        "--metadata-file",
        default="organizer_metadata.json",
        help="Organizer metadata filename under scripts/.",
    )
    parser.add_argument(
        "--subject-dir",
        default="Subject",
        help="Generated subject root represented by the selected metadata.",
    )
    parser.add_argument(
        "--review-dir",
        default=REVIEW_DIR_NAME,
        help="Generated review root represented by the selected metadata.",
    )
    parser.add_argument(
        "--sync-state-file",
        default=NOTION_SYNC_STATE_FILENAME,
        help="Notion incremental sync state filename under scripts/.",
    )
    parser.add_argument(
        "--skip-orphan-cleanup",
        action="store_true",
        help="Keep existing Notion pages after a migration preview sync.",
    )
    parser.add_argument(
        "--allow-large-cleanup",
        action="store_true",
        help=(
            "Allow orphan cleanup when no active Sync Keys remain or when at least "
            "10 pages and 20 percent of the database would be archived."
        ),
    )
    parser.add_argument("--nopause", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()

def collect_daily_logs(vault_dir):
    daily_logs_dir = os.path.join(vault_dir, "Daily_Logs")
    original_logs = []
    if os.path.exists(daily_logs_dir):
        for root, dirs, files in os.walk(daily_logs_dir):
            dirs.sort()
            for file in sorted(files):
                if file.lower().endswith(".md"):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, vault_dir)
                    original_logs.append(normalize_sync_key_part(rel_path))
    return original_logs

def normalize_daily_log_arg(vault_dir, raw_path):
    cleaned_path = raw_path.strip().strip('"').strip("'")
    if not cleaned_path:
        raise ValueError("Empty daily note path was provided.")

    candidates = []
    if os.path.isabs(cleaned_path):
        candidates.append(cleaned_path)
    else:
        candidates.append(os.path.join(vault_dir, cleaned_path))
        normalized = normalize_sync_key_part(cleaned_path)
        if not normalized.lower().startswith("daily_logs/"):
            candidates.append(os.path.join(vault_dir, "Daily_Logs", cleaned_path))

    chosen_path = next((path for path in candidates if os.path.isfile(path)), candidates[0])
    abs_vault_dir = os.path.abspath(vault_dir)
    abs_path = os.path.abspath(chosen_path)
    try:
        is_inside_vault = os.path.commonpath([abs_vault_dir, abs_path]) == abs_vault_dir
    except ValueError:
        is_inside_vault = False

    if not is_inside_vault:
        raise ValueError(f"Daily note path is outside this vault: {raw_path}")

    rel_path = normalize_sync_key_part(os.path.relpath(abs_path, abs_vault_dir))
    if not rel_path.lower().startswith("daily_logs/"):
        raise ValueError(f"Daily-only sync accepts files under Daily_Logs only: {raw_path}")
    if not rel_path.lower().endswith(".md"):
        raise ValueError(f"Daily-only sync accepts Markdown files only: {raw_path}")
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Daily note was not found: {raw_path}")
    return rel_path

def select_original_logs(vault_dir, args):
    daily_only_mode = bool(
        args.daily_only or args.daily_paths or args.daily or args.recent_daily is not None
    )
    all_logs = collect_daily_logs(vault_dir)
    if getattr(args, "classification_failed", False):
        if not all_logs:
            raise FileNotFoundError("No Daily_Logs markdown files were found.")
        return all_logs, True
    if not daily_only_mode:
        return all_logs, False

    if not all_logs:
        raise FileNotFoundError("No Daily_Logs markdown files were found.")

    selected_logs = []
    requested_paths = []
    if args.daily:
        requested_paths.extend(args.daily)
    requested_paths.extend(args.daily_paths)

    for raw_path in requested_paths:
        selected_logs.append(normalize_daily_log_arg(vault_dir, raw_path))

    recent_count = args.recent_daily
    if recent_count is None and args.daily_only and not selected_logs:
        recent_count = 1
    if recent_count is not None:
        if recent_count < 1:
            raise ValueError("--recent-daily must be 1 or greater.")
        recent_logs = sorted(
            all_logs,
            key=lambda rel_path: os.path.getmtime(os.path.join(vault_dir, rel_path)),
            reverse=True,
        )[:recent_count]
        selected_logs.extend(recent_logs)

    if not selected_logs:
        raise ValueError("No Daily_Logs markdown files were selected for daily-only sync.")

    seen = set()
    unique_logs = []
    for rel_path in selected_logs:
        normalized = normalize_sync_key_part(rel_path)
        if normalized not in seen:
            seen.add(normalized)
            unique_logs.append(normalized)
    return unique_logs, True

def extract_generated_paths_from_metadata(metadata):
    if isinstance(metadata, list):
        return metadata

    if not isinstance(metadata, dict):
        return []

    entries = metadata.get("entries", {})
    paths = []
    if isinstance(entries, dict):
        for entry in entries.values():
            if isinstance(entry, dict):
                paths.extend(entry.get("generated_paths", []))

    paths.extend(metadata.get("generated_paths", []))
    seen = set()
    unique_paths = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(path)
    return unique_paths

def extract_timeline_paths_from_metadata(metadata, vault_dir, review_dir=REVIEW_DIR_NAME):
    paths = []
    if isinstance(metadata, dict):
        paths.extend(metadata.get("timeline_paths", []))
        paths.extend(metadata.get("review_paths", []))

    if not paths:
        for timeline_root in (
            os.path.join(vault_dir, review_dir),
            os.path.join(vault_dir, "_Generated", "Timelines"),
        ):
            if os.path.exists(timeline_root):
                for root, dirs, files in os.walk(timeline_root):
                    for filename in files:
                        if filename.endswith(".md"):
                            full_path = os.path.join(root, filename)
                            paths.append(os.path.relpath(full_path, vault_dir))

    seen = set()
    unique_paths = []
    for path in paths:
        normalized = path.replace("\\", "/")
        if normalized not in seen:
            seen.add(normalized)
            unique_paths.append(normalized)
    return unique_paths

def map_generated_paths_to_source_ids(metadata):
    if not isinstance(metadata, dict):
        return {}

    entries = metadata.get("entries", {})
    if not isinstance(entries, dict):
        return {}

    path_to_source_id = {}
    for source_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        for path in entry.get("generated_paths", []):
            path_to_source_id[normalize_sync_key_part(path)] = source_id
    return path_to_source_id

def is_external_image_reference(image_ref):
    parsed = urllib.parse.urlparse(str(image_ref or "").strip())
    return parsed.scheme.casefold() in {"http", "https"}


def extract_local_image_references(markdown_text):
    references = []
    for match in IMAGE_TOKEN_RE.finditer(markdown_text):
        image_ref = (match.group(1) or match.group(2) or "").strip()
        if image_ref and not is_external_image_reference(image_ref):
            references.append(image_ref)
    return references


def build_image_asset_manifest(markdown_text, vault_dir):
    manifest_by_key = {}
    for image_ref in extract_local_image_references(markdown_text):
        try:
            local_path = resolve_local_image_path(image_ref, vault_dir)
        except ImageReferenceError as exc:
            raise CloudinaryUploadError(str(exc)) from exc
        if not local_path:
            record = {
                "reference": image_ref.replace("\\", "/"),
                "status": "missing",
            }
        else:
            try:
                file_sha1 = get_cached_file_sha1(local_path)
                relative_path = os.path.relpath(local_path, vault_dir)
                record = {
                    "reference": image_ref.replace("\\", "/"),
                    "path": relative_path.replace("\\", "/"),
                    "sha1": file_sha1,
                    "status": "ok",
                }
            except Exception as exc:
                print(f"Warning: Failed to fingerprint image {local_path}: {exc}")
                record = {
                    "reference": image_ref.replace("\\", "/"),
                    "status": "hash-error",
                }
        manifest_key = json.dumps(record, ensure_ascii=False, sort_keys=True)
        manifest_by_key[manifest_key] = record

    return [manifest_by_key[key] for key in sorted(manifest_by_key)]


def hash_image_asset_manifest(manifest):
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def create_image_block(img_filename, image_base_url, vault_dir=None, cloudinary_config=None):
    external_url = str(img_filename or "").strip()
    if is_external_image_reference(external_url):
        return {
            "object": "block",
            "type": "image",
            "image": {
                "type": "external",
                "external": {"url": external_url},
            },
        }

    try:
        img_local_path = resolve_local_image_path(img_filename, vault_dir)
    except ImageReferenceError as exc:
        raise CloudinaryUploadError(str(exc)) from exc

    if cloudinary_config:
        if not vault_dir:
            raise CloudinaryUploadError(
                f"Cannot resolve Cloudinary image without a vault path: {img_filename}"
            )
        if not img_local_path:
            raise CloudinaryUploadError(
                f"Local image file was not found for Cloudinary upload: {img_filename}"
            )
        img_url = get_or_upload_cloudinary_image(img_local_path, cloudinary_config, vault_dir)
        if not img_url:
            raise CloudinaryUploadError(
                f"Cloudinary upload returned no URL for {img_filename}."
            )
    else:
        raise CloudinaryUploadError(
            "Local images require Cloudinary for Notion synchronization. "
            f"Configure CLOUDINARY_CLOUD_NAME and CLOUDINARY_UPLOAD_PRESET: {img_filename}"
        )

    return {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {
                "url": img_url
            }
        }
    }


def markdown_to_notion_blocks(
    markdown_text,
    image_base_url=None,
    vault_dir=None,
    cloudinary_config=None,
):
    return notion_render.markdown_to_notion_blocks(
        markdown_text,
        image_base_url=image_base_url,
        vault_dir=vault_dir,
        cloudinary_config=cloudinary_config,
        image_block_factory=create_image_block,
    )

def extract_subject_category_path(relative_path, subject_dir="Subject"):
    normalized_path = normalize_sync_key_part(relative_path)
    path_parts = [p for p in normalized_path.split("/") if p]
    subject_idx = -1
    for idx, part in enumerate(path_parts):
        if part.casefold() == subject_dir.casefold():
            subject_idx = idx
            break
    if subject_idx == -1:
        return ""
    return "/".join(path_parts[subject_idx + 1:-1])

def build_sync_key(
    relative_path,
    note_metadata=None,
    page_kind=None,
    category_path=None,
    subject_dir="Subject",
):
    note_metadata = note_metadata or {}
    normalized_path = normalize_sync_key_part(relative_path)

    if page_kind == "timeline":
        return f"timeline::{normalize_sync_key_part(category_path or normalized_path)}"

    if normalized_path.lower().startswith("daily_logs/"):
        return f"daily::{normalized_path}"

    source_id = note_metadata.get("source_id")
    if source_id:
        subject_category_path = extract_subject_category_path(normalized_path, subject_dir)
        if subject_category_path:
            return f"subject::{source_id}::{subject_category_path}"
        return f"subject::{source_id}"

    return f"file::{normalized_path}"

def extract_timeline_category_path(relative_path, review_dir=REVIEW_DIR_NAME):
    normalized_path = normalize_sync_key_part(relative_path)
    prefixes = (f"{review_dir}/", LEGACY_REVIEW_PREFIX)
    timeline_rel_path = ""
    for prefix in prefixes:
        if normalized_path.startswith(prefix):
            timeline_rel_path = normalized_path[len(prefix):]
            break
    if not timeline_rel_path:
        return ""
    return os.path.dirname(timeline_rel_path).replace("\\", "/")


def sort_timeline_files_deepest_first(timeline_files, review_dir=REVIEW_DIR_NAME):
    def sort_key(relative_path):
        category_path = extract_timeline_category_path(relative_path, review_dir)
        depth = len([part for part in category_path.split("/") if part])
        return (-depth, normalize_sync_key_part(relative_path))

    return sorted(timeline_files, key=sort_key)

def query_existing_page(token, database_id, sync_key, state_entry=None):
    """Searches for an existing page by Sync Key."""
    pages = query_pages_by_property(
        token,
        database_id,
        NOTION_PROP_SYNC_KEY,
        sync_key,
    )
    selection = select_canonical_notion_page(pages, state_entry=state_entry)
    if selection.conflict:
        raise RuntimeError(
            f"Could not determine the canonical Notion page for {sync_key}: "
            f"{selection.conflict}"
        )
    if len(pages) > 1 and selection.page:
        print(
            f"-> Selected canonical page {notion_page_id(selection.page)} for "
            f"duplicate Sync Key ({selection.reason})."
        )
    return selection.page


def create_or_update_notion_page(
    token,
    database_id,
    filepath,
    relative_path,
    image_base_url=None,
    url_map=None,
    vault_dir=None,
    cloudinary_config=None,
    available_properties=None,
    sync_key=None,
    page_kind=None,
    category_path=None,
    sync_state=None,
    managed_link_targets=None,
    unresolved_links=None,
):
    """Upserts a local markdown file into the Notion database."""
    print(f"Syncing: {relative_path}...")

    if not os.path.exists(filepath):
        print(f"Error: Local file {filepath} not found. Skipping.")
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        markdown_content = f.read()
    markdown_content = strip_internal_comments(markdown_content)
    note_metadata = extract_generated_note_metadata(markdown_content)

    # Resolve managed local Markdown links and legacy wiki-links to Notion pages.
    normalized_rel_path = relative_path.replace("\\", "/")
    page_unresolved_links = []
    if url_map is not None and "daily_logs" not in normalized_rel_path.lower():
        markdown_content = convert_wikilinks_to_notion_links(
            markdown_content,
            url_map,
            managed_targets=managed_link_targets,
            unresolved_targets=page_unresolved_links,
            source_path=relative_path,
        )
    page_unresolved_links = sorted(set(page_unresolved_links))
    if unresolved_links is not None:
        unresolved_links.extend(
            {"source_path": relative_path, "target": target}
            for target in page_unresolved_links
        )

    if not sync_key:
        sync_key = build_sync_key(
            relative_path,
            note_metadata=note_metadata,
            page_kind=page_kind,
            category_path=category_path,
        )
    if not has_notion_property(available_properties, NOTION_PROP_SYNC_KEY):
        raise RuntimeError("Notion database is missing required rich_text property: Sync Key")

    content_hash = hash_sync_payload(sync_key, markdown_content, category_path=category_path)
    state_pages = sync_state.setdefault("pages", {}) if isinstance(sync_state, dict) else {}
    state_entry = state_pages.get(sync_key, {}) if isinstance(state_pages, dict) else {}
    if not isinstance(state_entry, dict):
        state_entry = {}
    cached_url = state_entry.get("url") if isinstance(state_entry, dict) else ""
    image_asset_manifest = build_image_asset_manifest(markdown_content, vault_dir)
    asset_hash = hash_image_asset_manifest(image_asset_manifest)
    stored_asset_hash = state_entry.get("asset_hash")
    stored_image_delivery_version = state_entry.get("image_delivery_version")
    image_delivery_version = (
        NOTION_IMAGE_DELIVERY_CLOUDINARY_VERSION
        if cloudinary_config
        else NOTION_IMAGE_DELIVERY_EXTERNAL_ONLY_VERSION
    )
    content_unchanged = state_entry.get("content_hash") == content_hash
    if content_unchanged and cached_url:
        if not image_asset_manifest and not stored_asset_hash:
            state_entry["asset_hash"] = asset_hash
            stored_asset_hash = asset_hash
        image_delivery_current = (
            not image_asset_manifest
            or stored_image_delivery_version == image_delivery_version
        )
        if stored_asset_hash == asset_hash and image_delivery_current:
            if cloudinary_config:
                mark_cloudinary_manifest_committed(vault_dir, image_asset_manifest)
            print(f"-> No content or image changes for {relative_path}. Skipping Notion update.")
            return cached_url
        if stored_asset_hash:
            if stored_asset_hash != asset_hash:
                print(f"-> Referenced image content changed for {relative_path}. Updating page...")
            else:
                print(f"-> Revalidating image delivery for {relative_path}. Updating page...")
        else:
            print(f"-> Establishing image fingerprint for {relative_path}. Updating page...")

    blocks = markdown_to_notion_blocks(markdown_content, image_base_url=image_base_url, vault_dir=vault_dir, cloudinary_config=cloudinary_config)
    block_chunks = [blocks[i:i + 100] for i in range(0, len(blocks), 100)]

    existing_page = query_existing_page(
        token,
        database_id,
        sync_key,
        state_entry=state_entry,
    )
    properties = get_page_properties(
        filepath,
        relative_path,
        sync_key,
        note_metadata=note_metadata,
        available_properties=available_properties,
        category_path=category_path,
    )

    final_page_url = None

    if existing_page:
        page_id = existing_page["id"]
        final_page_url = (
            existing_page.get("url")
            or cached_url
            or build_notion_page_url(page_id)
        )
        print(
            f"-> Existing page found by Sync Key (ID: {page_id}). "
            "Updating content in place..."
        )
        replace_page_content_in_place(
            token,
            page_id,
            properties,
            block_chunks,
        )
        print(f"-> Successfully updated {relative_path} (ID preserved: {page_id})")
    else:
        # INSERT
        print("-> No existing page found. Creating new page...")
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        res = notion_api_request(
            url,
            token,
            method="POST",
            data=payload,
            retry_mode=NOTION_RETRY_NON_IDEMPOTENT,
            operation_name=f"create page for Sync Key {sync_key}",
        )
        new_page_id = res["id"]
        final_page_url = res.get("url") or build_notion_page_url(new_page_id)

        appended_ids = []
        try:
            append_block_chunks(token, new_page_id, block_chunks, appended_ids)
        except Exception as exc:
            rollback_failures = delete_notion_blocks(token, appended_ids)
            rollback_note = (
                f" Rollback failures: {'; '.join(rollback_failures)}"
                if rollback_failures
                else ""
            )
            raise RuntimeError(
                f"Created page {new_page_id}, but failed to upload its content: "
                f"{exc}.{rollback_note} The same Sync Key will repair this page "
                "on the next run."
            ) from exc
        print(f"-> Successfully created {relative_path} (ID: {new_page_id})")

    if cloudinary_config:
        mark_cloudinary_manifest_committed(vault_dir, image_asset_manifest)

    if isinstance(sync_state, dict) and final_page_url:
        sync_state.setdefault("pages", {})[sync_key] = {
            "url": final_page_url,
            "page_id": page_id if existing_page else new_page_id,
            "content_hash": content_hash,
            "asset_hash": asset_hash,
            "image_delivery_version": image_delivery_version,
            "relative_path": relative_path.replace("\\", "/"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "unresolved_links": page_unresolved_links,
        }

    return final_page_url

def sync_category_timelines(
    token,
    database_id,
    timeline_files,
    vault_dir,
    image_base_url=None,
    cloudinary_config=None,
    url_map=None,
    available_properties=None,
    sync_state=None,
    review_dir=REVIEW_DIR_NAME,
    managed_link_targets=None,
):
    """Upserts generated local timeline index files for each leaf category."""
    print("\nSyncing local Category Timeline files...")
    result = SyncStageResult(stage="Review", expected=len(timeline_files))

    for rel_path in sort_timeline_files_deepest_first(timeline_files, review_dir):
        category_path = extract_timeline_category_path(rel_path, review_dir)
        if not category_path:
            print(f"Warning: Could not infer timeline category from {rel_path}. Skipping.")
            result.failures.append(
                SyncFailure("Review", rel_path, "Could not infer review category path.")
            )
            continue

        print(f"\nProcessing timeline for: {category_path}")
        filepath = os.path.join(vault_dir, rel_path)
        sync_key = build_sync_key(rel_path, page_kind="timeline", category_path=category_path)
        result.sync_keys.append(sync_key)

        try:
            page_url = create_or_update_notion_page(
                token,
                database_id,
                filepath,
                rel_path,
                image_base_url=image_base_url,
                url_map=url_map,
                vault_dir=vault_dir,
                cloudinary_config=cloudinary_config,
                available_properties=available_properties,
                sync_key=sync_key,
                page_kind="timeline",
                category_path=category_path,
                sync_state=sync_state,
                managed_link_targets=managed_link_targets,
                unresolved_links=result.unresolved_links,
            )
            if page_url:
                result.succeeded += 1
                if isinstance(url_map, dict):
                    url_map[normalize_sync_key_part(rel_path)] = page_url
            else:
                result.failures.append(
                    SyncFailure("Review", rel_path, "No Notion page URL was returned.")
                )
                add_cached_url_fallback(
                    sync_state, sync_key, rel_path, url_map
                )
        except Exception as e:
            print(f"Error: Failed to sync timeline for {category_path}: {e}")
            result.failures.append(SyncFailure("Review", rel_path, str(e)))
            add_cached_url_fallback(sync_state, sync_key, rel_path, url_map)

    return result

def _main_unlocked():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    load_env(os.path.join(script_dir, ".env"))

    token = get_required_env("NOTION_TOKEN")

    database_id = os.environ.get("NOTION_DATABASE_ID")

    if not database_id or database_id.startswith("your_") or database_id == "xxxxxxxxxxxxxxxx":
        print("Error: Notion Database ID is not set. Please configure NOTION_DATABASE_ID in .env.")
        sys.exit(1)

    vault_dir = resolve_workspace_dir(script_dir)
    metadata_filepath = os.path.join(script_dir, args.metadata_file)
    try:
        sync_state = load_notion_sync_state(script_dir, args.sync_state_file)
    except StateFileError as exc:
        print(f"Error: {exc}")
        print(
            "The existing state file was not replaced. Restore it before syncing, "
            "or move it aside only when intentionally rebuilding sync state."
        )
        return 1
    backfilled_page_ids = backfill_sync_state_page_ids(sync_state)
    if backfilled_page_ids:
        print(
            f"Recovered {backfilled_page_ids} Notion Page IDs from cached page URLs."
        )

    # Print masked database ID for safety
    masked_db_id = database_id
    if len(database_id) > 12:
        masked_db_id = f"{database_id[:6]}...{database_id[-6:]}"
    print(f"Notion Database ID: {masked_db_id}")
    print("Reading Notion database schema...")
    available_properties = get_database_property_names(token, database_id)
    if NOTION_PROP_SYNC_KEY not in available_properties:
        print("Error: Notion database is missing required rich_text property: Sync Key")
        sys.exit(1)
    missing_source_properties = [
        prop for prop in [NOTION_PROP_SOURCE_ID, NOTION_PROP_SOURCE_HEADING]
        if prop not in available_properties
    ]
    if missing_source_properties:
        print(
            "Warning: Optional Notion source tracking is not fully enabled. "
            f"Missing rich_text properties: {', '.join(missing_source_properties)}"
        )

    try:
        original_logs, daily_only_mode = select_original_logs(vault_dir, args)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    if daily_only_mode:
        if args.classification_failed:
            print("Classification failed. Syncing ALL original daily notes only; all cleanup is disabled.")
        else:
            print("Fast daily-only sync mode enabled.")
        print("Subject notes, Topic_Reviews, and orphan cleanup will be skipped.")
        local_files = []
        timeline_files = []
        path_to_source_id = {}
    else:
        print(f"Reading local metadata from {metadata_filepath}...")

        if not os.path.exists(metadata_filepath):
            print(f"Error: {metadata_filepath} does not exist. Run the local update first.")
            sys.exit(1)

        try:
            metadata = load_json_state(
                metadata_filepath,
                missing_default={},
                expected_type=dict,
                label="classification metadata",
            )
            if "entries" in metadata and not isinstance(metadata["entries"], dict):
                raise StateFileError(
                    f"Invalid classification metadata {metadata_filepath}: "
                    "'entries' must be an object."
                )
        except StateFileError as exc:
            print(f"Error: {exc}")
            print("Notion pages and cleanup were left unchanged by this sync run.")
            return 1

        local_files = extract_generated_paths_from_metadata(metadata)
        timeline_files = extract_timeline_paths_from_metadata(
            metadata, vault_dir, args.review_dir
        )
        path_to_source_id = map_generated_paths_to_source_ids(metadata)

        print(f"Found {len(local_files)} files in metadata.")
        print(f"Found {len(timeline_files)} generated timeline files.")

    print(f"Selected {len(original_logs)} original logs in Daily_Logs.")

    # Load Cloudinary configuration from environment variables
    cloudinary_config = None
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    upload_preset = os.environ.get("CLOUDINARY_UPLOAD_PRESET")
    if cloud_name and upload_preset and not cloud_name.startswith("your_") and not upload_preset.startswith("your_"):
        cloudinary_config = {
            "cloud_name": cloud_name,
            "upload_preset": upload_preset
        }
        print(f"Cloudinary integration enabled. (Cloud Name: {cloud_name})")
    else:
        print(
            "Cloudinary not configured. Text-only pages and external HTTPS images "
            "can sync; pages with local images will fail without broken fallback URLs."
        )

    cloudinary_cleanup_mode = (
        "off" if args.classification_failed
        else resolve_cloudinary_cleanup_mode(args, daily_only_mode)
    )
    if cloudinary_config or cloudinary_cleanup_mode != "off":
        try:
            load_cloudinary_cache(vault_dir)
        except StateFileError as exc:
            print(f"Error: {exc}")
            print(
                "The existing Cloudinary cache was not replaced. Restore it before "
                "syncing to avoid duplicate image uploads or unsafe cache cleanup."
            )
            return 1

    image_base_url = None
    if cloudinary_config:
        print("Using Cloudinary for local Notion images.")

    url_map = {}
    stage_results = []
    if args.classification_failed:
        stage_results.append(SyncStageResult(
            stage="Classification",
            expected=1,
            failures=[SyncFailure(
                "Classification", "local update",
                "Local classification failed. Only original daily notes were selected; "
                "Subject, Review and all cleanup were skipped. See the local update log for the cause.",
            )],
        ))
    managed_link_targets = build_managed_wikilink_targets(
        list(original_logs) + list(local_files) + list(timeline_files)
    )

    # Pass 1: Sync Original logs first to capture their Notion Page URLs
    print("\n[Pass 1/2] Syncing Original Daily Logs...")
    daily_result = SyncStageResult(stage="Daily", expected=len(original_logs))
    for rel_path in original_logs:
        filepath = os.path.join(vault_dir, rel_path)
        sync_key = build_sync_key(rel_path)
        daily_result.sync_keys.append(sync_key)
        try:
            page_url = create_or_update_notion_page(
                token, database_id, filepath, rel_path,
                image_base_url=image_base_url, url_map=None,
                vault_dir=vault_dir, cloudinary_config=cloudinary_config,
                available_properties=available_properties,
                sync_key=sync_key,
                page_kind="Daily",
                sync_state=sync_state,
            )
            if page_url:
                url_map[rel_path] = page_url
                daily_result.succeeded += 1
            else:
                daily_result.failures.append(
                    SyncFailure("Daily", rel_path, "No Notion page URL was returned.")
                )
                add_cached_url_fallback(
                    sync_state, sync_key, rel_path, url_map
                )
        except Exception as e:
            print(f"Error: Failed to sync original log {rel_path}: {e}")
            daily_result.failures.append(SyncFailure("Daily", rel_path, str(e)))
            add_cached_url_fallback(sync_state, sync_key, rel_path, url_map)

    stage_results.append(daily_result)
    if not save_sync_state_checkpoint(
        script_dir,
        sync_state,
        args.sync_state_file,
        stage_results,
        "Daily sync",
    ):
        return finish_after_state_save_failure(
            script_dir,
            stage_results,
            "skipped because local sync state could not be saved",
        )
    print(
        f"Successfully synced {daily_result.succeeded}/{daily_result.expected} "
        f"original logs; {len(daily_result.failures)} failures."
    )

    if daily_only_mode:
        sync_complete = is_sync_run_complete(stage_results)
        cleanup_status = (
            "skipped because classification failed (Notion and Cloudinary)"
            if args.classification_failed else "not applicable (daily-only mode)"
        )
        cloudinary_cleanup_ok = args.classification_failed or run_cloudinary_cleanup_after_sync(
            args,
            script_dir,
            vault_dir,
            daily_only_mode=True,
            allow_delete=sync_complete,
        )
        if not cloudinary_cleanup_ok:
            record_cloudinary_cleanup_failure(stage_results)
        success = is_sync_run_complete(stage_results)
        write_notion_sync_report(
            os.path.join(script_dir, "reports", "notion_sync_report.md"),
            stage_results,
            cleanup_status,
            success,
        )
        if success:
            print("\n[SUCCESS] Daily-only Notion synchronization complete!")
            return 0
        print("\n[PARTIAL FAILURE] Daily-only sync completed with errors. See notion_sync_report.md.")
        return 1

    # Pass 2: Sync Split Subject Notes with Wiki-Link translation
    print("\n[Pass 2/2] Syncing Split Subject Notes...")
    subject_result = SyncStageResult(stage="Subject", expected=len(local_files))
    for rel_path in local_files:
        filepath = os.path.join(vault_dir, rel_path)
        normalized_rel_path = normalize_sync_key_part(rel_path)
        source_id = path_to_source_id.get(normalized_rel_path)
        category_path = extract_subject_category_path(rel_path, args.subject_dir)
        sync_key = build_sync_key(
            rel_path,
            note_metadata={"source_id": source_id} if source_id else {},
            category_path=category_path,
            subject_dir=args.subject_dir,
        )
        subject_result.sync_keys.append(sync_key)
        try:
            page_url = create_or_update_notion_page(
                token, database_id, filepath, rel_path,
                image_base_url=image_base_url, url_map=url_map,
                vault_dir=vault_dir, cloudinary_config=cloudinary_config,
                available_properties=available_properties,
                sync_key=sync_key,
                page_kind="Subject",
                category_path=category_path,
                sync_state=sync_state,
                managed_link_targets=managed_link_targets,
                unresolved_links=subject_result.unresolved_links,
            )
            if page_url:
                url_map[rel_path] = page_url
                subject_result.succeeded += 1
            else:
                subject_result.failures.append(
                    SyncFailure("Subject", rel_path, "No Notion page URL was returned.")
                )
                add_cached_url_fallback(
                    sync_state, sync_key, rel_path, url_map
                )
        except Exception as e:
            print(f"Error: Failed to sync subject note {rel_path}: {e}")
            subject_result.failures.append(SyncFailure("Subject", rel_path, str(e)))
            add_cached_url_fallback(sync_state, sync_key, rel_path, url_map)

    stage_results.append(subject_result)
    if not save_sync_state_checkpoint(
        script_dir,
        sync_state,
        args.sync_state_file,
        stage_results,
        "Subject sync",
    ):
        return finish_after_state_save_failure(
            script_dir,
            stage_results,
            "skipped because local sync state could not be saved",
        )
    print(
        f"Successfully synced {subject_result.succeeded}/{subject_result.expected} "
        f"subject notes; {len(subject_result.failures)} failures and "
        f"{len(subject_result.unresolved_links)} unresolved links."
    )

    # 2. Sync combined timelines for categories
    review_result = sync_category_timelines(
        token, database_id, timeline_files, vault_dir,
        image_base_url=image_base_url, cloudinary_config=cloudinary_config, url_map=url_map,
        available_properties=available_properties,
        sync_state=sync_state,
        review_dir=args.review_dir,
        managed_link_targets=managed_link_targets,
    )
    stage_results.append(review_result)
    if not save_sync_state_checkpoint(
        script_dir,
        sync_state,
        args.sync_state_file,
        stage_results,
        "Review sync",
    ):
        return finish_after_state_save_failure(
            script_dir,
            stage_results,
            "skipped because local sync state could not be saved",
        )

    active_sync_keys = [
        sync_key
        for result in stage_results
        for sync_key in result.sync_keys
    ]
    cleanup_status = "not run"

    # 3. Cleanup orphan pages in Notion
    cleanup_allowed = should_run_orphan_cleanup(
        args.skip_orphan_cleanup,
        stage_results,
    )
    if args.skip_orphan_cleanup:
        print("Skipping Notion orphan cleanup as requested.")
        cleanup_status = "skipped by option"
    elif not cleanup_allowed:
        print(
            "Skipping Notion orphan cleanup because one or more sync stages "
            "failed or contain unresolved managed links."
        )
        cleanup_status = "skipped because sync was incomplete"
    else:
        cleanup_result = SyncStageResult(stage="Orphan cleanup", expected=1)
        try:
            notion_pages_by_sync_key, pages_without_sync_key = get_all_notion_sync_keys(token, database_id)
            cleanup_plan = build_orphan_cleanup_plan(
                notion_pages_by_sync_key,
                active_sync_keys,
                pages_without_sync_key,
                sync_state=sync_state,
            )
            cleanup_safe, cleanup_guard_reason = assess_orphan_cleanup_safety(
                cleanup_plan,
                allow_large_cleanup=args.allow_large_cleanup,
            )
            cleanup_plan_report = os.path.join(
                script_dir,
                "reports",
                "notion_orphan_cleanup_plan.md",
            )
            if not cleanup_safe:
                cleanup_plan_status = "blocked by safety guard"
            elif args.allow_large_cleanup:
                cleanup_plan_status = "allowed by --allow-large-cleanup"
            else:
                cleanup_plan_status = "within automatic safety limits"
            write_orphan_cleanup_plan_report(
                cleanup_plan_report,
                cleanup_plan,
                cleanup_plan_status,
                cleanup_guard_reason,
            )

            if not cleanup_safe:
                if cleanup_plan.conflicts:
                    recovery_hint = (
                        "Resolve the Identity Conflicts in "
                        "scripts/reports/notion_orphan_cleanup_plan.md. "
                        "--allow-large-cleanup does not override identity conflicts."
                    )
                else:
                    recovery_hint = (
                        "Review scripts/reports/notion_orphan_cleanup_plan.md and "
                        "rerun with --allow-large-cleanup only if the removals are "
                        "intentional."
                    )
                message = (
                    f"{cleanup_guard_reason} No pages were archived. {recovery_hint}"
                )
                print(f"Error: {message}")
                cleanup_result.failures.append(
                    SyncFailure(
                        "Orphan cleanup",
                        "Notion database",
                        message,
                    )
                )
                cleanup_status = (
                    "blocked by safety guard; "
                    f"{cleanup_plan.candidate_count}/{cleanup_plan.existing_page_count} "
                    "pages were candidates"
                )
            else:
                cleanup_counts = cleanup_orphan_pages(
                    token,
                    database_id,
                    notion_pages_by_sync_key,
                    active_sync_keys,
                    pages_without_sync_key=pages_without_sync_key,
                    plan=cleanup_plan,
                )
                if cleanup_counts["failed"]:
                    cleanup_result.failures.append(
                        SyncFailure(
                            "Orphan cleanup",
                            "Notion database",
                            f"{cleanup_counts['failed']} page archive operations failed.",
                        )
                    )
                    cleanup_status = "completed with archive failures"
                else:
                    cleanup_result.succeeded = 1
                    cleanup_status = f"completed; archived {cleanup_counts['archived']} pages"
                    active_set = set(active_sync_keys)
                    state_pages = sync_state.get("pages", {})
                    if isinstance(state_pages, dict):
                        sync_state["pages"] = {
                            key: value
                            for key, value in state_pages.items()
                            if key in active_set
                        }
        except Exception as e:
            print(f"Error during cleanup process: {e}")
            cleanup_result.failures.append(
                SyncFailure("Orphan cleanup", "Notion database", str(e))
            )
            cleanup_status = "failed"
        stage_results.append(cleanup_result)

    if not save_sync_state_checkpoint(
        script_dir,
        sync_state,
        args.sync_state_file,
        stage_results,
        "orphan cleanup",
    ):
        return finish_after_state_save_failure(
            script_dir,
            stage_results,
            cleanup_status,
        )
    sync_complete = is_sync_run_complete(stage_results)
    cloudinary_cleanup_ok = run_cloudinary_cleanup_after_sync(
        args,
        script_dir,
        vault_dir,
        daily_only_mode=False,
        allow_delete=sync_complete,
    )
    if not cloudinary_cleanup_ok:
        record_cloudinary_cleanup_failure(stage_results)
    success = is_sync_run_complete(stage_results)
    write_notion_sync_report(
        os.path.join(script_dir, "reports", "notion_sync_report.md"),
        stage_results,
        cleanup_status,
        success,
    )
    if success:
        print("\n[SUCCESS] Notion synchronization complete!")
        return 0
    print("\n[PARTIAL FAILURE] Notion sync completed with errors. See notion_sync_report.md.")
    return 1


def main():
    if lock_is_delegated_by_parent():
        return _main_unlocked()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_dir = resolve_workspace_dir(script_dir)
    try:
        with VaultProcessLock(
            vault_dir,
            "notion-sync",
            command=command_text(__file__),
        ):
            return _main_unlocked()
    except ProcessLockUnavailable as exc:
        print_lock_error(exc)
        return LOCK_BUSY_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
