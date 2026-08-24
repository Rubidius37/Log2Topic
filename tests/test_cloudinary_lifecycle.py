import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import cloudinary_cleanup  # noqa: E402
import sync_to_notion  # noqa: E402


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def empty_live():
    return {
        "live_sha1s": set(),
        "live_filenames": set(),
        "missing_filenames": set(),
        "live_cloudinary_urls": set(),
        "markdown_files": 0,
        "image_refs": 0,
        "missing_refs": [],
    }


class CloudinaryLifecycleTests(unittest.TestCase):
    def test_cleanup_does_not_protect_an_image_under_scripts(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            daily_dir = os.path.join(vault_dir, "Daily_Logs")
            scripts_dir = os.path.join(vault_dir, "scripts")
            os.makedirs(daily_dir)
            os.makedirs(scripts_dir)
            with open(os.path.join(daily_dir, "note.md"), "w", encoding="utf-8") as file_obj:
                file_obj.write("![[scripts/secret.png]]\n")
            with open(os.path.join(scripts_dir, "secret.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"secret")

            live = cloudinary_cleanup.scan_live_images(vault_dir, ["Daily_Logs"])

        self.assertEqual(live["live_sha1s"], set())
        self.assertEqual(live["live_filenames"], set())
        self.assertEqual(len(live["missing_refs"]), 1)
        self.assertIn("blocked image reference", live["missing_refs"][0])

    def test_new_upload_is_pending_and_successful_page_can_commit_it(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            os.makedirs(os.path.join(vault_dir, "scripts"))
            image_path = os.path.join(vault_dir, "image.png")
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"image")
            sync_to_notion._cloudinary_cache = {}
            try:
                with patch.object(
                    sync_to_notion,
                    "get_cached_file_sha1",
                    return_value="abc123",
                ), patch.object(
                    sync_to_notion,
                    "upload_to_cloudinary",
                    return_value={
                        "url": "https://res.cloudinary.com/demo/image/upload/v1/image.png",
                        "public_id": "image",
                        "uploaded_at": "2026-08-01T00:00:00+00:00",
                    },
                ), patch.object(sync_to_notion, "save_cloudinary_cache"):
                    sync_to_notion.get_or_upload_cloudinary_image(
                        image_path,
                        {"cloud_name": "demo", "upload_preset": "preset"},
                        vault_dir,
                    )
                    self.assertEqual(
                        sync_to_notion._cloudinary_cache["sha1:abc123"]["status"],
                        sync_to_notion.CLOUDINARY_ASSET_PENDING,
                    )

                    committed = sync_to_notion.mark_cloudinary_manifest_committed(
                        vault_dir,
                        [{"status": "ok", "sha1": "abc123"}],
                    )

                self.assertEqual(committed, 2)
                self.assertTrue(
                    all(
                        entry["status"] == sync_to_notion.CLOUDINARY_ASSET_COMMITTED
                        for entry in sync_to_notion._cloudinary_cache.values()
                    )
                )
            finally:
                sync_to_notion._cloudinary_cache = None

    def test_existing_cache_without_status_is_treated_as_committed(self):
        cache = {
            "sha1:old": {
                "url": "https://res.cloudinary.com/demo/image/upload/v1/old.png",
                "sha1": "old",
                "filename": "old.png",
            }
        }
        group = next(iter(cloudinary_cleanup.group_cache_entries(cache).values()))

        self.assertFalse(cloudinary_cleanup.is_pending_group(group))
        self.assertEqual(group["statuses"], {cloudinary_cleanup.CLOUDINARY_ASSET_COMMITTED})

    def test_pending_asset_requires_age_and_three_successful_unused_runs(self):
        now = datetime(2026, 8, 20, tzinfo=timezone.utc)
        cache = {
            "sha1:pending": {
                "url": "https://res.cloudinary.com/demo/image/upload/v1/pending.png",
                "public_id": "pending",
                "sha1": "pending",
                "filename": "pending.png",
                "uploaded_at": (now - timedelta(days=20)).isoformat(),
                "status": cloudinary_cleanup.CLOUDINARY_ASSET_PENDING,
            }
        }

        for expected_count in range(1, 4):
            groups = cloudinary_cleanup.group_cache_entries(cache)
            used, stale = cloudinary_cleanup.classify_groups(groups, empty_live())
            cloudinary_cleanup.update_pending_lifecycle(cache, used, stale, now=now)
            self.assertEqual(
                cache["sha1:pending"]["unused_full_sync_count"],
                expected_count,
            )

        groups = cloudinary_cleanup.group_cache_entries(cache)
        _used, stale = cloudinary_cleanup.classify_groups(groups, empty_live())
        eligible, deferred = cloudinary_cleanup.select_pending_auto_delete_candidates(
            stale,
            total_group_count=20,
            grace_days=14,
            min_unused_runs=3,
            max_delete_count=10,
            max_delete_ratio=0.05,
            now=now,
        )

        self.assertEqual([group["url"] for group in eligible], [cache["sha1:pending"]["url"]])
        self.assertEqual(deferred, [])

    def test_used_pending_asset_clears_unused_lifecycle(self):
        cache = {
            "sha1:pending": {
                "url": "https://res.cloudinary.com/demo/image/upload/v1/pending.png",
                "public_id": "pending",
                "sha1": "pending",
                "filename": "pending.png",
                "uploaded_at": "2026-08-01T00:00:00+00:00",
                "status": cloudinary_cleanup.CLOUDINARY_ASSET_PENDING,
                "stale_since": "2026-08-02T00:00:00+00:00",
                "unused_full_sync_count": 2,
            }
        }
        live = empty_live()
        live["live_sha1s"].add("pending")
        groups = cloudinary_cleanup.group_cache_entries(cache)
        used, stale = cloudinary_cleanup.classify_groups(groups, live)

        changed = cloudinary_cleanup.update_pending_lifecycle(cache, used, stale)

        self.assertTrue(changed)
        self.assertNotIn("stale_since", cache["sha1:pending"])
        self.assertNotIn("unused_full_sync_count", cache["sha1:pending"])

    def test_auto_cleanup_deletes_pending_but_never_committed_stale_asset(self):
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pending_url = "https://res.cloudinary.com/demo/image/upload/v1/pending.png"
        committed_url = "https://res.cloudinary.com/demo/image/upload/v1/committed.png"
        cache = {
            "sha1:pending": {
                "url": pending_url,
                "public_id": "pending",
                "sha1": "pending",
                "filename": "pending.png",
                "uploaded_at": old,
                "status": cloudinary_cleanup.CLOUDINARY_ASSET_PENDING,
                "stale_since": old,
                "unused_full_sync_count": 2,
            },
            "sha1:committed": {
                "url": committed_url,
                "public_id": "committed",
                "sha1": "committed",
                "filename": "committed.png",
                "uploaded_at": old,
                "status": cloudinary_cleanup.CLOUDINARY_ASSET_COMMITTED,
            },
        }
        args = SimpleNamespace(
            subject_dir="Subject",
            review_dir="Topic_Reviews",
            cloudinary_cleanup="auto",
            cloudinary_cleanup_delete=False,
            cloudinary_cleanup_limit=0,
            cloudinary_cleanup_invalidate=False,
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "CLOUDINARY_CLOUD_NAME": "demo",
                "CLOUDINARY_API_KEY": "key",
                "CLOUDINARY_API_SECRET": "secret",
            },
            clear=False,
        ), patch.object(
            cloudinary_cleanup,
            "load_cache",
            return_value=cache,
        ), patch.object(
            cloudinary_cleanup,
            "scan_live_images",
            return_value=empty_live(),
        ), patch.object(
            cloudinary_cleanup,
            "save_cache",
        ), patch.object(
            cloudinary_cleanup,
            "write_report",
        ), patch.object(
            cloudinary_cleanup,
            "destroy_cloudinary_asset",
            return_value={"result": "ok"},
        ) as destroy:
            result = sync_to_notion.run_cloudinary_cleanup_after_sync(
                args,
                temp_dir,
                temp_dir,
                daily_only_mode=False,
                allow_delete=True,
            )

        self.assertTrue(result)
        destroy.assert_called_once()
        self.assertEqual(destroy.call_args.args[3], "pending")

    def test_auto_cleanup_does_not_advance_or_delete_when_sync_is_unsafe(self):
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        args = SimpleNamespace(
            subject_dir="Subject",
            review_dir="Topic_Reviews",
            cloudinary_cleanup="auto",
            cloudinary_cleanup_delete=False,
            cloudinary_cleanup_limit=0,
            cloudinary_cleanup_invalidate=False,
        )

        for allow_delete, missing_refs in ((False, []), (True, ["note.md: missing.png"])):
            with self.subTest(allow_delete=allow_delete, missing_refs=missing_refs):
                cache = {
                    "sha1:pending": {
                        "url": "https://res.cloudinary.com/demo/image/upload/v1/pending.png",
                        "public_id": "pending",
                        "sha1": "pending",
                        "filename": "pending.png",
                        "uploaded_at": old,
                        "status": cloudinary_cleanup.CLOUDINARY_ASSET_PENDING,
                        "stale_since": old,
                        "unused_full_sync_count": 2,
                    }
                }
                live = empty_live()
                live["missing_refs"] = missing_refs
                with tempfile.TemporaryDirectory() as temp_dir, patch.object(
                    cloudinary_cleanup,
                    "load_cache",
                    return_value=cache,
                ), patch.object(
                    cloudinary_cleanup,
                    "scan_live_images",
                    return_value=live,
                ), patch.object(
                    cloudinary_cleanup,
                    "save_cache",
                ) as save_cache, patch.object(
                    cloudinary_cleanup,
                    "write_report",
                ), patch.object(
                    cloudinary_cleanup,
                    "destroy_cloudinary_asset",
                ) as destroy:
                    result = sync_to_notion.run_cloudinary_cleanup_after_sync(
                        args,
                        temp_dir,
                        temp_dir,
                        daily_only_mode=False,
                        allow_delete=allow_delete,
                    )

                self.assertTrue(result)
                self.assertEqual(cache["sha1:pending"]["unused_full_sync_count"], 2)
                save_cache.assert_not_called()
                destroy.assert_not_called()

    def test_legacy_delete_request_is_restricted_to_auto_pending_mode(self):
        args = SimpleNamespace(
            cloudinary_cleanup="delete",
            cloudinary_cleanup_delete=False,
        )
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                sync_to_notion.resolve_cloudinary_cleanup_mode(args, daily_only_mode=False),
                "auto",
            )


if __name__ == "__main__":
    unittest.main()
