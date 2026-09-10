import contextlib
import io
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
sys.path.insert(0, str(ROOT / 'scripts'))
import sync_to_notion as sync


class ClassificationFallbackTests(unittest.TestCase):
    def run_fallback(self, fail_upload=False):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            daily = root / 'Daily_Logs'
            daily.mkdir()
            for name in ('first.md', 'second.md'):
                (daily / name).write_text('body', encoding='utf-8')
            stack.enter_context(patch.object(sys, 'argv', ['sync', '--classification-failed', '--cloudinary-cleanup', 'delete']))
            stack.enter_context(patch.dict(os.environ, {'NOTION_DATABASE_ID': 'fake-database'}, clear=True))
            for name, value in {
                'load_env': None,
                'get_required_env': 'fake-token',
                'resolve_workspace_dir': str(root),
                'load_notion_sync_state': {'pages': {}},
                'get_database_property_names': {'Sync Key'},
                'save_sync_state_checkpoint': True,
            }.items():
                stack.enter_context(patch.object(sync, name, return_value=value))
            extraction = stack.enter_context(patch.object(sync, 'extract_generated_paths_from_metadata', side_effect=AssertionError('stale metadata used')))
            cleanup = stack.enter_context(patch.object(sync, 'run_cloudinary_cleanup_after_sync', side_effect=AssertionError('cleanup ran')))
            orphan = stack.enter_context(patch.object(sync, 'cleanup_orphan_pages', side_effect=AssertionError('orphan cleanup ran')))
            outcomes = [RuntimeError('upload failed'), 'https://example.invalid/second'] if fail_upload else ['https://example.invalid/first', 'https://example.invalid/second']
            upload = stack.enter_context(patch.object(sync, 'create_or_update_notion_page', side_effect=outcomes))
            report = stack.enter_context(patch.object(sync, 'write_notion_sync_report'))
            with contextlib.redirect_stdout(io.StringIO()):
                result = sync._main_unlocked()
            self.assertEqual(result, 1)
            self.assertEqual(upload.call_count, 2)
            for call in upload.call_args_list:
                self.assertEqual(call.kwargs['page_kind'], 'Daily')
            extraction.assert_not_called()
            cleanup.assert_not_called()
            orphan.assert_not_called()
            stages = report.call_args.args[1]
            self.assertEqual([stage.stage for stage in stages], ['Classification', 'Daily'])
            self.assertEqual(stages[1].succeeded, 1 if fail_upload else 2)
            self.assertFalse(report.call_args.args[3])

    def test_fallback_uploads_all_originals_and_reports_partial_failure(self):
        self.run_fallback()

    def test_original_upload_failure_still_attempts_remaining_files(self):
        self.run_fallback(fail_upload=True)

    def test_fast_daily_default_still_selects_one(self):
        with patch.object(sys, 'argv', ['sync', '--daily-only']), patch.object(sync, 'collect_daily_logs', return_value=['a.md', 'b.md']), patch.object(sync.os.path, 'getmtime', side_effect=[1, 2]):
            logs, daily_only = sync.select_original_logs('.', sync.parse_args())
            self.assertEqual(logs, ['b.md'])
            self.assertTrue(daily_only)

    @unittest.skipUnless(os.name == 'nt', 'Windows batch integration')
    def test_batch_success_and_failure_routes(self):
        for classification_exit in (0, 2):
            with self.subTest(classification_exit=classification_exit), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                scripts = root / 'scripts'
                scripts.mkdir()
                shutil.copy2(ROOT / 'scripts/run_notion_sync.bat', scripts)
                (scripts / 'resolve_python.bat').write_text('@echo off\nset PYTHON_CMD="' + sys.executable + '"\nexit /b 0\n', encoding='ascii')
                (scripts / 'hierarchical_classifier.py').write_text('raise SystemExit(' + str(classification_exit) + ')\n')
                (scripts / 'sync_to_notion.py').write_text('import sys,json\nfrom pathlib import Path\nPath("sync_args.json").write_text(json.dumps(sys.argv[1:]))\n')
                result = subprocess.run(['cmd.exe', '/d', '/c', str(scripts / 'run_notion_sync.bat'), '--nopause'], cwd=root, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 1 if classification_exit else 0, result.stdout)
                args = json.loads((root / 'sync_args.json').read_text())
                self.assertEqual('--classification-failed' in args, bool(classification_exit))


if __name__ == '__main__':
    unittest.main()
