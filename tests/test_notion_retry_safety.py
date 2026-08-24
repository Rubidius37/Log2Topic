import io
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import notion_api  # noqa: E402
import sync_to_notion  # noqa: E402


class NotionRetrySafetyTests(unittest.TestCase):
    @staticmethod
    def make_http_error(status, body=b'{"message":"temporary"}'):
        return urllib.error.HTTPError(
            "https://api.notion.com/test",
            status,
            "error",
            {"Retry-After": "0"},
            io.BytesIO(body),
        )

    @staticmethod
    def make_response(payload=b'{"ok":true}'):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        return response

    def test_safe_post_retries_server_error(self):
        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=[self.make_http_error(503), self.make_response()],
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            result = notion_api.notion_api_request(
                "https://api.notion.com/v1/databases/database/query",
                "token",
                method="POST",
                data={"page_size": 100},
                max_attempts=2,
                retry_mode=notion_api.NOTION_RETRY_SAFE,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_non_idempotent_write_does_not_retry_server_error(self):
        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=self.make_http_error(503),
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            with self.assertRaisesRegex(
                notion_api.NotionAmbiguousWriteError,
                "may have applied.*create page.*was not retried",
            ):
                notion_api.notion_api_request(
                    "https://api.notion.com/v1/pages",
                    "token",
                    method="POST",
                    data={"properties": {}},
                    retry_mode=notion_api.NOTION_RETRY_NON_IDEMPOTENT,
                    operation_name="create page",
                )

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_non_idempotent_write_does_not_retry_lost_response(self):
        error = urllib.error.URLError(TimeoutError("timed out"))
        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=error,
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            with self.assertRaisesRegex(
                notion_api.NotionAmbiguousWriteError,
                "append block chunk.*response was lost",
            ):
                notion_api.notion_api_request(
                    "https://api.notion.com/v1/blocks/page/children",
                    "token",
                    method="PATCH",
                    data={"children": []},
                    retry_mode=notion_api.NOTION_RETRY_NON_IDEMPOTENT,
                    operation_name="append block chunk",
                )

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_non_idempotent_write_still_retries_explicit_rate_limit(self):
        with patch.object(
            notion_api.urllib.request,
            "urlopen",
            side_effect=[self.make_http_error(429), self.make_response()],
        ) as urlopen, patch.object(notion_api.time, "sleep") as sleep:
            result = notion_api.notion_api_request(
                "https://api.notion.com/v1/pages",
                "token",
                method="POST",
                data={"properties": {}},
                max_attempts=2,
                retry_mode=notion_api.NOTION_RETRY_NON_IDEMPOTENT,
                operation_name="create page",
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_append_blocks_declares_non_idempotent_retry_policy(self):
        chunk = [{"object": "block", "type": "paragraph"}]
        with patch.object(
            notion_api,
            "notion_api_request",
            return_value={"results": [{"id": "new-block"}]},
        ) as api:
            block_ids = notion_api.append_block_chunks(
                "token",
                "page-id",
                [chunk],
            )

        self.assertEqual(block_ids, ["new-block"])
        self.assertEqual(
            api.call_args.kwargs["retry_mode"],
            notion_api.NOTION_RETRY_NON_IDEMPOTENT,
        )

    def test_ambiguous_append_keeps_last_successful_sync_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Subject/Knowledge/note.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("updated body\n")

            sync_key = "subject::stable::Knowledge"
            original_entry = {
                "url": "https://www.notion.so/stable",
                "page_id": "stable-page",
                "content_hash": "last-successful-hash",
            }
            state = {"pages": {sync_key: dict(original_entry)}}
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
                return_value=[{"object": "block", "type": "paragraph"}],
            ), patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
                side_effect=sync_to_notion.NotionAmbiguousWriteError(
                    "append result is unknown"
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "append result is unknown",
                ):
                    sync_to_notion.create_or_update_notion_page(
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

        self.assertEqual(state["pages"][sync_key], original_entry)

    def test_ambiguous_create_is_recovered_by_sync_key_on_next_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Daily_Logs/new.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("new body\n")

            sync_key = "daily::new"
            state = {"pages": {}}
            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value=None,
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[],
            ), patch.object(
                sync_to_notion,
                "notion_api_request",
                side_effect=sync_to_notion.NotionAmbiguousWriteError(
                    "create result is unknown"
                ),
            ):
                with self.assertRaises(sync_to_notion.NotionAmbiguousWriteError):
                    sync_to_notion.create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        available_properties={"Sync Key"},
                        sync_key=sync_key,
                        page_kind="Daily",
                        sync_state=state,
                    )

            self.assertEqual(state, {"pages": {}})

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value={
                    "id": "recovered-page",
                    "url": "https://www.notion.so/recovered-page",
                },
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[],
            ), patch.object(
                sync_to_notion,
                "replace_page_content_in_place",
            ) as replace_page:
                page_url = sync_to_notion.create_or_update_notion_page(
                    "token",
                    "database",
                    full_path,
                    rel_path,
                    available_properties={"Sync Key"},
                    sync_key=sync_key,
                    page_kind="Daily",
                    sync_state=state,
                )

        self.assertEqual(page_url, "https://www.notion.so/recovered-page")
        replace_page.assert_called_once()
        self.assertEqual(state["pages"][sync_key]["page_id"], "recovered-page")

    def test_new_page_content_failure_rolls_back_and_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rel_path = "Daily_Logs/new.md"
            full_path = os.path.join(temp_dir, *rel_path.split("/"))
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("new body\n")

            state = {"pages": {}}
            create_payloads = []

            def fake_create(_url, _token, method="GET", data=None, **_kwargs):
                self.assertEqual(method, "POST")
                create_payloads.append(data)
                return {
                    "id": "partial-page",
                    "url": "https://www.notion.so/partial-page",
                }

            def fail_append(_token, _page_id, _chunks, appended_ids):
                appended_ids.append("partial-root")
                raise RuntimeError("child upload failed")

            with patch.object(
                sync_to_notion,
                "query_existing_page",
                return_value=None,
            ), patch.object(
                sync_to_notion,
                "markdown_to_notion_blocks",
                return_value=[{"object": "block", "type": "paragraph"}],
            ), patch.object(
                sync_to_notion,
                "notion_api_request",
                side_effect=fake_create,
            ), patch.object(
                sync_to_notion,
                "append_block_chunks",
                side_effect=fail_append,
            ), patch.object(
                sync_to_notion,
                "delete_notion_blocks",
                return_value=[],
            ) as delete_blocks:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "same Sync Key will repair this page",
                ):
                    sync_to_notion.create_or_update_notion_page(
                        "token",
                        "database",
                        full_path,
                        rel_path,
                        available_properties={"Sync Key"},
                        sync_key="daily::new",
                        page_kind="Daily",
                        sync_state=state,
                    )

        self.assertNotIn("children", create_payloads[0])
        delete_blocks.assert_called_once_with("token", ["partial-root"])
        self.assertEqual(state, {"pages": {}})


if __name__ == "__main__":
    unittest.main()
