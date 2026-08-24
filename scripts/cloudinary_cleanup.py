import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from atomic_io import StateFileError, atomic_write_json, load_json_state
from image_assets import (
    IMAGE_EXTENSIONS,
    ImageReferenceError,
    normalize_image_reference,
    resolve_local_image_path,
)
from process_lock import (
    LOCK_BUSY_EXIT_CODE,
    ProcessLockUnavailable,
    VaultProcessLock,
    command_text,
    lock_is_delegated_by_parent,
    print_lock_error,
)


IMAGE_TOKEN_PATTERN = re.compile(r"!\[\[([^\]]+)\]\]|!\[[^\]\n]*\]\(([^)\n]+)\)")
CLOUDINARY_URL_PATTERN = re.compile(r"https://res\.cloudinary\.com/[^\s)>\]]+")
CLOUDINARY_ASSET_PENDING = "pending"
CLOUDINARY_ASSET_COMMITTED = "committed"


def load_env(filepath):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def get_file_sha1(filepath):
    digest = hashlib.sha1()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_markdown_files(vault_dir, roots):
    for root_name in roots:
        root_path = os.path.join(vault_dir, root_name)
        if not os.path.exists(root_path):
            continue
        for root, dirs, files in os.walk(root_path):
            dirs.sort()
            for filename in sorted(files):
                if filename.lower().endswith(".md"):
                    yield os.path.join(root, filename)


def scan_live_images(vault_dir, roots):
    live_sha1s = set()
    live_filenames = set()
    missing_filenames = set()
    live_cloudinary_urls = set()
    markdown_files = 0
    image_refs = 0
    missing_refs = []

    for filepath in iter_markdown_files(vault_dir, roots):
        markdown_files += 1
        try:
            with open(filepath, "r", encoding="utf-8") as file_obj:
                content = file_obj.read()
        except Exception as exc:
            print(f"Warning: Could not read {filepath}: {exc}")
            continue

        live_cloudinary_urls.update(match.group(0).rstrip(".,") for match in CLOUDINARY_URL_PATTERN.finditer(content))

        for match in IMAGE_TOKEN_PATTERN.finditer(content):
            image_refs += 1
            image_ref = (match.group(1) or match.group(2)).strip()
            if image_ref.startswith("http://") or image_ref.startswith("https://"):
                if "res.cloudinary.com" in image_ref:
                    live_cloudinary_urls.add(image_ref)
                continue

            try:
                normalized_ref = normalize_image_reference(image_ref)
                local_path = resolve_local_image_path(image_ref, vault_dir)
            except ImageReferenceError as exc:
                rel_md = os.path.relpath(filepath, vault_dir).replace("\\", "/")
                missing_refs.append(f"{rel_md}: blocked image reference ({exc})")
                continue

            basename = os.path.basename(normalized_ref).lower()
            if basename:
                live_filenames.add(basename)

            if local_path:
                try:
                    live_sha1s.add(get_file_sha1(local_path))
                except Exception as exc:
                    print(f"Warning: Could not hash {local_path}: {exc}")
            elif basename:
                missing_filenames.add(basename)
                rel_md = os.path.relpath(filepath, vault_dir).replace("\\", "/")
                missing_refs.append(f"{rel_md}: {image_ref}")

    return {
        "live_sha1s": live_sha1s,
        "live_filenames": live_filenames,
        "missing_filenames": missing_filenames,
        "live_cloudinary_urls": live_cloudinary_urls,
        "markdown_files": markdown_files,
        "image_refs": image_refs,
        "missing_refs": missing_refs,
    }


def load_cache(cache_path):
    return load_json_state(
        cache_path,
        missing_default={},
        expected_type=dict,
        label="Cloudinary cache",
    )


def save_cache(cache_path, cache):
    atomic_write_json(cache_path, cache)


def get_entry_url(value):
    if isinstance(value, dict):
        return value.get("url", "")
    if isinstance(value, str):
        return value
    return ""


def get_entry_sha1(key, value):
    if key.startswith("sha1:"):
        return key.split(":", 1)[1]
    if isinstance(value, dict):
        return value.get("sha1", "")
    return ""


def get_entry_filename(key, value):
    if isinstance(value, dict) and value.get("filename"):
        return os.path.basename(value["filename"]).lower()
    if not key.startswith("sha1:"):
        return os.path.basename(key).lower()
    return ""


