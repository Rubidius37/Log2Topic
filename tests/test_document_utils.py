import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from document_utils import source_date_key


class SourceDateTests(unittest.TestCase):
    def test_dotted_compact_and_iso_markdown_source_dates(self):
        for value in (
            "26.09.27 일지.md", "26.09.27 일지.MD",
            "Daily_Logs/2026-09/26.09.27 일지.md", "260927 일지.md",
            "2026-09-27-log.md",
        ):
            with self.subTest(value=value):
                self.assertEqual(source_date_key(value), "2026-09-27")

    def test_unknown_or_invalid_date_sorts_as_undated(self):
        for value in (
            "26.09.27 일지", "260927 일지", "2026-09-27-log",
            "undated.md", "26.02.30 일지.md", "2026-13-01-log.md",
        ):
            with self.subTest(value=value):
                self.assertEqual(source_date_key(value), "0000-00-00")


if __name__ == "__main__":
    unittest.main()
