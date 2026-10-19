import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from notion_render import (
    convert_wikilinks_to_notion_links,
    format_date_for_notion,
    get_page_properties,
    markdown_to_notion_blocks,
    notion_code_language,
)


class NotionCodeLanguageTests(unittest.TestCase):
    def test_code_fences_use_notion_language_values(self):
        markdown = (
            "```text\nplain body\n```\n"
            "```py\nprint(1)\n```\n"
            "```Mermaid\ngraph LR\n```\n"
            "```sml\nval x = 1\n```\n"
            "```\nno language\n```\n"
        )
        blocks = markdown_to_notion_blocks(markdown)
        codes = [block["code"] for block in blocks if block["type"] == "code"]
        self.assertEqual(
            [code["language"] for code in codes],
            ["plain text", "python", "mermaid", "plain text", "plain text"],
        )
        self.assertEqual(codes[0]["rich_text"][0]["text"]["content"], "plain body")
        self.assertEqual(codes[3]["rich_text"][0]["text"]["content"], "val x = 1")

    def test_unclosed_fence_uses_normalized_language(self):
        blocks = markdown_to_notion_blocks("```TEXT\nunfinished")
        self.assertEqual(blocks[-1]["code"]["language"], "plain text")
        self.assertEqual(notion_code_language("c++"), "c++")
        self.assertEqual(notion_code_language("ps1"), "powershell")
        self.assertEqual(notion_code_language("unknown-tag"), "plain text")

    def test_quoted_fence_inside_callout_is_normalized(self):
        blocks = markdown_to_notion_blocks(
            "> [!NOTE] Example\n> ```text\n> quoted code\n> ```\n"
        )
        children = blocks[0]["callout"]["children"]
        self.assertEqual(children[0]["type"], "code")
        self.assertEqual(children[0]["code"]["language"], "plain text")
        self.assertEqual(children[0]["code"]["rich_text"][0]["text"]["content"], "quoted code")

    def test_standard_blockquote_renders_as_notion_quote_block(self):
        blocks = markdown_to_notion_blocks("> 첫 번째 인용\n> 두 번째 인용\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["type"], "quote")
        self.assertEqual(
            blocks[0]["quote"]["rich_text"][0]["text"]["content"],
            "첫 번째 인용\n두 번째 인용",
        )

    def test_iso_date_filenames_and_titled_markdown_links_in_notion_render(self):
        self.assertEqual(format_date_for_notion("2026-09-27-log"), "2026-09-27")
        props = get_page_properties(
            "Subject/Projects/2026-09-27 - Functional Test.md",
            "Subject/Projects/2026-09-27 - Functional Test.md",
            "subject::123::Projects",
        )
        self.assertEqual(props["이름"]["title"][0]["text"]["content"], "Functional Test")
        self.assertEqual(props["날짜"]["date"]["start"], "2026-09-27")

        converted = convert_wikilinks_to_notion_links(
            '[보고서](../Daily_Logs/2026-09-27-log.md "원본 일지")',
            {"Daily_Logs/2026-09-27-log.md": "https://www.notion.so/logpage"},
            source_path="Subject/2026-09-27 - Functional Test.md",
        )
        self.assertEqual(converted, "[보고서](https://www.notion.so/logpage)")


if __name__ == "__main__":
    unittest.main()
