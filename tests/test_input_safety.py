"""Regressions for source previews, generated paths, and external workspaces."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from classification_review_dashboard import ReviewError, add_classification_rule
from document_utils import resolve_generated_path
from hierarchical_classifier import parse_args, parse_rules_from_markdown, validate_output_targets
from review_renderer import _save_reviews


RULES = """| Level 1 | Level 2 | Level 3 | Level 4 | Level 5 | Keywords |
| --- | --- | --- | --- | --- | --- |
| Projects | Sample | | | | |
"""


class InputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        for source in (ROOT / "scripts").glob("*.py"):
            shutil.copy2(source, self.scripts)
        shutil.copy2(ROOT / "log2topic.py", self.root)
        self.vault = self.root / "Workspace"
        self.daily = self.vault / "Daily_Logs"
        self.daily.mkdir(parents=True)
        self.rules = self.vault / "Classification_Rules.md"
        self.rules.write_text(RULES, encoding="utf-8")
        self.source = self.daily / "2026-09-01.md"
        self.source.write_text(
            "# Projects\n## Sample\n<!-- research-notes-source-id: aaaaaaaaaaaaaaaa -->\n"
            "A fictional test record.\n", encoding="utf-8"
        )
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        self.env.pop("LOG2TOPIC_WORKSPACE", None)

    def run_python(self, script, *args):
        return subprocess.run(
            [sys.executable, "-B", str(script), *args], env=self.env,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def classify(self, *args):
        return self.run_python(
            self.scripts / "hierarchical_classifier.py", "--production",
            "--output-dir", "Subject", "--review-dir", "Topic_Reviews",
            "--metadata-file", "organizer_metadata.json", *args,
        )

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file() and ".runtime" not in p.parts}

    def test_rebuild_dry_run_preserves_sources_outputs_metadata_and_backups(self):
        result = self.classify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        shutil.copy2(self.source, self.daily / "2026-09-02.md")
        for batch in ("old-a", "old-b"):
            backup = self.scripts / "source_id_backups" / "rebuild" / batch / "saved.md"
            backup.parent.mkdir(parents=True)
            backup.write_text("preserved backup", encoding="utf-8")
        before = self.snapshot()
        for extra in ([], ["--no-persist-source-ids"]):
            with self.subTest(extra=extra):
                result = self.classify("--dry-run", "--rebuild-source-ids",
                                       "--max-backup-batches", "1", *extra)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Would rebuild Source ID markers in 2 source files", result.stdout)
                self.assertIn("Source units: 2", result.stdout)
                self.assertEqual(before, self.snapshot())
        result = self.classify("--rebuild-source-ids")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata = json.loads((self.scripts / "organizer_metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["stats"]["source_units"], 2)
        self.assertEqual(len(metadata["entries"]), 2)

    def test_unsafe_rules_fail_before_changing_source_or_outputs(self):
        for name in ("..", ".", "../escaped", r"..\escaped", "/escaped", "C:escaped",
                     "NUL", "COM1.txt", "trailing.", "a?b"):
            with self.subTest(name=name):
                self.rules.write_text(RULES.replace("Projects", name), encoding="utf-8")
                before = self.snapshot()
                result = self.classify()
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("Unsafe category name", result.stdout)
                self.assertEqual(before, self.snapshot())

    def test_dashboard_rejects_unsafe_category_without_saving_rules(self):
        before = self.snapshot()
        for name in ("..", r"..\escaped", "C:escaped", "CON"):
            with self.subTest(name=name), self.assertRaises(ReviewError):
                add_classification_rule([name], vault_dir=str(self.vault),
                                        rules_path=str(self.rules), backup_dir=str(self.root / "backups"))
        self.assertEqual(before, self.snapshot())

    def test_valid_unicode_category_names_remain_supported(self):
        self.rules.write_text(RULES.replace("Projects", "연구 (실험)").replace("Sample", "Topic 1.2"),
                              encoding="utf-8")
        self.assertEqual(parse_rules_from_markdown(self.rules).errors, [])

    def test_output_arguments_cannot_escape_or_target_source_subfolders(self):
        for name in ("../escaped", "/Subject", "C:/escaped", "Daily_Logs/nested", "Subject/nested"):
            for flag in ("--output-dir", "--review-dir"):
                with self.subTest(name=name, flag=flag):
                    self.assertTrue(validate_output_targets(parse_args([flag, name])))
        self.assertEqual(validate_output_targets(parse_args(["--output-dir", "Preview/Subjects"])), "")

    def test_review_batch_checks_all_destinations_before_writing(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            _save_reviews(str(self.vault), "Topic_Reviews", {
                "Topic_Reviews/valid.md": "valid",
                "Topic_Reviews/../Daily_Logs/2026-09-01.md": "overwrite",
            })
        self.assertEqual(before, self.snapshot())

    def test_resolved_path_cannot_escape_through_symlink(self):
        # Mock resolution so this guard is also exercised without Windows symlink privileges.
        realpath = os.path.realpath
        category = self.vault / "Subject" / "linked"
        def resolve(path):
            if os.path.normcase(os.path.normpath(path)).startswith(
                os.path.normcase(str(category)) + os.sep
            ):
                return str(self.root / "outside" / "note.md")
            return realpath(path)
        with patch("document_utils.os.path.realpath", side_effect=resolve):
            with self.assertRaises(ValueError):
                resolve_generated_path(str(self.vault), "Subject", "Subject/linked/note.md")

    def test_cli_uses_external_workspace_from_environment_or_settings(self):
        external = self.root / "ExternalVault"
        external.mkdir()
        self.rules.rename(external / "Classification_Rules.md")
        runtime = self.scripts / ".runtime"
        runtime.mkdir(exist_ok=True)
        for mode in ("environment", "settings"):
            with self.subTest(mode=mode):
                self.env.pop("LOG2TOPIC_WORKSPACE", None)
                if mode == "environment":
                    self.env["LOG2TOPIC_WORKSPACE"] = str(external)
                else:
                    (runtime / "tray_settings.json").write_text(
                        json.dumps({"workspace_path": str(external)}), encoding="utf-8")
                result = self.run_python(self.root / "log2topic.py", "update", "--validate-rules")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue((external / "Daily_Logs").is_dir())
                self.assertTrue((external / "attachments").is_dir())
                self.assertEqual(list((external / "Daily_Logs").glob("*.md")), [])

    def test_cli_still_seeds_bundled_workspace(self):
        self.source.unlink()
        result = self.run_python(self.root / "log2topic.py", "update", "--validate-rules")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(list(self.daily.glob("*.md"))), 2)


if __name__ == "__main__":
    unittest.main()
