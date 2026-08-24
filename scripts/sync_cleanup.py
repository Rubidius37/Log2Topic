import os
from dataclasses import dataclass, field
from datetime import datetime

from notion_api import (
    NOTION_RETRY_SAFE,
    archive_notion_page,
    notion_api_request,
)
from notion_state import get_state_page_id_candidates, normalize_notion_page_id
from sync_contracts import NOTION_PROP_SYNC_KEY, normalize_sync_key_part


ORPHAN_CLEANUP_LARGE_MIN_PAGES = 10
ORPHAN_CLEANUP_LARGE_RATIO = 0.20


@dataclass
class OrphanCleanupPlan:
    candidates: list = field(default_factory=list)
    canonical_pages: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    existing_page_count: int = 0
    active_sync_key_count: int = 0

    @property
    def candidate_count(self):
        return len(self.candidates)

    @property
    def candidate_ratio(self):
        if self.existing_page_count == 0:
            return 0.0
        return self.candidate_count / self.existing_page_count


@dataclass
class CanonicalPageSelection:
    page: object = None
    reason: str = ""
    conflict: str = ""


def notion_page_id(page):
    if isinstance(page, dict):
        return str(page.get("id", ""))
    return str(page or "")


def notion_page_sort_key(page):
    if isinstance(page, dict):
        created_time = str(page.get("created_time") or "9999-12-31T23:59:59.999Z")
    else:
        created_time = "9999-12-31T23:59:59.999Z"
    return (created_time, normalize_notion_page_id(notion_page_id(page)))


def select_canonical_notion_page(pages, state_entry=None):
    page_records = list(pages or [])
    if not page_records:
        return CanonicalPageSelection(reason="no matching page")

    pages_by_id = {
        normalize_notion_page_id(notion_page_id(page)): page
        for page in page_records
        if notion_page_id(page)
    }
    state_candidates = get_state_page_id_candidates(state_entry)
    for preferred_id, reason in state_candidates:
        if preferred_id in pages_by_id:
            return CanonicalPageSelection(
                page=pages_by_id[preferred_id],
                reason=reason,
            )

    if state_candidates and len(page_records) > 1:
        expected = ", ".join(page_id for page_id, _reason in state_candidates)
        return CanonicalPageSelection(
            conflict=(
                f"Sync state points to {expected}, but none of those Page IDs are "
                f"present among {len(page_records)} matching pages."
            )
        )

    if len(page_records) == 1:
        reason = (
            "only matching page; previous state target unavailable"
            if state_candidates
            else "only matching page"
        )
        return CanonicalPageSelection(page=page_records[0], reason=reason)

    canonical = min(page_records, key=notion_page_sort_key)
    return CanonicalPageSelection(
        page=canonical,
        reason="oldest created page fallback",
    )


def get_all_notion_sync_keys(token, database_id):
    """Retrieves all pages in the Notion database to get their page IDs and Sync Keys."""
    url = f"https://api.notion.com/v1/databases/{database_id}/query"
    pages_by_sync_key = {}
    pages_without_sync_key = []
    has_more = True
    next_cursor = None

    print("Fetching existing pages from Notion database for cleanup comparison...")
    while has_more:
        payload = {"page_size": 100}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        res = notion_api_request(
            url,
            token,
            method="POST",
            data=payload,
            retry_mode=NOTION_RETRY_SAFE,
            operation_name="list database pages for orphan cleanup",
        )
        results = res.get("results", [])

        for page in results:
            page_id = page["id"]
            props = page.get("properties", {})
            sync_key_prop = props.get(NOTION_PROP_SYNC_KEY, {})
            rich_texts = sync_key_prop.get("rich_text", [])
            if rich_texts:
                sync_key = rich_texts[0].get("text", {}).get("content", "")
                if sync_key:
                    pages_by_sync_key.setdefault(sync_key, []).append(page)
                    continue
            pages_without_sync_key.append(page)

        has_more = res.get("has_more", False)
        next_cursor = res.get("next_cursor")

    managed_page_count = sum(len(page_ids) for page_ids in pages_by_sync_key.values())
    print(
        f"Found {managed_page_count} pages with Sync Key and "
        f"{len(pages_without_sync_key)} pages without Sync Key in Notion DB."
    )
    return pages_by_sync_key, pages_without_sync_key