def get_entry_status(value):
    if not isinstance(value, dict):
        return CLOUDINARY_ASSET_COMMITTED
    status = value.get("status")
    if status == CLOUDINARY_ASSET_PENDING:
        return CLOUDINARY_ASSET_PENDING
    return CLOUDINARY_ASSET_COMMITTED


def extract_public_id_from_url(url):
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    try:
        upload_index = parts.index("upload")
    except ValueError:
        return ""

    public_parts = parts[upload_index + 1:]
    while public_parts:
        first = public_parts[0]
        if re.fullmatch(r"v\d+", first):
            public_parts = public_parts[1:]
            break
        if "," in first or first.startswith(("c_", "w_", "h_", "q_", "f_", "e_")):
            public_parts = public_parts[1:]
            continue
        break

    if not public_parts:
        return ""

    public_id = "/".join(public_parts)
    stem, ext = os.path.splitext(public_id)
    if ext.lower() in IMAGE_EXTENSIONS:
        public_id = stem
    return public_id


def group_cache_entries(cache):
    groups = {}
    for key, value in cache.items():
        url = get_entry_url(value)
        if not url or "res.cloudinary.com" not in url:
            continue
        group = groups.setdefault(url, {
            "url": url,
            "keys": [],
            "sha1s": set(),
            "filenames": set(),
            "public_ids": set(),
            "statuses": set(),
            "uploaded_ats": set(),
            "stale_sinces": set(),
            "unused_full_sync_counts": [],
        })
        group["keys"].append(key)
        sha1 = get_entry_sha1(key, value)
        filename = get_entry_filename(key, value)
        public_id = value.get("public_id", "") if isinstance(value, dict) else ""
        public_id = public_id or extract_public_id_from_url(url)
        group["statuses"].add(get_entry_status(value))
        if isinstance(value, dict):
            if value.get("uploaded_at"):
                group["uploaded_ats"].add(value["uploaded_at"])
            if value.get("stale_since"):
                group["stale_sinces"].add(value["stale_since"])
            try:
                group["unused_full_sync_counts"].append(
                    int(value.get("unused_full_sync_count", 0))
                )
            except (TypeError, ValueError):
                group["unused_full_sync_counts"].append(0)
        if sha1:
            group["sha1s"].add(sha1)
        if filename:
            group["filenames"].add(filename)
        if public_id:
            group["public_ids"].add(public_id)
    return groups


def classify_groups(groups, live):
    stale = []
    used = []
    for group in groups.values():
        direct_url_live = group["url"] in live["live_cloudinary_urls"]
        sha_live = bool(group["sha1s"] & live["live_sha1s"])
        missing_filename_live = bool(group["filenames"] & live["missing_filenames"])
        filename_fallback_live = not group["sha1s"] and bool(group["filenames"] & live["live_filenames"])
        is_live = direct_url_live or sha_live or missing_filename_live or filename_fallback_live
        target = used if is_live else stale
        target.append(group)
    return used, stale


def is_pending_group(group):
    return group.get("statuses") == {CLOUDINARY_ASSET_PENDING}


def update_pending_lifecycle(cache, used, stale, now=None):
    now = now or datetime.now().astimezone()
    now_text = now.isoformat(timespec="seconds")
    changed = False

    for group in used:
        for key in group["keys"]:
            value = cache.get(key)
            if not isinstance(value, dict) or get_entry_status(value) != CLOUDINARY_ASSET_PENDING:
                continue
            if "stale_since" in value or "unused_full_sync_count" in value:
                value.pop("stale_since", None)
                value.pop("unused_full_sync_count", None)
                changed = True

    for group in stale:
        if not is_pending_group(group):
            continue
        existing_counts = group.get("unused_full_sync_counts") or [0]
        next_count = max(existing_counts) + 1
        stale_since = min(group.get("stale_sinces") or {now_text})
        for key in group["keys"]:
            value = cache.get(key)
            if not isinstance(value, dict) or get_entry_status(value) != CLOUDINARY_ASSET_PENDING:
                continue
            if (
                value.get("stale_since") != stale_since
                or value.get("unused_full_sync_count") != next_count
            ):
                value["stale_since"] = stale_since
                value["unused_full_sync_count"] = next_count
                changed = True
    return changed


