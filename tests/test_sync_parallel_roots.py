import io
import os
import sys
import tempfile
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import sync_to_notion  # noqa: E402
import cloudinary_cleanup  # noqa: E402
import notion_api  # noqa: E402
import sync_cleanup  # noqa: E402
from notion_render import (  # noqa: E402
    convert_wikilinks_to_notion_links,
    strip_internal_comments,
)
from sync_to_notion import (  # noqa: E402
    SyncFailure,
    SyncStageResult,
    add_cached_url_fallback,
    assess_orphan_cleanup_safety,
    backfill_sync_state_page_ids,
    build_image_asset_manifest,
    build_managed_wikilink_targets,
    build_orphan_cleanup_plan,
    build_sync_key,
    cleanup_orphan_pages,
    create_or_update_notion_page,
    extract_subject_category_path,
    extract_timeline_category_path,
    extract_timeline_paths_from_metadata,
    hash_sync_payload,
    hash_image_asset_manifest,
    is_sync_run_complete,
    normalize_notion_page_id,
    notion_api_request,
    query_existing_page,
    query_pages_by_property,
    run_cloudinary_cleanup_after_sync,
    select_canonical_notion_page,
    should_run_orphan_cleanup,
    sort_timeline_files_deepest_first,
    write_orphan_cleanup_plan_report,
    write_notion_sync_report,
)


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class ParallelRootSyncTests(unittest.TestCase):
    def test_parallel_subject_root_produces_the_same_category_sync_key(self):
        rel_path = "Subject_Hierarchical/Knowledge/Analysis/Qualitative/note.md"
        category = extract_subject_category_path(rel_path, "Subject_Hierarchical")
        self.assertEqual(category, "Knowledge/Analysis/Qualitative")
        self.assertEqual(
            build_sync_key(
                rel_path,
                note_metadata={"source_id": "abc123"},
                subject_dir="Subject_Hierarchical",
            ),
            "subject::abc123::Knowledge/Analysis/Qualitative",
        )

    def test_schema_four_review_paths_are_loaded(self):
        metadata = {
            "review_paths": [
                "Topic_Reviews_Hierarchical/Knowledge/Analysis/Qualitative/[리뷰] Qualitative.md"
            ]
        }
        paths = extract_timeline_paths_from_metadata(
            metadata,
            ROOT_DIR,
            "Topic_Reviews_Hierarchical",
        )
        self.assertEqual(paths, metadata["review_paths"])
        self.assertEqual(
            extract_timeline_category_path(
                paths[0], "Topic_Reviews_Hierarchical"
            ),
            "Knowledge/Analysis/Qualitative",
        )

    def test_source_id_comments_are_not_sent_to_notion(self):
        content = (
            "## Analysis\n"
            "<!-- research-notes-source-id: abcdef1234567890 -->\n"
            "body\n"
        )
        cleaned = strip_internal_comments(content)
        self.assertNotIn("research-notes-source-id", cleaned)
        self.assertIn("body", cleaned)

    def test_source_id_comment_removal_preserves_existing_blank_lines(self):
        content = (
            "# Knowledge\n\n"
            "<!-- research-notes-source-id: abcdef1234567890 -->\n"
            "body\n"
        )
        self.assertEqual(
            strip_internal_comments(content),
            "# Knowledge\n\nbody\n",
        )

    def test_reviews_sync_children_before_parent_reviews(self):
        files = [
            "Topic_Reviews_Hierarchical/Knowledge/[종합 리뷰] Knowledge.md",
            "Topic_Reviews_Hierarchical/Knowledge/Analysis/[종합 리뷰] Analysis.md",
            "Topic_Reviews_Hierarchical/Knowledge/Analysis/Qualitative/[리뷰] Qualitative.md",
        ]
        ordered = sort_timeline_files_deepest_first(
            files, "Topic_Reviews_Hierarchical"
        )
        self.assertEqual(ordered[0], files[2])
        self.assertEqual(ordered[-1], files[0])

    def test_aggregate_review_wikilink_with_brackets_is_converted(self):
        content = (
            "- [[Topic_Reviews_Hierarchical/Knowledge/Analysis/[종합 리뷰] Analysis|Analysis]]"
        )
        converted = convert_wikilinks_to_notion_links(
            content,
            {
                "Topic_Reviews_Hierarchical/Knowledge/Analysis/[종합 리뷰] Analysis.md":
                    "https://www.notion.so/review-ce"
            },
        )
        self.assertEqual(converted, "- [Analysis](https://www.notion.so/review-ce)")

    def test_unresolved_managed_link_uploads_as_text_and_repairs_later(self):
        content = "원본: [[Daily_Logs/2026-08/260814 일지|260814 일지]]"
        managed = build_managed_wikilink_targets(
            ["Daily_Logs/2026-08/260814 일지.md"]
        )
        unresolved = []
        fallback = convert_wikilinks_to_notion_links(
            content,
            {},
            managed_targets=managed,
            unresolved_targets=unresolved,
        )
        repaired = convert_wikilinks_to_notion_links(
            content,
            {
                "Daily_Logs/2026-08/260814 일지.md":
                    "https://www.notion.so/daily-260814"
            },
            managed_targets=managed,
            unresolved_targets=[],
        )

        self.assertEqual(fallback, "원본: 260814 일지")
        self.assertEqual(unresolved, ["Daily_Logs/2026-08/260814 일지"])
        self.assertIn("https://www.notion.so/daily-260814", repaired)
        self.assertNotEqual(
            hash_sync_payload("subject::1::Knowledge", fallback),
            hash_sync_payload("subject::1::Knowledge", repaired),
        )

    def test_relative_markdown_link_is_resolved_from_current_document(self):
        content = (
            "원본: [260814 일지](../../Daily_Logs/2026-08/"
            "260814%20%EC%9D%BC%EC%A7%80.md)"
        )
        target = "Daily_Logs/2026-08/260814 일지.md"
        converted = convert_wikilinks_to_notion_links(
            content,
            {target: "https://www.notion.so/daily-260814"},
            managed_targets=build_managed_wikilink_targets([target]),
            source_path="Subject/Knowledge/note.md",
        )

        self.assertEqual(
            converted,
            "원본: [260814 일지](https://www.notion.so/daily-260814)",
        )

    def test_unresolved_relative_managed_link_becomes_text(self):
        content = "[원본](../../Daily_Logs/missing.md)"
        managed = build_managed_wikilink_targets(["Daily_Logs/missing.md"])
        unresolved = []

        converted = convert_wikilinks_to_notion_links(
            content,
            {},
            managed_targets=managed,
            unresolved_targets=unresolved,
            source_path="Subject/Knowledge/note.md",
        )

        self.assertEqual(converted, "원본")
        self.assertEqual(unresolved, ["Daily_Logs/missing.md"])

    def test_external_and_unmanaged_markdown_links_are_preserved(self):
        content = "[웹](https://example.com) / [문서](../manual.md)"

        converted = convert_wikilinks_to_notion_links(
            content,
            {},
            source_path="Subject/Knowledge/note.md",
        )

        self.assertEqual(converted, content)

    def test_failed_page_can_keep_its_last_known_link_url(self):
        state = {
            "pages": {
                "daily::Daily_Logs/a.md": {
                    "url": "https://www.notion.so/last-known-a"
                }
            }
        }
        url_map = {}
        found = add_cached_url_fallback(
            state,
            "daily::Daily_Logs/a.md",
            "Daily_Logs/a.md",
            url_map,
        )
        self.assertTrue(found)
        self.assertEqual(
            url_map["Daily_Logs/a.md"],
            "https://www.notion.so/last-known-a",
        )

    def test_page_with_unresolved_managed_link_is_still_uploaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    "**Date/Log**: "
                    "[[Daily_Logs/2026-08/260814 일지|260814 일지]]\n"
                )

            state = {"pages": {}}
            unresolved = []
            managed = build_managed_wikilink_targets(
                ["Daily_Logs/2026-08/260814 일지.md"]
            )

            def fake_api(url, _token, method="GET", data=None, **_kwargs):
                if method == "POST" and url.endswith("/v1/pages"):
                    return {
                        "id": "new-page",
                        "url": "https://notion.so/new-page",
                    }
                if method == "PATCH" and url.endswith("/blocks/new-page/children"):
                    return {
                        "results": [
                            {"id": f"new-block-{index}"}
                            for index, _block in enumerate(data["children"])
                        ]
                    }
                raise AssertionError(f"Unexpected API call: {method} {url}")

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value=None,
            ), patch.object(
                sync_to_notion,
                "notion_api_request",
                side_effect=fake_api,
            ), patch.object(
                notion_api,
                "notion_api_request",
                side_effect=fake_api,
            ):
                page_url = create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    url_map={},
                    vault_dir=temp_dir,
                    available_properties={"Sync Key"},
                    sync_key="subject::1::Knowledge",
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                    managed_link_targets=managed,
                    unresolved_links=unresolved,
                )

        self.assertEqual(page_url, "https://notion.so/new-page")
        self.assertEqual(
            state["pages"]["subject::1::Knowledge"]["unresolved_links"],
            ["Daily_Logs/2026-08/260814 일지"],
        )
        self.assertEqual(
            unresolved,
            [
                {
                    "source_path": rel_path,
                    "target": "Daily_Logs/2026-08/260814 일지",
                }
            ],
        )

    def test_unchanged_page_skips_every_notion_api_call(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("unchanged\n")

            sync_key = "subject::stable::Knowledge"
            content_hash = hash_sync_payload(sync_key, "unchanged\n", "Knowledge")
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "content_hash": content_hash,
                    }
                }
            }
            with patch.object(sync_to_notion, "notion_api_request") as api:
                page_url = create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                )

        self.assertEqual(page_url, "https://www.notion.so/stable")
        api.assert_not_called()
        self.assertIn("asset_hash", state["pages"][sync_key])

    def test_same_filename_image_replacement_changes_asset_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(attachments_dir)
            image_path = os.path.join(attachments_dir, "measurement.png")
            markdown = "![[measurement.png]]\n"
            sync_to_notion._image_sha1_cache.clear()

            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"first-image")
            first_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )

            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"second-image-with-different-bytes")
            second_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )

        self.assertNotEqual(first_hash, second_hash)

    def test_repeated_image_references_hash_each_file_once_per_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(attachments_dir)
            image_path = os.path.join(attachments_dir, "shared.png")
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"shared-image")
            sync_to_notion._image_sha1_cache.clear()

            with patch.object(
                sync_to_notion,
                "get_file_sha1",
                return_value="shared-sha1",
            ) as hasher:
                build_image_asset_manifest(
                    "![[shared.png]]![[shared.png]]\n",
                    temp_dir,
                )
                build_image_asset_manifest("![[shared.png]]\n", temp_dir)

        hasher.assert_called_once_with(os.path.abspath(image_path))

    def test_changed_image_bytes_force_page_update_with_unchanged_markdown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            markdown = "![[measurement.png]]\n"
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(markdown)
            image_path = os.path.join(attachments_dir, "measurement.png")
            sync_to_notion._image_sha1_cache.clear()
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"old-image")

            sync_key = "subject::stable::Knowledge"
            old_asset_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "page_id": "stable-page",
                        "content_hash": hash_sync_payload(sync_key, markdown, "Knowledge"),
                        "asset_hash": old_asset_hash,
                    }
                }
            }
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"new-image-with-different-bytes")

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "stable-page",
                    "url": "https://www.notion.so/stable",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[],
            ), patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
            ) as replace_page:
                page_url = create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    vault_dir=temp_dir,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                )

        self.assertEqual(page_url, "https://www.notion.so/stable")
        replace_page.assert_called_once()
        self.assertNotEqual(state["pages"][sync_key]["asset_hash"], old_asset_hash)

    def test_unchanged_image_asset_skips_page_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            markdown = "![[stable.png]]\n"
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(markdown)
            with open(os.path.join(attachments_dir, "stable.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"stable-image")
            sync_to_notion._image_sha1_cache.clear()

            sync_key = "subject::stable::Knowledge"
            asset_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "content_hash": hash_sync_payload(sync_key, markdown, "Knowledge"),
                        "asset_hash": asset_hash,
                        "image_delivery_version": (
                            sync_to_notion.NOTION_IMAGE_DELIVERY_EXTERNAL_ONLY_VERSION
                        ),
                    }
                }
            }
            with patch.object(sync_to_notion, "notion_api_request") as api, patch.object(
                sync_to_notion,
                "query_existing_page",
            ) as query_page:
                page_url = create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    vault_dir=temp_dir,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                )

        self.assertEqual(page_url, "https://www.notion.so/stable")
        api.assert_not_called()
        query_page.assert_not_called()

    def test_missing_image_dependency_changes_when_file_appears(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(attachments_dir)
            markdown = "![[later.png]]\n"
            sync_to_notion._image_sha1_cache.clear()

            missing_manifest = build_image_asset_manifest(markdown, temp_dir)
            missing_hash = hash_image_asset_manifest(missing_manifest)
            with open(os.path.join(attachments_dir, "later.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"now-present")
            present_manifest = build_image_asset_manifest(markdown, temp_dir)
            present_hash = hash_image_asset_manifest(present_manifest)

        self.assertEqual(missing_manifest[0]["status"], "missing")
        self.assertEqual(present_manifest[0]["status"], "ok")
        self.assertNotEqual(missing_hash, present_hash)

    def test_existing_image_page_without_asset_hash_updates_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            markdown = "![[baseline.png]]\n"
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(markdown)
            with open(os.path.join(attachments_dir, "baseline.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"baseline-image")
            sync_to_notion._image_sha1_cache.clear()

            sync_key = "subject::stable::Knowledge"
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "page_id": "stable-page",
                        "content_hash": hash_sync_payload(sync_key, markdown, "Knowledge"),
                    }
                }
            }
            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "stable-page",
                    "url": "https://www.notion.so/stable",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[],
            ), patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
            ) as replace_page:
                create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    vault_dir=temp_dir,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                )

        replace_page.assert_called_once()
        self.assertIn("asset_hash", state["pages"][sync_key])

    def test_cloudinary_http_error_is_raised_with_response_details(self):
        error = urllib.error.HTTPError(
            "https://api.cloudinary.com/upload",
            401,
            "unauthorized",
            {},
            io.BytesIO(b'{"error":{"message":"Invalid upload preset"}}'),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "measurement.png")
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"image")

            with patch.object(
                sync_to_notion.urllib.request,
                "urlopen",
                side_effect=error,
            ):
                with self.assertRaisesRegex(
                    sync_to_notion.CloudinaryUploadError,
                    "HTTP 401.*Invalid upload preset",
                ):
                    sync_to_notion.upload_to_cloudinary(
                        image_path,
                        "cloud",
                        "preset",
                    )

    def test_cloudinary_mode_does_not_fall_back_to_localhost(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(attachments_dir)
            image_path = os.path.join(attachments_dir, "measurement.png")
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"image")

            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
                return_value=None,
            ):
                with self.assertRaisesRegex(
                    sync_to_notion.CloudinaryUploadError,
                    "returned no URL",
                ):
                    sync_to_notion.create_image_block(
                        "measurement.png",
                        "http://localhost:8000",
                        vault_dir=temp_dir,
                        cloudinary_config={
                            "cloud_name": "cloud",
                            "upload_preset": "preset",
                        },
                    )

    def test_cloudinary_mode_fails_when_local_image_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                sync_to_notion.CloudinaryUploadError,
                "Local image file was not found.*missing.png",
            ):
                sync_to_notion.create_image_block(
                    "missing.png",
                    "http://localhost:8000",
                    vault_dir=temp_dir,
                    cloudinary_config={
                        "cloud_name": "cloud",
                        "upload_preset": "preset",
                    },
                )

    def test_local_image_without_cloudinary_fails_instead_of_using_localhost(self):
        with self.assertRaisesRegex(
            sync_to_notion.CloudinaryUploadError,
            "Local images require Cloudinary",
        ):
            sync_to_notion.create_image_block(
                "measurement image.png",
                None,
            )

    def test_external_https_image_does_not_require_cloudinary(self):
        block = sync_to_notion.create_image_block(
            "https://example.com/measurement%20image.png",
            None,
        )

        self.assertEqual(
            block["image"]["external"]["url"],
            "https://example.com/measurement%20image.png",
        )

    def test_cloudinary_rejects_paths_outside_the_vault_before_upload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault_dir = os.path.join(temp_dir, "vault")
            os.makedirs(vault_dir)
            outside_path = os.path.join(temp_dir, "outside.png")
            with open(outside_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"outside")

            references = [
                "../outside.png",
                "%2e%2e/outside.png",
                outside_path,
            ]
            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
            ) as upload:
                for reference in references:
                    with self.subTest(reference=reference), self.assertRaises(
                        sync_to_notion.CloudinaryUploadError
                    ):
                        sync_to_notion.create_image_block(
                            reference,
                            None,
                            vault_dir=vault_dir,
                            cloudinary_config={
                                "cloud_name": "cloud",
                                "upload_preset": "preset",
                            },
                        )

            upload.assert_not_called()

    def test_cloudinary_resolves_parent_relative_attachment_reference(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            attachments_dir = os.path.join(vault_dir, "attachments")
            os.makedirs(attachments_dir)
            image_path = os.path.join(attachments_dir, "pasted.png")
            with open(image_path, "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"attachment")

            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
                return_value="https://cloudinary.example/pasted.png",
            ) as upload:
                block = sync_to_notion.create_image_block(
                    "../../attachments/pasted.png",
                    None,
                    vault_dir=vault_dir,
                    cloudinary_config={
                        "cloud_name": "cloud",
                        "upload_preset": "preset",
                    },
                )

            self.assertEqual(
                block["image"]["external"]["url"],
                "https://cloudinary.example/pasted.png",
            )
            upload.assert_called_once()

    def test_cloudinary_rejects_protected_and_non_image_files_before_upload(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            scripts_dir = os.path.join(vault_dir, "scripts")
            attachments_dir = os.path.join(vault_dir, "attachments")
            os.makedirs(scripts_dir)
            os.makedirs(attachments_dir)
            with open(os.path.join(scripts_dir, ".env"), "w", encoding="utf-8") as file_obj:
                file_obj.write("NOTION_TOKEN=secret\n")
            with open(os.path.join(scripts_dir, "secret.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"secret")
            with open(os.path.join(attachments_dir, "fake.png"), "w", encoding="utf-8") as file_obj:
                file_obj.write("NOTION_TOKEN=secret\n")
            with open(os.path.join(attachments_dir, "fake.svg"), "w", encoding="utf-8") as file_obj:
                file_obj.write("NOTION_TOKEN=secret\n")

            references = ["scripts/.env", "scripts/secret.png", "fake.png", "fake.svg"]
            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
            ) as upload:
                for reference in references:
                    with self.subTest(reference=reference), self.assertRaises(
                        sync_to_notion.CloudinaryUploadError
                    ):
                        sync_to_notion.create_image_block(
                            reference,
                            None,
                            vault_dir=vault_dir,
                            cloudinary_config={
                                "cloud_name": "cloud",
                                "upload_preset": "preset",
                            },
                        )

            upload.assert_not_called()

    def test_valid_svg_inside_vault_can_use_cloudinary(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            attachments_dir = os.path.join(vault_dir, "attachments")
            os.makedirs(attachments_dir)
            with open(os.path.join(attachments_dir, "diagram.svg"), "w", encoding="utf-8") as file_obj:
                file_obj.write(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
                    '<path d="M0 0h10v10z"/></svg>'
                )

            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
                return_value="https://res.cloudinary.com/demo/diagram.svg",
            ) as upload:
                block = sync_to_notion.create_image_block(
                    "diagram.svg",
                    None,
                    vault_dir=vault_dir,
                    cloudinary_config={
                        "cloud_name": "cloud",
                        "upload_preset": "preset",
                    },
                )

            upload.assert_called_once()
            self.assertEqual(
                block["image"]["external"]["url"],
                "https://res.cloudinary.com/demo/diagram.svg",
            )

    def test_cloudinary_upload_rejects_fake_image_before_network_request(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = os.path.join(temp_dir, "fake.png")
            with open(image_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("NOTION_TOKEN=secret\n")

            with patch.object(sync_to_notion.urllib.request, "urlopen") as urlopen:
                with self.assertRaisesRegex(
                    sync_to_notion.CloudinaryUploadError,
                    "file contents do not match",
                ):
                    sync_to_notion.upload_to_cloudinary(image_path, "cloud", "preset")

            urlopen.assert_not_called()

    def test_sync_and_cleanup_share_the_same_safe_image_resolver(self):
        self.assertIs(
            sync_to_notion.resolve_local_image_path,
            cloudinary_cleanup.resolve_local_image_path,
        )

    def test_unsafe_image_reference_preserves_existing_notion_state(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            rel_path = "Daily_Logs/note.md"
            full_path = os.path.join(vault_dir, *rel_path.split("/"))
            scripts_dir = os.path.join(vault_dir, "scripts")
            os.makedirs(os.path.dirname(full_path))
            os.makedirs(scripts_dir)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("![[scripts/.env]]\n")
            with open(os.path.join(scripts_dir, ".env"), "w", encoding="utf-8") as file_obj:
                file_obj.write("NOTION_TOKEN=secret\n")

            original_entry = {
                "url": "https://www.notion.so/stable",
                "page_id": "stable-page",
                "content_hash": "last-successful-content",
            }
            state = {"pages": {"daily::note": dict(original_entry)}}
            with patch.object(sync_to_notion, "notion_api_request") as notion_api, patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
            ) as upload:
                with self.assertRaisesRegex(
                    sync_to_notion.CloudinaryUploadError,
                    "allowed image type",
                ):
                    create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        vault_dir=vault_dir,
                        cloudinary_config={
                            "cloud_name": "cloud",
                            "upload_preset": "preset",
                        },
                        available_properties={"Sync Key"},
                        sync_key="daily::note",
                        page_kind="Daily",
                        sync_state=state,
                    )

            self.assertEqual(state["pages"]["daily::note"], original_entry)
            notion_api.assert_not_called()
            upload.assert_not_called()

    def test_cloudinary_failure_preserves_existing_page_and_sync_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            markdown = "![[measurement.png]]\nupdated body\n"
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(markdown)
            with open(
                os.path.join(attachments_dir, "measurement.png"),
                "wb",
            ) as file_obj:
                file_obj.write(PNG_HEADER + b"updated-image")
            sync_to_notion._image_sha1_cache.clear()

            sync_key = "subject::stable::Knowledge"
            asset_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )
            original_entry = {
                "url": "https://www.notion.so/stable",
                "page_id": "stable-page",
                "content_hash": hash_sync_payload(sync_key, markdown, "Knowledge"),
                "asset_hash": asset_hash,
                "image_delivery_version": (
                    sync_to_notion.NOTION_IMAGE_DELIVERY_EXTERNAL_ONLY_VERSION
                ),
            }
            state = {"pages": {sync_key: dict(original_entry)}}
            cloudinary_config = {
                "cloud_name": "cloud",
                "upload_preset": "preset",
            }

            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
                side_effect=sync_to_notion.CloudinaryUploadError(
                    "Cloudinary upload failed for measurement.png: timeout"
                ),
            ), patch.object(
                sync_to_notion,
                "query_existing_page",
            ) as query_page, patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
            ) as replace_page, patch.object(
                sync_to_notion,
                "notion_api_request",
            ) as notion_api:
                with self.assertRaisesRegex(
                    sync_to_notion.CloudinaryUploadError,
                    "measurement.png: timeout",
                ):
                    create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        vault_dir=temp_dir,
                        cloudinary_config=cloudinary_config,
                        available_properties={"Sync Key"},
                        sync_key=sync_key,
                        page_kind="Subject",
                        category_path="Knowledge",
                        sync_state=state,
                    )

        self.assertEqual(state["pages"][sync_key], original_entry)
        query_page.assert_not_called()
        replace_page.assert_not_called()
        notion_api.assert_not_called()

    def test_new_page_is_not_created_when_cloudinary_upload_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Daily_Logs/new.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("![[new.png]]\n")
            with open(os.path.join(attachments_dir, "new.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"new-image")

            state = {"pages": {}}
            with patch.object(
                sync_to_notion,
                "get_or_upload_cloudinary_image",
                side_effect=sync_to_notion.CloudinaryUploadError("upload unavailable"),
            ), patch.object(sync_to_notion, "notion_api_request") as notion_api:
                with self.assertRaises(sync_to_notion.CloudinaryUploadError):
                    create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        vault_dir=temp_dir,
                        cloudinary_config={
                            "cloud_name": "cloud",
                            "upload_preset": "preset",
                        },
                        available_properties={"Sync Key"},
                        sync_key="daily::new",
                        page_kind="Daily",
                        sync_state=state,
                    )

        self.assertEqual(state, {"pages": {}})
        notion_api.assert_not_called()

    def test_legacy_image_delivery_state_is_revalidated_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            attachments_dir = os.path.join(temp_dir, "attachments")
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            os.makedirs(attachments_dir)
            markdown = "![[stable.png]]\n"
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write(markdown)
            with open(os.path.join(attachments_dir, "stable.png"), "wb") as file_obj:
                file_obj.write(PNG_HEADER + b"stable-image")
            sync_to_notion._image_sha1_cache.clear()

            sync_key = "subject::stable::Knowledge"
            asset_hash = hash_image_asset_manifest(
                build_image_asset_manifest(markdown, temp_dir)
            )
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "page_id": "stable-page",
                        "content_hash": hash_sync_payload(sync_key, markdown, "Knowledge"),
                        "asset_hash": asset_hash,
                    }
                }
            }
            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "stable-page",
                    "url": "https://www.notion.so/stable",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[],
            ), patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
            ) as replace_page:
                create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    vault_dir=temp_dir,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Subject",
                    category_path="Knowledge",
                    sync_state=state,
                )

        replace_page.assert_called_once()
        self.assertEqual(
            state["pages"][sync_key]["image_delivery_version"],
            sync_to_notion.NOTION_IMAGE_DELIVERY_EXTERNAL_ONLY_VERSION,
        )

    def test_successful_images_are_cached_when_a_later_upload_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.makedirs(os.path.join(temp_dir, "attachments"))
            os.makedirs(os.path.join(temp_dir, "scripts"))
            for filename, content in (
                ("first.png", PNG_HEADER + b"first"),
                ("second.png", PNG_HEADER + b"second"),
            ):
                with open(
                    os.path.join(temp_dir, "attachments", filename),
                    "wb",
                ) as file_obj:
                    file_obj.write(content)

            config = {"cloud_name": "cloud", "upload_preset": "preset"}
            markdown = "![[first.png]]![[second.png]]"
            sync_to_notion._cloudinary_cache = None
            sync_to_notion._image_sha1_cache.clear()
            try:
                with patch.object(
                    sync_to_notion,
                    "upload_to_cloudinary",
                    side_effect=[
                        "https://res.cloudinary.com/first.png",
                        sync_to_notion.CloudinaryUploadError("second failed"),
                    ],
                ) as first_attempt:
                    with self.assertRaisesRegex(
                        sync_to_notion.CloudinaryUploadError,
                        "second failed",
                    ):
                        sync_to_notion.markdown_to_notion_blocks(
                            markdown,
                            vault_dir=temp_dir,
                            cloudinary_config=config,
                        )
                self.assertEqual(first_attempt.call_count, 2)

                with patch.object(
                    sync_to_notion,
                    "upload_to_cloudinary",
                    return_value="https://res.cloudinary.com/second.png",
                ) as retry:
                    blocks = sync_to_notion.markdown_to_notion_blocks(
                        markdown,
                        vault_dir=temp_dir,
                        cloudinary_config=config,
                    )

                self.assertEqual(len(blocks), 2)
                retry.assert_called_once()
                self.assertTrue(retry.call_args.args[0].endswith("second.png"))
            finally:
                sync_to_notion._cloudinary_cache = None
                sync_to_notion._image_sha1_cache.clear()

    def test_changed_page_updates_in_place_and_preserves_page_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Topic_Reviews/Knowledge/[리뷰] Knowledge.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("updated review\n")

            state = {
                "pages": {
                    "timeline::Knowledge": {
                        "url": "https://www.notion.so/stable-review",
                        "content_hash": "old-hash",
                    }
                }
            }
            blocks = [{"object": "block", "type": "paragraph"} for _ in range(101)]
            calls = []

            def fake_api(url, _token, method="GET", data=None, **_kwargs):
                calls.append((method, url, data))
                if method == "GET" and url.endswith("page_size=100"):
                    return {
                        "results": [{"id": "old-a"}, {"id": "old-b"}],
                        "has_more": False,
                    }
                if method == "PATCH" and "/blocks/stable-page/children" in url:
                    return {
                        "results": [
                            {"id": f"new-{len(calls)}-{index}"}
                            for index, _block in enumerate(data["children"])
                        ]
                    }
                if method == "PATCH" and url.endswith("/pages/stable-page"):
                    return {"id": "stable-page"}
                if method == "DELETE":
                    return {"archived": True}
                raise AssertionError(f"Unexpected API call: {method} {url}")

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "stable-page",
                    "url": "https://www.notion.so/stable-review",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=blocks,
            ), patch.object(
                notion_api,
                "notion_api_request",
                side_effect=fake_api,
            ):
                page_url = create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    available_properties={"Sync Key"},
                    sync_key="timeline::Knowledge",
                    page_kind="timeline",
                    category_path="Knowledge",
                    sync_state=state,
                )

        self.assertEqual(page_url, "https://www.notion.so/stable-review")
        self.assertEqual(state["pages"]["timeline::Knowledge"]["page_id"], "stable-page")
        self.assertNotEqual(
            state["pages"]["timeline::Knowledge"]["content_hash"],
            "old-hash",
        )
        self.assertFalse(
            any(method == "POST" and url.endswith("/v1/pages") for method, url, _ in calls)
        )
        append_calls = [
            call for call in calls
            if call[0] == "PATCH" and "/blocks/stable-page/children" in call[1]
        ]
        self.assertEqual([len(call[2]["children"]) for call in append_calls], [100, 1])
        property_index = next(
            index for index, call in enumerate(calls)
            if call[0] == "PATCH" and call[1].endswith("/pages/stable-page")
        )
        first_delete_index = next(
            index for index, call in enumerate(calls) if call[0] == "DELETE"
        )
        self.assertLess(property_index, first_delete_index)

    def test_large_callout_children_are_appended_in_recursive_chunks(self):
        child_blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []},
            }
            for _ in range(495)
        ]
        callout = {
            "object": "block",
            "type": "callout",
            "callout": {"rich_text": [], "children": child_blocks},
        }
        payloads = []
        next_id = 0

        def fake_api(_url, _token, method="GET", data=None, **_kwargs):
            nonlocal next_id
            self.assertEqual(method, "PATCH")
            payloads.append(data["children"])
            results = []
            for _block in data["children"]:
                next_id += 1
                results.append({"id": f"block-{next_id}"})
            return {"results": results}

        appended = []
        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=fake_api,
        ):
            sync_to_notion.append_notion_block_tree(
                "token",
                "page-id",
                [callout],
                appended_top_level_ids=appended,
                track_top_level=True,
            )

        self.assertEqual([len(payload) for payload in payloads], [1, 100, 100, 100, 100, 95])
        self.assertNotIn("children", payloads[0][0]["callout"])
        self.assertEqual(len(callout["callout"]["children"]), 495)
        self.assertEqual(appended, ["block-1"])
        for payload in payloads:
            self.assertLessEqual(len(payload), 100)
            self.assertTrue(
                all(sync_to_notion.notion_block_fits_single_request(block) for block in payload)
            )

    def test_five_level_list_is_uploaded_without_flattening(self):
        def list_item(label, child=None):
            payload = {"rich_text": [{"text": {"content": label}}]}
            if child is not None:
                payload["children"] = [child]
            return {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": payload,
            }

        block = list_item(
            "level-1",
            list_item(
                "level-2",
                list_item("level-3", list_item("level-4", list_item("level-5"))),
            ),
        )
        payloads = []
        next_id = 0

        def fake_api(_url, _token, method="GET", data=None, **_kwargs):
            nonlocal next_id
            self.assertEqual(method, "PATCH")
            payloads.append(data["children"])
            results = []
            for _block in data["children"]:
                next_id += 1
                results.append({"id": f"list-{next_id}"})
            return {"results": results}

        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=fake_api,
        ):
            sync_to_notion.append_notion_block_tree("token", "page-id", [block])

        self.assertEqual(len(payloads), 3)
        self.assertEqual(
            sync_to_notion.get_notion_block_children(block)[0]
            ["bulleted_list_item"]["rich_text"][0]["text"]["content"],
            "level-2",
        )
        for payload in payloads:
            self.assertTrue(
                all(sync_to_notion.notion_block_fits_single_request(item) for item in payload)
            )

    def test_recursive_child_failure_rolls_back_new_top_level_block(self):
        callout = {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [],
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": []},
                    }
                    for _ in range(101)
                ],
            },
        }
        calls = []

        def fake_api(url, _token, method="GET", data=None, **_kwargs):
            calls.append((method, url, data))
            if method == "GET":
                return {"results": [{"id": "old-a"}], "has_more": False}
            if method == "PATCH" and url.endswith("/blocks/page-a/children"):
                return {"results": [{"id": "new-callout"}]}
            if method == "PATCH" and url.endswith("/blocks/new-callout/children"):
                child_appends = [
                    call for call in calls
                    if call[0] == "PATCH" and call[1].endswith("/blocks/new-callout/children")
                ]
                if len(child_appends) == 1:
                    return {
                        "results": [
                            {"id": f"child-{index}"}
                            for index, _block in enumerate(data["children"])
                        ]
                    }
                raise RuntimeError("nested chunk failed")
            if method == "DELETE" and url.endswith("/blocks/new-callout"):
                return {"archived": True}
            raise AssertionError(f"Unexpected API call: {method} {url}")

        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=fake_api,
        ):
            with self.assertRaisesRegex(RuntimeError, "nested chunk failed"):
                sync_to_notion.replace_page_content_in_place(
                    "token",
                    "page-a",
                    {"Name": {"title": []}},
                    [[callout]],
                )

        deleted_urls = [url for method, url, _data in calls if method == "DELETE"]
        self.assertEqual(
            deleted_urls,
            ["https://api.notion.com/v1/blocks/new-callout"],
        )

    def test_failed_later_append_chunk_rolls_back_new_blocks_only(self):
        calls = []

        def fake_api(url, _token, method="GET", data=None, **_kwargs):
            calls.append((method, url, data))
            if method == "GET":
                return {"results": [{"id": "old-a"}], "has_more": False}
            if method == "PATCH" and "/blocks/page-a/children" in url:
                append_count = sum(
                    1
                    for call in calls
                    if call[0] == "PATCH" and "/blocks/page-a/children" in call[1]
                )
                if append_count == 1:
                    return {"results": [{"id": "new-a"}]}
                raise RuntimeError("second chunk failed")
            if method == "DELETE" and url.endswith("/blocks/new-a"):
                return {"archived": True}
            raise AssertionError(f"Unexpected API call: {method} {url}")

        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=fake_api,
        ):
            with self.assertRaisesRegex(RuntimeError, "prepare in-place update"):
                sync_to_notion.replace_page_content_in_place(
                    "token",
                    "page-a",
                    {"Name": {"title": []}},
                    [[{"object": "block"}], [{"object": "block"}]],
                )

        deleted_urls = [url for method, url, _data in calls if method == "DELETE"]
        self.assertEqual(
            deleted_urls,
            ["https://api.notion.com/v1/blocks/new-a"],
        )

    def test_old_block_cleanup_failure_does_not_advance_sync_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("new body\n")

            sync_key = "subject::stable::Knowledge"
            state = {
                "pages": {
                    sync_key: {
                        "url": "https://www.notion.so/stable",
                        "content_hash": "old-hash",
                    }
                }
            }

            def fake_api(url, _token, method="GET", data=None, **_kwargs):
                if method == "GET":
                    return {"results": [{"id": "old-a"}], "has_more": False}
                if method == "PATCH" and "/blocks/stable-page/children" in url:
                    return {"results": [{"id": "new-a"}]}
                if method == "PATCH" and url.endswith("/pages/stable-page"):
                    return {"id": "stable-page"}
                if method == "DELETE" and url.endswith("/blocks/old-a"):
                    raise RuntimeError("delete failed")
                raise AssertionError(f"Unexpected API call: {method} {url}")

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "stable-page",
                    "url": "https://www.notion.so/stable",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[{"object": "block"}],
            ), patch.object(
                notion_api,
                "notion_api_request",
                side_effect=fake_api,
            ):
                with self.assertRaisesRegex(RuntimeError, "sync hash was not advanced"):
                    create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        available_properties={"Sync Key"},
                        sync_key=sync_key,
                        page_kind="Subject",
                        category_path="Knowledge",
                        sync_state=state,
                    )

        self.assertEqual(state["pages"][sync_key]["content_hash"], "old-hash")

    def test_block_listing_follows_pagination(self):
        responses = [
            {
                "results": [{"id": "block-a"}],
                "has_more": True,
                "next_cursor": "cursor-a",
            },
            {
                "results": [{"id": "block-b"}],
                "has_more": False,
                "next_cursor": None,
            },
        ]
        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=responses,
        ) as api:
            block_ids = sync_to_notion.get_top_level_block_ids(
                "token",
                "page-a",
            )

        self.assertEqual(block_ids, ["block-a", "block-b"])
        self.assertEqual(api.call_count, 2)
        self.assertIn("start_cursor=cursor-a", api.call_args_list[1].args[0])

    def test_retry_replaces_a_mixed_old_and_new_snapshot(self):
        calls = []

        def fake_api(url, _token, method="GET", data=None, **_kwargs):
            calls.append((method, url, data))
            if method == "GET":
                return {
                    "results": [
                        {"id": "remaining-old"},
                        {"id": "previous-new"},
                    ],
                    "has_more": False,
                }
            if method == "PATCH" and "/blocks/page-a/children" in url:
                return {"results": [{"id": "complete-new"}]}
            if method == "PATCH" and url.endswith("/pages/page-a"):
                return {"id": "page-a"}
            if method == "DELETE":
                return {"archived": True}
            raise AssertionError(f"Unexpected API call: {method} {url}")

        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=fake_api,
        ):
            sync_to_notion.replace_page_content_in_place(
                "token",
                "page-a",
                {"Name": {"title": []}},
                [[{"object": "block"}]],
            )

        deleted_ids = [
            url.rsplit("/", 1)[-1]
            for method, url, _data in calls
            if method == "DELETE"
        ]
        self.assertEqual(deleted_ids, ["remaining-old", "previous-new"])

    def test_sync_run_is_incomplete_for_failure_or_unresolved_link(self):
        stage = SyncStageResult(stage="Subject", expected=1, succeeded=1)
        self.assertTrue(is_sync_run_complete([stage]))

        stage.unresolved_links.append({"source_path": "Subject/a.md", "target": "Daily/a"})
        self.assertFalse(is_sync_run_complete([stage]))

        stage.unresolved_links.clear()
        stage.failures.append(SyncFailure("Subject", "Subject/a.md", "failed"))
        self.assertFalse(is_sync_run_complete([stage]))

    def test_orphan_cleanup_gate_requires_complete_stages(self):
        complete = SyncStageResult(stage="Daily", expected=1, succeeded=1)
        incomplete = SyncStageResult(stage="Subject", expected=1, succeeded=0)
        self.assertTrue(should_run_orphan_cleanup(False, [complete]))
        self.assertFalse(should_run_orphan_cleanup(True, [complete]))
        self.assertFalse(should_run_orphan_cleanup(False, [complete, incomplete]))

    def test_page_id_normalization_and_url_only_state_backfill(self):
        hyphenated = "12345678-1234-1234-1234-1234567890AB"
        compact = "123456781234123412341234567890ab"
        state = {
            "pages": {
                "daily::a": {
                    "url": f"https://www.notion.so/Example-{compact}"
                }
            }
        }

        self.assertEqual(normalize_notion_page_id(hyphenated), compact)
        self.assertEqual(backfill_sync_state_page_ids(state), 1)
        self.assertEqual(state["pages"]["daily::a"]["page_id"], compact)

    def test_canonical_selection_prefers_state_page_regardless_of_result_order(self):
        page_a = {"id": "page-a", "created_time": "2024-01-01T00:00:00.000Z"}
        page_b = {"id": "page-b", "created_time": "2025-01-01T00:00:00.000Z"}
        state_entry = {"page_id": "page-b"}

        for pages in ([page_a, page_b], [page_b, page_a]):
            selection = select_canonical_notion_page(pages, state_entry)
            self.assertEqual(selection.page["id"], "page-b")
            self.assertEqual(selection.reason, "sync state page_id")

    def test_query_existing_page_uses_state_canonical_page(self):
        pages = [{"id": "old-page"}, {"id": "current-page"}]
        with patch.object(
            sync_to_notion,
            "query_pages_by_property",
            return_value=pages,
        ):
            selected = query_existing_page(
                "token",
                "database",
                "daily::a",
                state_entry={"page_id": "current-page"},
            )

        self.assertEqual(selected["id"], "current-page")

    def test_query_pages_by_property_paginates_duplicate_results(self):
        first_page = {
            "results": [{"id": f"page-{index}"} for index in range(100)],
            "has_more": True,
            "next_cursor": "cursor-2",
        }
        second_page = {
            "results": [{"id": "page-100"}],
            "has_more": False,
            "next_cursor": None,
        }
        with patch.object(
            notion_api,
            "notion_api_request",
            side_effect=[first_page, second_page],
        ) as api:
            pages = query_pages_by_property(
                "token",
                "database",
                "Sync Key",
                "daily::a",
            )

        self.assertEqual(len(pages), 101)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args_list[1].kwargs["data"]["start_cursor"], "cursor-2")

    def test_cleanup_plan_keeps_state_page_regardless_of_notion_order(self):
        state = {"pages": {"daily::a": {"page_id": "page-b"}}}
        for pages in (["page-a", "page-b"], ["page-b", "page-a"]):
            plan = build_orphan_cleanup_plan(
                {"daily::a": pages},
                ["daily::a"],
                sync_state=state,
            )
            self.assertEqual(plan.canonical_pages[0]["page_id"], "page-b")
            self.assertEqual(
                [candidate["page_id"] for candidate in plan.candidates],
                ["page-a"],
            )

    def test_cleanup_plan_blocks_unresolved_state_identity_even_with_override(self):
        plan = build_orphan_cleanup_plan(
            {"daily::a": ["page-a", "page-b"]},
            ["daily::a"],
            sync_state={"pages": {"daily::a": {"page_id": "missing-page"}}},
        )

        allowed, reason = assess_orphan_cleanup_safety(
            plan,
            allow_large_cleanup=True,
        )

        self.assertFalse(allowed)
        self.assertIn("identity is unresolved", reason)
        self.assertEqual(plan.candidates, [])
        self.assertEqual(plan.conflicts[0]["page_ids"], ["page-a", "page-b"])

    def test_state_free_duplicate_bootstrap_keeps_oldest_page(self):
        newer = {"id": "newer", "created_time": "2025-01-01T00:00:00.000Z"}
        older = {"id": "older", "created_time": "2024-01-01T00:00:00.000Z"}
        plan = build_orphan_cleanup_plan(
            {"daily::a": [newer, older]},
            ["daily::a"],
        )

        self.assertEqual(plan.canonical_pages[0]["page_id"], "older")
        self.assertEqual(plan.candidates[0]["page_id"], "newer")

    def test_orphan_cleanup_guard_blocks_empty_active_inventory(self):
        plan = build_orphan_cleanup_plan(
            {
                "daily::a": ["page-a"],
                "subject::b::Knowledge": ["page-b"],
            },
            [],
        )

        allowed, reason = assess_orphan_cleanup_safety(plan)

        self.assertFalse(allowed)
        self.assertIn("No active local Sync Keys", reason)
        self.assertEqual(plan.candidate_count, 2)

    def test_orphan_cleanup_guard_blocks_large_candidate_ratio(self):
        pages = {
            f"daily::{index}": [f"page-{index}"]
            for index in range(50)
        }
        active_keys = [f"daily::{index}" for index in range(40)]
        plan = build_orphan_cleanup_plan(pages, active_keys)

        allowed, reason = assess_orphan_cleanup_safety(plan)

        self.assertFalse(allowed)
        self.assertIn("10/50", reason)
        self.assertEqual(plan.candidate_ratio, 0.2)

    def test_orphan_cleanup_guard_allows_small_cleanup_or_explicit_override(self):
        pages = {
            f"daily::{index}": [f"page-{index}"]
            for index in range(50)
        }
        small_plan = build_orphan_cleanup_plan(
            pages,
            [f"daily::{index}" for index in range(41)],
        )
        empty_plan = build_orphan_cleanup_plan(pages, [])

        self.assertTrue(assess_orphan_cleanup_safety(small_plan)[0])
        self.assertTrue(
            assess_orphan_cleanup_safety(
                empty_plan,
                allow_large_cleanup=True,
            )[0]
        )

    def test_orphan_cleanup_plan_report_lists_blocked_candidates(self):
        plan = build_orphan_cleanup_plan(
            {"daily::a": ["page-a"]},
            [],
            ["legacy-page"],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "cleanup-plan.md")
            write_orphan_cleanup_plan_report(
                report_path,
                plan,
                "blocked by safety guard",
                "No active local Sync Keys remain.",
            )
            with open(report_path, encoding="utf-8") as file_obj:
                report = file_obj.read()

        self.assertIn("blocked by safety guard", report)
        self.assertIn("daily::a", report)
        self.assertIn("legacy-page", report)

    def test_incomplete_sync_downgrades_cloudinary_delete_to_report(self):
        args = SimpleNamespace(
            subject_dir="Subject",
            review_dir="Topic_Reviews",
            cloudinary_cleanup_limit=0,
            cloudinary_cleanup_invalidate=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            sync_cleanup,
            "resolve_cloudinary_cleanup_mode",
            return_value="auto",
        ), patch.object(
            cloudinary_cleanup,
            "load_cache",
            return_value={},
        ), patch.object(
            cloudinary_cleanup,
            "scan_live_images",
            return_value={
                "live_sha1s": set(),
                "live_filenames": set(),
                "missing_filenames": set(),
                "live_cloudinary_urls": set(),
                "markdown_files": 0,
                "image_refs": 0,
                "missing_refs": [],
            },
        ), patch.object(
            cloudinary_cleanup,
            "destroy_cloudinary_asset",
        ) as destroy:
            run_cloudinary_cleanup_after_sync(
                args,
                temp_dir,
                temp_dir,
                daily_only_mode=False,
                allow_delete=False,
            )

        destroy.assert_not_called()

    def test_notion_api_retries_retryable_http_error(self):
        error = urllib.error.HTTPError(
            "https://api.notion.com/test",
            503,
            "unavailable",
            {"Retry-After": "0"},
            io.BytesIO(b'{"message":"busy"}'),
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'

        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=[error, response],
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            result = notion_api_request(
                "https://api.notion.com/test",
                "token",
                max_attempts=2,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_notion_api_does_not_retry_permanent_http_error(self):
        error = urllib.error.HTTPError(
            "https://api.notion.com/test",
            400,
            "bad request",
            {},
            io.BytesIO(b'{"message":"bad"}'),
        )
        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=error,
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                notion_api_request(
                    "https://api.notion.com/test",
                    "token",
                    max_attempts=4,
                )

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_cleanup_reports_archive_failures(self):
        with patch.object(
            sync_cleanup,
            "archive_notion_page",
            side_effect=[True, False],
        ):
            result = cleanup_orphan_pages(
                "token",
                "database",
                {"orphan::a": ["page-a", "page-b"]},
                [],
            )
        self.assertEqual(result, {"archived": 1, "failed": 1})

    def test_partial_failure_report_contains_unresolved_links(self):
        stage = SyncStageResult(
            stage="Subject",
            expected=1,
            succeeded=1,
            unresolved_links=[
                {"source_path": "Subject/a.md", "target": "Daily_Logs/a"}
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = os.path.join(temp_dir, "notion_sync_report.md")
            write_notion_sync_report(
                report_path,
                [stage],
                "skipped because sync was incomplete",
                False,
            )
            with open(report_path, encoding="utf-8") as file_obj:
                report = file_obj.read()

        self.assertIn("partial failure", report)
        self.assertIn("Subject/a.md", report)
        self.assertIn("Daily_Logs/a", report)


if __name__ == "__main__":
    unittest.main()