def build_orphan_cleanup_plan(
    notion_pages_by_sync_key,
    active_sync_keys,
    pages_without_sync_key=None,
    sync_state=None,
):
    active_set = set(active_sync_keys)
    candidates = []
    canonical_pages = []
    conflicts = []
    state_pages = sync_state.get("pages", {}) if isinstance(sync_state, dict) else {}
    if not isinstance(state_pages, dict):
        state_pages = {}

    for sync_key, pages in notion_pages_by_sync_key.items():
        if sync_key not in active_set:
            candidates.extend(
                {
                    "page_id": notion_page_id(page),
                    "sync_key": sync_key,
                    "reason": "orphan",
                }
                for page in pages
            )
            continue

        selection = select_canonical_notion_page(
            pages,
            state_entry=state_pages.get(sync_key, {}),
        )
        if selection.conflict:
            conflicts.append(
                {
                    "sync_key": sync_key,
                    "reason": selection.conflict,
                    "page_ids": [notion_page_id(page) for page in pages],
                }
            )
            continue
        if not selection.page:
            continue

        canonical_id = notion_page_id(selection.page)
        normalized_canonical_id = normalize_notion_page_id(canonical_id)
        if len(pages) > 1:
            canonical_pages.append(
                {
                    "sync_key": sync_key,
                    "page_id": canonical_id,
                    "reason": selection.reason,
                }
            )
        candidates.extend(
            {
                "page_id": notion_page_id(page),
                "sync_key": sync_key,
                "reason": "duplicate",
            }
            for page in pages
            if normalize_notion_page_id(notion_page_id(page))
            != normalized_canonical_id
        )

    candidates.extend(
        {
            "page_id": notion_page_id(page),
            "sync_key": "",
            "reason": "missing Sync Key",
        }
        for page in pages_without_sync_key or []
    )
    existing_page_count = sum(
        len(pages) for pages in notion_pages_by_sync_key.values()
    ) + len(pages_without_sync_key or [])
    return OrphanCleanupPlan(
        candidates=candidates,
        canonical_pages=canonical_pages,
        conflicts=conflicts,
        existing_page_count=existing_page_count,
        active_sync_key_count=len(active_set),
    )


def assess_orphan_cleanup_safety(plan, allow_large_cleanup=False):
    if plan.conflicts:
        return (
            False,
            f"Canonical page identity is unresolved for {len(plan.conflicts)} "
            "duplicate Sync Key group(s).",
        )
    if allow_large_cleanup or plan.candidate_count == 0:
        return True, ""

    if plan.active_sync_key_count == 0 and plan.existing_page_count > 0:
        return (
            False,
            "No active local Sync Keys remain, so every existing Notion page is at risk.",
        )

    if (
        plan.candidate_count >= ORPHAN_CLEANUP_LARGE_MIN_PAGES
        and plan.candidate_ratio >= ORPHAN_CLEANUP_LARGE_RATIO
    ):
        return (
            False,
            f"Cleanup would archive {plan.candidate_count}/{plan.existing_page_count} "
            f"pages ({plan.candidate_ratio:.1%}).",
        )

    return True, ""


def write_orphan_cleanup_plan_report(report_path, plan, status, reason=""):
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    lines = [
        "# Notion Orphan Cleanup Plan",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Status: {status}",
        f"- Active local Sync Keys: {plan.active_sync_key_count}",
        f"- Existing Notion pages: {plan.existing_page_count}",
        f"- Archive candidates: {plan.candidate_count}",
        f"- Candidate ratio: {plan.candidate_ratio:.1%}",
    ]
    if reason:
        lines.append(f"- Reason: {reason}")
    lines.extend(["", "## Canonical Pages", ""])
    if not plan.canonical_pages:
        lines.append("- None")
    else:
        for canonical in plan.canonical_pages:
            lines.append(
                f"- `{canonical['sync_key']}` keeps `{canonical['page_id']}` "
                f"({canonical['reason']})"
            )
    lines.extend(["", "## Identity Conflicts", ""])
    if not plan.conflicts:
        lines.append("- None")
    else:
        for conflict in plan.conflicts:
            page_ids = ", ".join(f"`{page_id}`" for page_id in conflict["page_ids"])
            lines.append(
                f"- `{conflict['sync_key']}`: {conflict['reason']} Candidates: {page_ids}"
            )
    lines.extend(["", "## Archive Candidates", ""])
    if not plan.candidates:
        lines.append("- None")
    else:
        for candidate in plan.candidates:
            label = candidate["sync_key"] or "(missing Sync Key)"
            lines.append(
                f"- `{candidate['reason']}` `{label}` "
                f"(Page ID: `{candidate['page_id']}`)"
            )
    with open(report_path, "w", encoding="utf-8") as file_obj:
        file_obj.write("\n".join(lines).rstrip() + "\n")


