import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from classification_review_dashboard import (  # noqa: E402
    ClassificationReviewHandler,
    DashboardLifecycle,
    ReviewError,
    add_classification_rule,
    apply_manual_categories,
    build_category_list,
    build_review_items,
    is_local_host,
    is_local_origin,
    merge_unit_into_previous,
    remove_manual_categories,
    resolve_source_path,
    resolve_ui_language,
)
from hierarchical_classifier import (  # noqa: E402
    METADATA_SCHEMA_VERSION,
    classify_unit,
    make_source_anchor,
    parse_markdown_into_units,
    parse_rules_from_markdown,
    source_unit_fingerprint,
)


RULES = """\
| Level 1 | Level 2 | Level 3 | Level 4 | Level 5 | Keywords |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Projects | Project Alpha | | | | Project Alpha |
| | | Testing | | | testing |
| Knowledge | Analysis | Qualitative | | | qualitative analysis |
"""


class ClassificationReviewDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.vault_dir = self.temp_dir.name
        self.scripts_dir = os.path.join(self.vault_dir, "scripts")
        self.daily_dir = os.path.join(self.vault_dir, "Daily_Logs", "2026-08")
        os.makedirs(self.scripts_dir)
        os.makedirs(self.daily_dir)
        self.rules_path = os.path.join(self.vault_dir, "Classification_Rules.md")
        self.metadata_path = os.path.join(self.scripts_dir, "organizer_metadata.json")
        self.backup_dir = os.path.join(self.scripts_dir, "backups")
        with open(self.rules_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(RULES)
        self.tree = parse_rules_from_markdown(self.rules_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_log(self, content, filename="260814 일지.md"):
        path = os.path.join(self.daily_dir, filename)
        with open(path, "w", encoding="utf-8", newline="\n") as file_obj:
            file_obj.write(content)
        return path

    def write_metadata_for_unit(self, filepath, source_id, unit):
        source_rel_path = os.path.relpath(filepath, self.vault_dir).replace("\\", "/")
        classification = classify_unit(unit, self.tree)
        entry = {
            "source_path": source_rel_path,
            "source_log": os.path.splitext(os.path.basename(filepath))[0],
            "source_heading": unit.title,
            "source_heading_path": list(unit.heading_path),
            "source_line": unit.start_line,
            "source_anchor": make_source_anchor(source_rel_path, unit),
            "source_fingerprint": source_unit_fingerprint(unit),
            "primary_category": list(classification["primary_path"]),
            "needs_review": classification["needs_review"],
            "review_reasons": list(classification["issues"]),
            "matched_categories": [
                {
                    "path": list(path),
                    "basis": classification["basis_by_path"][path],
                }
                for path in classification["paths"]
            ],
            "generated_paths": [],
        }
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "entries": {source_id: entry},
        }
        with open(self.metadata_path, "w", encoding="utf-8") as file_obj:
            json.dump(metadata, file_obj, ensure_ascii=False)
        return entry

    def test_parent_category_review_comes_from_metadata_not_unclassified_folder(self):
        source_id = "abcdef1234567890"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "기능 동작을 검토했다.\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = next(value for value in units if value.title == "Project Alpha")
        self.write_metadata_for_unit(filepath, source_id, unit)

        items = build_review_items(self.vault_dir, self.metadata_path, self.rules_path)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["review_kind"], "parent-category")
        self.assertNotIn("research-notes-source-id", items[0]["content"])
        self.assertEqual(items[0]["current_categories"], [["Projects", "Project Alpha"]])

    def test_dashboard_language_uses_saved_setting(self):
        settings_path = os.path.join(self.temp_dir.name, "tray_settings.json")
        with open(settings_path, "w", encoding="utf-8") as file_obj:
            json.dump({"ui_language": "en"}, file_obj)
        self.assertEqual("en", resolve_ui_language(settings_path))
        with open(settings_path, "w", encoding="utf-8") as file_obj:
            json.dump({"ui_language": "ko"}, file_obj)
        self.assertEqual("ko", resolve_ui_language(settings_path))

    def test_apply_uses_source_id_for_level_three_and_supports_multiple_paths(self):
        source_id = "0123456789abcdef"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            "### Testing\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "테스트와 정성 분석의 관계를 검토했다.\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = next(value for value in units if value.title == "Testing")
        self.write_metadata_for_unit(filepath, source_id, unit)

        result = apply_manual_categories(
            source_id,
            [
                ["Projects", "Project Alpha", "Testing"],
                ["Knowledge", "Analysis", "Qualitative"],
            ],
            source_unit_fingerprint(unit),
            self.vault_dir,
            self.metadata_path,
            self.rules_path,
            self.backup_dir,
        )

        self.assertTrue(result["changed"])
        with open(filepath, "r", encoding="utf-8") as file_obj:
            updated = file_obj.read()
        self.assertIn(
            "Category: Projects/Project Alpha/Testing, Knowledge/Analysis/Qualitative",
            updated,
        )
        self.assertLess(updated.index("research-notes-source-id"), updated.index("Category:"))
        self.assertTrue(os.path.exists(os.path.join(self.vault_dir, *result["backup_path"].split("/"))))

        _log_name, updated_units = parse_markdown_into_units(filepath, self.tree)
        updated_unit = next(value for value in updated_units if value.title == "Testing")
        classification = classify_unit(updated_unit, self.tree)
        self.assertFalse(classification["needs_review"])
        self.assertEqual(
            set(classification["paths"]),
            {
                ("Projects", "Project Alpha", "Testing"),
                ("Knowledge", "Analysis", "Qualitative"),
            },
        )

    def test_stale_fingerprint_rejects_edit_without_changing_source(self):
        source_id = "fedcba9876543210"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "기존 내용\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = next(value for value in units if value.title == "Project Alpha")
        self.write_metadata_for_unit(filepath, source_id, unit)
        with open(filepath, "a", encoding="utf-8") as file_obj:
            file_obj.write("화면을 연 뒤 추가된 내용\n")
        with open(filepath, "r", encoding="utf-8") as file_obj:
            before = file_obj.read()

        with self.assertRaises(ReviewError) as context:
            apply_manual_categories(
                source_id,
                [["Projects", "Project Alpha", "Testing"]],
                source_unit_fingerprint(unit),
                self.vault_dir,
                self.metadata_path,
                self.rules_path,
                self.backup_dir,
            )

        self.assertEqual(context.exception.status, 409)
        with open(filepath, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), before)

    def test_unknown_category_is_rejected_without_changing_source(self):
        source_id = "aaaabbbbccccdddd"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "내용\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = next(value for value in units if value.title == "Project Alpha")
        self.write_metadata_for_unit(filepath, source_id, unit)
        with open(filepath, "r", encoding="utf-8") as file_obj:
            before = file_obj.read()

        with self.assertRaises(ReviewError):
            apply_manual_categories(
                source_id,
                [["Projects", "Unknown"]],
                source_unit_fingerprint(unit),
                self.vault_dir,
                self.metadata_path,
                self.rules_path,
                self.backup_dir,
            )

        with open(filepath, "r", encoding="utf-8") as file_obj:
            self.assertEqual(file_obj.read(), before)

    def test_source_path_must_stay_under_daily_logs(self):
        outside = os.path.join(self.vault_dir, "Classification_Rules.md")
        self.assertTrue(os.path.exists(outside))
        with self.assertRaises(ReviewError):
            resolve_source_path(self.vault_dir, "Daily_Logs/../Classification_Rules.md")

    def test_document_root_override_preserves_yaml_frontmatter(self):
        source_id = "1111222233334444"
        filepath = self.write_log(
            "---\n"
            "date: 2026-08-14\n"
            "---\n"
            "Heading이 없는 원본 내용\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = units[0]
        self.write_metadata_for_unit(filepath, source_id, unit)

        apply_manual_categories(
            source_id,
            [["Knowledge"]],
            source_unit_fingerprint(unit),
            self.vault_dir,
            self.metadata_path,
            self.rules_path,
            self.backup_dir,
        )

        with open(filepath, "r", encoding="utf-8") as file_obj:
            updated = file_obj.read().splitlines()
        self.assertEqual(updated[0], "---")
        self.assertEqual(updated[1], "Category: Knowledge")
        self.assertEqual(updated[3], "---")

    def test_category_list_exposes_all_five_level_metadata_fields(self):
        categories = build_category_list(self.tree)
        testing = next(
            value
            for value in categories
            if value["path"] == ["Projects", "Project Alpha", "Testing"]
        )
        self.assertEqual(testing["depth"], 3)
        self.assertTrue(testing["selectable"])
        self.assertTrue(all(value["selectable"] for value in categories))

    def test_dashboard_closes_after_the_last_browser_session(self):
        class FakeServer:
            def __init__(self):
                self.shutdown_called = threading.Event()

            def shutdown(self):
                self.shutdown_called.set()

        server = FakeServer()
        lifecycle = DashboardLifecycle(close_delay=0.03)
        lifecycle.attach(server)
        try:
            lifecycle.open("session_12345678")
            lifecycle.open("session_abcdefgh")
            lifecycle.close("session_12345678")
            self.assertFalse(server.shutdown_called.wait(0.08))
            lifecycle.close("session_abcdefgh")
            self.assertTrue(server.shutdown_called.wait(0.5))
        finally:
            lifecycle.stop()

    def test_dashboard_reload_cancels_pending_shutdown(self):
        class FakeServer:
            def __init__(self):
                self.shutdown_called = threading.Event()

            def shutdown(self):
                self.shutdown_called.set()

        server = FakeServer()
        lifecycle = DashboardLifecycle(close_delay=0.08)
        lifecycle.attach(server)
        try:
            lifecycle.open("session_12345678")
            lifecycle.close("session_12345678")
            time.sleep(0.02)
            lifecycle.open("session_12345678")
            self.assertFalse(server.shutdown_called.wait(0.12))
        finally:
            lifecycle.stop()

    def test_dashboard_waits_for_active_classification_before_shutdown(self):
        class FakeServer:
            def __init__(self):
                self.shutdown_called = threading.Event()

            def shutdown(self):
                self.shutdown_called.set()

        busy = threading.Event()
        busy.set()
        server = FakeServer()
        lifecycle = DashboardLifecycle(close_delay=0.03, busy_check=busy.is_set)
        lifecycle.attach(server)
        try:
            lifecycle.open("session_12345678")
            lifecycle.close("session_12345678")
            self.assertFalse(server.shutdown_called.wait(0.1))
            busy.clear()
            self.assertTrue(server.shutdown_called.wait(0.5))
        finally:
            lifecycle.stop()

    def test_dashboard_watch_connection_closes_server(self):
        class QuietHandler(ClassificationReviewHandler):
            def log_message(self, _format_string, *_args):
                pass

        server = None
        lifecycle = DashboardLifecycle(close_delay=0.03)
        thread = None
        connection = None
        response = None
        try:
            from http.server import ThreadingHTTPServer

            server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
            lifecycle.attach(server)
            server.dashboard_lifecycle = lifecycle
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            connection.request("GET", "/api/session/watch?session_id=session_12345678")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(2), b": ")
            response.close()
            connection.close()
            response = None
            connection = None

            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        finally:
            if response is not None:
                response.close()
            if connection is not None:
                connection.close()
            lifecycle.stop()
            if server is not None:
                if thread is not None and thread.is_alive():
                    server.shutdown()
                    thread.join(timeout=2)
                server.server_close()

    def test_remove_manual_categories_restores_heading_based_classification(self):
        source_id = "9999888877776666"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            "### Testing\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "Category: Projects/Unknown\n"
            "내용\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        unit = next(value for value in units if value.title == "Testing")
        self.write_metadata_for_unit(filepath, source_id, unit)

        items = build_review_items(self.vault_dir, self.metadata_path, self.rules_path)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["has_manual_category"])
        self.assertEqual(items[0]["review_kind"], "invalid-manual")

        result = remove_manual_categories(
            source_id,
            source_unit_fingerprint(unit),
            self.vault_dir,
            self.metadata_path,
            self.rules_path,
            self.backup_dir,
        )
        self.assertTrue(result["changed"])
        with open(filepath, "r", encoding="utf-8") as file_obj:
            updated = file_obj.read()
        self.assertNotIn("Category:", updated)

        _log_name, updated_units = parse_markdown_into_units(filepath, self.tree)
        updated_unit = next(value for value in updated_units if value.title == "Testing")
        classification = classify_unit(updated_unit, self.tree)
        self.assertFalse(classification["needs_review"])
        self.assertEqual(classification["paths"], [("Projects", "Project Alpha", "Testing")])

    def test_add_classification_rule_updates_table_and_preserves_existing_rules(self):
        result = add_classification_rule(
            "projects / Project Alpha / Deployment",
            keywords="deploy, release",
            vault_dir=self.vault_dir,
            rules_path=self.rules_path,
            backup_dir=self.backup_dir,
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["path"], ["Projects", "Project Alpha", "Deployment"])

        updated_tree = parse_rules_from_markdown(self.rules_path)
        self.assertFalse(updated_tree.errors)
        self.assertIn(("Projects", "Project Alpha", "Deployment"), updated_tree.nodes)
        self.assertIn(("Projects", "Project Alpha", "Testing"), updated_tree.nodes)
        self.assertIn(("Knowledge", "Analysis", "Qualitative"), updated_tree.nodes)

        with self.assertRaises(ReviewError):
            add_classification_rule(
                ["Projects", "Project Alpha", "Deployment"],
                vault_dir=self.vault_dir,
                rules_path=self.rules_path,
                backup_dir=self.backup_dir,
            )

    def test_dns_rebinding_host_and_origin_validation(self):
        self.assertTrue(is_local_host("127.0.0.1:8000"))
        self.assertTrue(is_local_host("localhost:8000"))
        self.assertTrue(is_local_host("[::1]:8000"))
        self.assertFalse(is_local_host("evil.example.com:8000"))
        self.assertFalse(is_local_host(""))
        self.assertFalse(is_local_origin("", allow_empty=False))
        self.assertFalse(is_local_origin("https://evil.example.com", allow_empty=False))
        self.assertTrue(is_local_origin("http://127.0.0.1:8000", allow_empty=False))

    def test_merge_unit_into_previous_inserts_merge_above_marker(self):
        source_id = "abababab12121212"
        filepath = self.write_log(
            "# Projects\n"
            "## Project Alpha\n"
            "### Testing\n"
            "기능 테스트 본문\n"
            "# 분석 결과\n"
            f"<!-- research-notes-source-id: {source_id} -->\n"
            "AI 답변 본문\n"
            "### 세부 분석 항목\n"
            "세부 항목 본문\n"
        )
        _log_name, units = parse_markdown_into_units(filepath, self.tree)
        ai_unit = next(u for u in units if u.title == "분석 결과")
        self.write_metadata_for_unit(filepath, source_id, ai_unit)

        items = build_review_items(self.vault_dir, self.metadata_path, self.rules_path)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["can_merge_above"])

        res = merge_unit_into_previous(
            source_id,
            source_unit_fingerprint(ai_unit),
            self.vault_dir,
            self.metadata_path,
            self.rules_path,
            self.backup_dir,
        )
        self.assertTrue(res["changed"])
        _log_name, merged_units = parse_markdown_into_units(filepath, self.tree)
        testing_unit = next(u for u in merged_units if u.title == "Testing")
        classified = classify_unit(testing_unit, self.tree)
        self.assertIn("# 분석 결과", classified["content"])
        self.assertIn("AI 답변 본문", classified["content"])
        self.assertIn("### 세부 분석 항목", classified["content"])
        self.assertIn("세부 항목 본문", classified["content"])
        self.assertNotIn("research-notes-merge-above", classified["content"])


if __name__ == "__main__":
    unittest.main()
