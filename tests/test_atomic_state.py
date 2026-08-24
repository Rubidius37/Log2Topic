import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import atomic_io  # noqa: E402
import hierarchical_classifier  # noqa: E402
import notion_state  # noqa: E402
import sync_to_notion  # noqa: E402


PNG_HEADER = b"\x89PNG\r\n\x1a\n"
from atomic_io import StateFileError, atomic_write_json, load_json_state  # noqa: E402


class AtomicStateTests(unittest.TestCase):
    def test_atomic_json_successfully_replaces_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "state.json")
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write('{"old": true}')

            atomic_write_json(path, {"new": "값"})

            with open(path, "r", encoding="utf-8") as file_obj:
                self.assertEqual(json.load(file_obj), {"new": "값"})
            self.assertEqual(os.listdir(temp_dir), ["state.json"])

    def test_replace_failure_preserves_old_file_and_removes_temp_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "state.json")
            original = '{"stable": true}'
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write(original)

            with patch.object(
                atomic_io.os,
                "replace",
                side_effect=PermissionError("replace blocked"),
            ):
                with self.assertRaises(PermissionError):
                    atomic_write_json(path, {"new": True})

            with open(path, "r", encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), original)
            self.assertEqual(os.listdir(temp_dir), ["state.json"])

    def test_serialization_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "state.json")
            original = '{"stable": true}'
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write(original)

            with self.assertRaises(StateFileError):
                atomic_write_json(path, {"unsupported": object()})

            with open(path, "r", encoding="utf-8") as file_obj:
                self.assertEqual(file_obj.read(), original)
            self.assertEqual(os.listdir(temp_dir), ["state.json"])

    def test_missing_state_uses_default_but_malformed_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "state.json")
            self.assertEqual(
                load_json_state(path, {"pages": {}}, label="test state"),
                {"pages": {}},
            )
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write('{"pages":')

            with self.assertRaises(StateFileError):
                load_json_state(path, {"pages": {}}, label="test state")

    def test_notion_state_rejects_invalid_pages_shape(self):
        with tempfile.TemporaryDirectory() as script_dir:
            path = os.path.join(script_dir, "state.json")
            with open(path, "w", encoding="utf-8") as file_obj:
                json.dump({"pages": []}, file_obj)

            with self.assertRaises(StateFileError):
                sync_to_notion.load_notion_sync_state(script_dir, "state.json")

    def test_malformed_cloudinary_cache_fails_instead_of_resetting(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            script_dir = os.path.join(vault_dir, "scripts")
            os.makedirs(script_dir)
            with open(
                os.path.join(script_dir, "cloudinary_cache.json"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write('{"sha1:broken":')

            sync_to_notion._cloudinary_cache = None
            try:
                with self.assertRaises(StateFileError):
                    sync_to_notion.load_cloudinary_cache(vault_dir)
            finally:
                sync_to_notion._cloudinary_cache = None

    def test_cloudinary_cache_save_failure_is_not_hidden(self):
        with tempfile.TemporaryDirectory() as vault_dir, patch.object(
            sync_to_notion,
            "atomic_write_json",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaises(sync_to_notion.CloudinaryUploadError) as raised:
                sync_to_notion.save_cloudinary_cache(vault_dir, {"sha1:test": {}})

        self.assertIn("disk full", str(raised.exception))

    def test_failed_cloudinary_cache_save_rolls_back_in_memory_entries(self):
        with tempfile.TemporaryDirectory() as vault_dir:
            script_dir = os.path.join(vault_dir, "scripts")
            os.makedirs(script_dir)
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
                    return_value="https://example.test/image.png",
                ), patch.object(
                    sync_to_notion,
                    "save_cloudinary_cache",
                    side_effect=sync_to_notion.CloudinaryUploadError("disk full"),
                ):
                    with self.assertRaises(sync_to_notion.CloudinaryUploadError):
                        sync_to_notion.get_or_upload_cloudinary_image(
                            image_path,
                            {"cloud_name": "demo", "upload_preset": "preset"},
                            vault_dir,
                        )

                self.assertEqual(sync_to_notion._cloudinary_cache, {})
            finally:
                sync_to_notion._cloudinary_cache = None

    def test_checkpoint_failure_is_recorded_as_incomplete_stage(self):
        stage_results = []
        with patch.object(
            notion_state,
            "save_notion_sync_state",
            side_effect=OSError("disk full"),
        ):
            saved = sync_to_notion.save_sync_state_checkpoint(
                "scripts",
                {"pages": {}},
                "state.json",
                stage_results,
                "Daily sync",
            )

        self.assertFalse(saved)
        self.assertEqual(len(stage_results), 1)
        self.assertEqual(stage_results[0].stage, "Local state")
        self.assertFalse(stage_results[0].complete)
        self.assertIn("disk full", stage_results[0].failures[0].error)

    def test_classifier_does_not_replace_outputs_when_metadata_is_malformed(self):
        rules = """\
| Level 1 | Level 2 | Level 3 | Level 4 | Level 5 | Keywords |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Knowledge | Analysis | | | | data analysis |
"""
        with tempfile.TemporaryDirectory() as vault_dir:
            script_dir = os.path.join(vault_dir, "scripts")
            daily_dir = os.path.join(vault_dir, "Daily_Logs")
            subject_dir = os.path.join(vault_dir, "Subject")
            review_dir = os.path.join(vault_dir, "Topic_Reviews")
            for directory in (script_dir, daily_dir, subject_dir, review_dir):
                os.makedirs(directory)
            with open(
                os.path.join(vault_dir, "Classification_Rules.md"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write(rules)
            with open(
                os.path.join(daily_dir, "note.md"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("# Knowledge\n## Test\ndata analysis\n")
            existing_path = os.path.join(subject_dir, "existing.md")
            with open(existing_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("existing\n")
            with open(
                os.path.join(script_dir, "organizer_metadata.json"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write('{"entries":')

            fake_module_path = os.path.join(script_dir, "hierarchical_classifier.py")
            with patch.object(hierarchical_classifier, "__file__", fake_module_path):
                result = hierarchical_classifier.main(
                    [
                        "--production",
                        "--output-dir",
                        "Subject",
                        "--review-dir",
                        "Topic_Reviews",
                        "--metadata-file",
                        "organizer_metadata.json",
                    ]
                )

            with open(existing_path, "r", encoding="utf-8") as file_obj:
                existing = file_obj.read()

        self.assertEqual(result, 2)
        self.assertEqual(existing, "existing\n")


if __name__ == "__main__":
    unittest.main()