def cleanup_orphan_pages(
    token,
    database_id,
    notion_pages_by_sync_key,
    active_sync_keys,
    pages_without_sync_key=None,
    plan=None,
    sync_state=None,
):
    """Archives pages in Notion that no longer match active local Sync Keys."""
    print("Starting orphan pages cleanup...")
    plan = plan or build_orphan_cleanup_plan(
        notion_pages_by_sync_key,
        active_sync_keys,
        pages_without_sync_key,
        sync_state=sync_state,
    )
    orphans_count = 0
    failed_count = 0

    for candidate in plan.candidates:
        sync_key = candidate["sync_key"]
        label = sync_key or "missing Sync Key"
        print(
            f"-> {candidate['reason']} page found: {label} "
            f"(ID: {candidate['page_id']}). Archiving..."
        )
        if archive_notion_page(token, candidate["page_id"], label):
            orphans_count += 1
        else:
            failed_count += 1

    print(
        f"Orphan cleanup complete. Archived {orphans_count} pages; "
        f"{failed_count} archive operations failed."
    )
    return {"archived": orphans_count, "failed": failed_count}

def resolve_cloudinary_cleanup_mode(args, daily_only_mode):
    if getattr(args, "cloudinary_cleanup_delete", False):
        return "off" if daily_only_mode else "auto"
    if args.cloudinary_cleanup:
        mode = "auto" if args.cloudinary_cleanup == "delete" else args.cloudinary_cleanup
        return "off" if daily_only_mode and mode == "auto" else mode

    env_mode = os.environ.get("CLOUDINARY_CLEANUP_AFTER_SYNC", "").strip().lower()
    if env_mode in {"off", "false", "no", "0"}:
        return "off"
    if env_mode in {"report", "dry-run", "dryrun"}:
        return "report"
    if env_mode in {"auto", "delete", "true", "yes", "1"}:
        return "off" if daily_only_mode else "auto"

    return "off" if daily_only_mode else "auto"


def cloudinary_legacy_delete_requested(args):
    if getattr(args, "cloudinary_cleanup_delete", False):
        return True
    if getattr(args, "cloudinary_cleanup", None) == "delete":
        return True
    return os.environ.get("CLOUDINARY_CLEANUP_AFTER_SYNC", "").strip().lower() in {
        "delete",
        "true",
        "yes",
        "1",
    }


def cleanup_env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def cleanup_env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default