def parse_timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


def select_pending_auto_delete_candidates(
    stale,
    total_group_count,
    grace_days=14,
    min_unused_runs=3,
    max_delete_count=10,
    max_delete_ratio=0.05,
    now=None,
):
    now = now or datetime.now().astimezone()
    eligible = []
    for group in stale:
        if not is_pending_group(group) or not group.get("public_ids"):
            continue
        uploaded_times = [
            parsed
            for parsed in (parse_timestamp(value) for value in group.get("uploaded_ats", set()))
            if parsed is not None
        ]
        if not uploaded_times:
            continue
        age_days = (now - min(uploaded_times)).total_seconds() / 86400
        unused_runs = max(group.get("unused_full_sync_counts") or [0])
        if age_days >= max(0, grace_days) and unused_runs >= max(1, min_unused_runs):
            eligible.append(group)

    eligible.sort(
        key=lambda group: (
            min(group.get("uploaded_ats") or {"9999"}),
            group["url"],
        )
    )
    if max_delete_count <= 0 or max_delete_ratio <= 0:
        return [], eligible
    ratio_limit = max(1, int(max(0, total_group_count) * max_delete_ratio))
    limit = min(max_delete_count, ratio_limit)
    return eligible[:limit], eligible[limit:]


def cloudinary_signature(params, api_secret):
    signable = {
        key: value for key, value in params.items()
        if value not in (None, "") and key not in {"api_key", "signature"}
    }
    payload = "&".join(f"{key}={signable[key]}" for key in sorted(signable))
    return hashlib.sha1((payload + api_secret).encode("utf-8")).hexdigest()


def destroy_cloudinary_asset(cloud_name, api_key, api_secret, public_id, invalidate=False):
    url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/destroy"
    params = {
        "public_id": public_id,
        "timestamp": str(int(time.time())),
        "api_key": api_key,
    }
    if invalidate:
        params["invalidate"] = "true"
    params["signature"] = cloudinary_signature(params, api_secret)
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def write_report(report_path, used, stale, live, deleted=None, failed=None):
    deleted = deleted or []
    failed = failed or []
    pending_stale = [group for group in stale if is_pending_group(group)]
    committed_stale = [group for group in stale if not is_pending_group(group)]
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    lines = [
        "# Cloudinary Cleanup Report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Markdown files scanned: {live['markdown_files']}",
        f"- Markdown image references: {live['image_refs']}",
        f"- Cache URLs still used/protected: {len(used)}",
        f"- Stale cache URLs candidates: {len(stale)}",
        f"- Pending stale uploads: {len(pending_stale)}",
        f"- Committed stale assets (manual review): {len(committed_stale)}",
        f"- Deleted URLs: {len(deleted)}",
        f"- Failed deletions: {len(failed)}",
        "",
    ]

    if live["missing_refs"]:
        lines.append("## Missing Local Image References")
        lines.append("")
        for ref in live["missing_refs"][:100]:
            lines.append(f"- `{ref}`")
        if len(live["missing_refs"]) > 100:
            lines.append(f"- ... {len(live['missing_refs']) - 100} more")
        lines.append("")

    lines.append("## Stale Candidates")
    lines.append("")
    for group in stale:
        status = "pending" if is_pending_group(group) else "committed"
        public_id = ", ".join(sorted(group["public_ids"])) or "(unknown)"
        filenames = ", ".join(sorted(group["filenames"])) or "(unknown)"
        lines.append(f"- `{status}` / `{public_id}` / {filenames}")
        lines.append(f"  {group['url']}")
    lines.append("")

    if deleted:
        lines.append("## Deleted")
        lines.append("")
        for item in deleted:
            lines.append(f"- `{item['public_id']}` -> {item['result']}")
        lines.append("")

    if failed:
        lines.append("## Failed")
        lines.append("")
        for item in failed:
            lines.append(f"- `{item['public_id']}` -> {item['error']}")
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def prune_cache(cache, deleted_urls):
    if not deleted_urls:
        return cache, 0
    deleted_urls = set(deleted_urls)
    pruned = {
        key: value for key, value in cache.items()
        if get_entry_url(value) not in deleted_urls
    }
    return pruned, len(cache) - len(pruned)