def run_cloudinary_cleanup_after_sync(
    args,
    script_dir,
    vault_dir,
    daily_only_mode,
    allow_delete=True,
):
    mode = resolve_cloudinary_cleanup_mode(args, daily_only_mode)
    if cloudinary_legacy_delete_requested(args):
        print(
            "Warning: Legacy Cloudinary delete mode is restricted to delayed "
            "pending-only cleanup. Committed assets will not be deleted automatically."
        )
    if mode == "off":
        return True

    try:
        import cloudinary_cleanup
    except Exception as e:
        print(f"Warning: Cloudinary cleanup module could not be loaded: {e}")
        return False

    print("\n[Post-sync] Checking Cloudinary image cleanup candidates...")
    cache_path = os.path.join(script_dir, "cloudinary_cache.json")
    report_path = os.path.join(script_dir, "reports", "cloudinary_cleanup_report.md")
    roots = ["Daily_Logs", args.subject_dir, args.review_dir]

    try:
        cache = cloudinary_cleanup.load_cache(cache_path)
        live = cloudinary_cleanup.scan_live_images(vault_dir, roots)
        groups = cloudinary_cleanup.group_cache_entries(cache)
        used, stale = cloudinary_cleanup.classify_groups(groups, live)
        stale = sorted(
            stale,
            key=lambda group: sorted(group["filenames"] or group["public_ids"] or {group["url"]}),
        )

        print(f"-> Cloudinary cache URLs: {len(groups)}")
        print(f"-> Used/protected URLs: {len(used)}")
        print(f"-> Stale candidates: {len(stale)}")

        deleted = []
        failed = []
        deferred = []
        auto_candidates = []
        if mode == "auto" and not allow_delete:
            print(
                "-> Pending auto cleanup skipped because this full sync was incomplete. "
                "Candidate counters were not advanced."
            )
        elif mode == "auto" and live.get("missing_refs"):
            print(
                "-> Pending auto cleanup blocked because local image references are missing. "
                "Candidate counters were not advanced."
            )
        elif mode == "auto":
            lifecycle_changed = cloudinary_cleanup.update_pending_lifecycle(
                cache,
                used,
                stale,
            )
            if lifecycle_changed:
                cloudinary_cleanup.save_cache(cache_path, cache)
                groups = cloudinary_cleanup.group_cache_entries(cache)
                used, stale = cloudinary_cleanup.classify_groups(groups, live)
                stale = sorted(stale, key=lambda group: group["url"])

            auto_candidates, deferred = (
                cloudinary_cleanup.select_pending_auto_delete_candidates(
                    stale,
                    len(groups),
                    grace_days=cleanup_env_int("CLOUDINARY_PENDING_GRACE_DAYS", 14),
                    min_unused_runs=cleanup_env_int("CLOUDINARY_PENDING_MIN_FULL_SYNCS", 3),
                    max_delete_count=cleanup_env_int("CLOUDINARY_PENDING_MAX_DELETE", 10),
                    max_delete_ratio=cleanup_env_float("CLOUDINARY_PENDING_MAX_DELETE_RATIO", 0.05),
                )
            )
            if args.cloudinary_cleanup_limit > 0:
                deferred = auto_candidates[args.cloudinary_cleanup_limit:] + deferred
                auto_candidates = auto_candidates[:args.cloudinary_cleanup_limit]

            pending_stale = sum(
                1 for group in stale if cloudinary_cleanup.is_pending_group(group)
            )
            committed_stale = len(stale) - pending_stale
            print(f"-> Pending stale uploads: {pending_stale}")
            print(f"-> Committed stale assets (report only): {committed_stale}")
            print(f"-> Pending assets eligible for auto delete: {len(auto_candidates)}")
            if deferred:
                print(f"-> Eligible pending assets deferred by safety limits: {len(deferred)}")

        if auto_candidates:
            cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "")
            api_key = os.environ.get("CLOUDINARY_API_KEY", "")
            api_secret = os.environ.get("CLOUDINARY_API_SECRET", "")
            credentials = (cloud_name, api_key, api_secret)
            if any(not value or value.startswith("your_") for value in credentials):
                print(
                    "Warning: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and "
                    "CLOUDINARY_API_SECRET are required for pending auto cleanup. "
                    "Eligible assets were left unchanged and reported."
                )
            else:
                for group in auto_candidates:
                    public_ids = sorted(group["public_ids"])
                    if not public_ids:
                        failed.append({
                            "public_id": "(unknown)",
                            "error": f"Could not derive public_id from {group['url']}",
                        })
                        continue
                    public_id = public_ids[0]
                    try:
                        result = cloudinary_cleanup.destroy_cloudinary_asset(
                            cloud_name,
                            api_key,
                            api_secret,
                            public_id,
                            invalidate=args.cloudinary_cleanup_invalidate,
                        )
                        deleted.append({
                            "url": group["url"],
                            "public_id": public_id,
                            "result": result.get("result", result),
                        })
                        print(f"-> Deleted Cloudinary asset {public_id}: {result.get('result', result)}")
                    except Exception as e:
                        failed.append({"public_id": public_id, "error": str(e)})
                        print(f"Warning: Failed to delete Cloudinary asset {public_id}: {e}")

                if deleted:
                    pruned_cache, removed_entries = cloudinary_cleanup.prune_cache(
                        cache,
                        [item["url"] for item in deleted],
                    )
                    cloudinary_cleanup.save_cache(cache_path, pruned_cache)
                    print(f"-> Pruned {removed_entries} Cloudinary cache entries.")
        elif stale:
            if mode == "report":
                print(
                    "-> Report mode only. Use the standalone cleanup command with "
                    "--delete to remove reviewed committed assets."
                )

        cloudinary_cleanup.write_report(report_path, used, stale, live, deleted=deleted, failed=failed)
        print(f"-> Cloudinary cleanup report written: {report_path}")
        return not failed
    except Exception as e:
        print(f"Warning: Cloudinary cleanup after sync failed: {e}")
        return False