def parse_args():
    parser = argparse.ArgumentParser(description="Find and optionally delete unused Cloudinary images.")
    parser.add_argument("--delete", action="store_true", help="Actually delete stale Cloudinary assets. Default is dry-run.")
    parser.add_argument("--limit", type=int, default=0, help="Limit the number of stale assets processed.")
    parser.add_argument("--invalidate", action="store_true", help="Ask Cloudinary to invalidate CDN cache for deleted assets.")
    parser.add_argument("--keep-cache", action="store_true", help="Do not prune cloudinary_cache.json after successful deletions.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["Daily_Logs", "Subject", "Topic_Reviews"],
        help="Vault folders to scan for live image references.",
    )
    return parser.parse_args()


def _main_unlocked():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_dir = os.path.abspath(os.path.join(script_dir, ".."))
    env_path = os.path.join(script_dir, ".env")
    cache_path = os.path.join(script_dir, "cloudinary_cache.json")
    report_path = os.path.join(script_dir, "reports", "cloudinary_cleanup_report.md")

    load_env(env_path)
    try:
        cache = load_cache(cache_path)
    except StateFileError as exc:
        print(f"Error: {exc}")
        print("The existing Cloudinary cache was not replaced or pruned.")
        return 1
    live = scan_live_images(vault_dir, args.roots)
    groups = group_cache_entries(cache)
    used, stale = classify_groups(groups, live)
    stale = sorted(stale, key=lambda group: sorted(group["filenames"] or group["public_ids"] or {group["url"]}))
    if args.limit > 0:
        stale = stale[:args.limit]

    print(f"Markdown files scanned: {live['markdown_files']}")
    print(f"Markdown image references: {live['image_refs']}")
    print(f"Cloudinary cache URLs: {len(groups)}")
    print(f"Used/protected URLs: {len(used)}")
    print(f"Stale candidates: {len(stale)}")

    deleted = []
    failed = []

    if args.delete and stale:
        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
        api_key = os.environ.get("CLOUDINARY_API_KEY", "")
        api_secret = os.environ.get("CLOUDINARY_API_SECRET", "")
        if not cloud_name or not api_key or not api_secret:
            print("Error: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET are required for --delete.")
            sys.exit(1)

        for group in stale:
            public_ids = sorted(group["public_ids"])
            if not public_ids:
                failed.append({"public_id": "(unknown)", "error": f"Could not derive public_id from {group['url']}"})
                continue
            public_id = public_ids[0]
            try:
                result = destroy_cloudinary_asset(cloud_name, api_key, api_secret, public_id, invalidate=args.invalidate)
                deleted.append({"url": group["url"], "public_id": public_id, "result": result.get("result", result)})
                print(f"Deleted {public_id}: {result.get('result', result)}")
            except urllib.error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                failed.append({"public_id": public_id, "error": f"HTTP {exc.code}: {error_body}"})
                print(f"Failed {public_id}: HTTP {exc.code}")
            except Exception as exc:
                failed.append({"public_id": public_id, "error": str(exc)})
                print(f"Failed {public_id}: {exc}")

        if deleted and not args.keep_cache:
            pruned_cache, removed_entries = prune_cache(cache, [item["url"] for item in deleted])
            try:
                save_cache(cache_path, pruned_cache)
                print(f"Pruned {removed_entries} cache entries from {cache_path}")
            except Exception as exc:
                failed.append({
                    "public_id": "(local cache)",
                    "error": f"Deleted assets but could not save pruned cache: {exc}",
                })
                print(f"Error: Could not save pruned Cloudinary cache: {exc}")
    elif stale:
        print("Dry-run only. Re-run with --delete to delete stale Cloudinary assets.")

    write_report(report_path, used, stale, live, deleted=deleted, failed=failed)
    print(f"Report written: {report_path}")
    return 1 if failed else 0


def main():
    if lock_is_delegated_by_parent():
        return _main_unlocked()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    vault_dir = os.path.abspath(os.path.join(script_dir, ".."))
    try:
        with VaultProcessLock(
            vault_dir,
            "cloudinary-cleanup",
            command=command_text(__file__),
        ):
            return _main_unlocked()
    except ProcessLockUnavailable as exc:
        print_lock_error(exc)
        return LOCK_BUSY_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
