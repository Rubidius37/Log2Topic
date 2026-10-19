"""Offline data-image security and synchronization fixtures."""

import base64
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote_from_bytes
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import cloudinary_cleanup as cleanup
import image_assets
import inline_images as inline
import notion_render
import sync_to_notion as sync


SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
       b'width="10" height="10"><rect width="10" height="10" fill="#123456"/></svg>')
CONFIG = {"cloud_name": "example", "upload_preset": "example"}
URL = "https://res.cloudinary.com/example/image/upload/v1/inline.svg"


def data_url(data, mime="image/svg+xml", encoded=True):
    if encoded:
        return "data:" + mime + ";base64," + base64.b64encode(data).decode()
    return "data:" + mime + ";charset=utf-8," + quote_from_bytes(data, safe="")


def png(width=1, height=1):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0")) + chunk(b"IEND", b""))


class InlineDecodingTests(unittest.TestCase):
    def test_svg_base64_and_percent_encoding_preserve_original_bytes(self):
        for reference in (data_url(SVG), data_url(SVG, encoded=False),
                          "DATA:image/svg+xml;utf8," + quote_from_bytes(SVG, safe="")):
            with self.subTest(reference=reference[:32]):
                image = inline.decode_data_image(reference)
                self.assertEqual(image.data, SVG)
                self.assertEqual(image.sha1, hashlib.sha1(SVG).hexdigest())
                self.assertTrue(image.filename.endswith(".svg"))

    def test_png_and_other_raster_dimensions(self):
        gif = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
        # Minimal SOF metadata verifies that JPEG dimensions are read from its
        # structure rather than guessed from a filename or declared MIME.
        jpeg = b"\xff\xd8\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xd9"
        webp = base64.b64decode("UklGRiIAAABXRUJQVlA4IBYAAAAwAQCdASoBAAEADsD+JaQAA3AAAAAA")
        for data, mime in ((png(), "image/png"), (gif, "image/gif"), (jpeg, "image/jpeg"), (webp, "image/webp")):
            with self.subTest(mime=mime):
                self.assertEqual(inline.decode_data_image(data_url(data, mime)).data, data)

    def test_invalid_encoding_mime_spoofing_and_dimensions_are_rejected(self):
        references = ["data:image/svg+xml;base64,@@", "data:image/svg+xml,%xx",
                      "data:text/html;base64,PHNjcmlwdD4=", "data:image/png;base64," + base64.b64encode(SVG).decode(),
                      "data:image/svg+xml;charset=utf-16," + quote_from_bytes(SVG),
                      "data:image/svg+xml;base64;base64,AA==", "data:image/svg+xml", "data:image/png,",
                      data_url(png(9000, 1), "image/png"), data_url(png(5000, 5000), "image/png"),
                      data_url(png()[:-2], "image/png")]
        for reference in references:
            with self.subTest(reference=reference[:50]):
                with self.assertRaises(inline.InlineImageError) as raised:
                    inline.decode_data_image(reference)
                self.assertNotIn(reference, str(raised.exception))

    def test_url_decoded_size_and_svg_complexity_limits(self):
        with patch.object(inline, "MAX_DATA_URL_LENGTH", 24):
            with self.assertRaisesRegex(inline.InlineImageError, "length"):
                inline.decode_data_image(data_url(SVG))
        with patch.object(inline, "MAX_INLINE_IMAGE_BYTES", 20):
            with self.assertRaisesRegex(inline.InlineImageError, "5 MiB"):
                inline.decode_data_image(data_url(SVG))
        with patch.object(inline, "MAX_SVG_ELEMENTS", 1):
            with self.assertRaisesRegex(inline.InlineImageError, "complexity"):
                inline.decode_data_image(data_url(SVG))
        with patch.object(inline, "MAX_SVG_DEPTH", 1):
            with self.assertRaisesRegex(inline.InlineImageError, "complexity"):
                inline.decode_data_image(data_url(SVG))
        with patch.object(inline, "MAX_SVG_BYTES", 10):
            with self.assertRaisesRegex(inline.InlineImageError, "1 MiB"):
                inline.decode_data_image(data_url(SVG))

    def test_active_svg_features_are_rejected(self):
        bodies = [b'<script>alert(1)</script>', b'<g onload="alert(1)"/>',
                  b'<foreignObject><div>HTML</div></foreignObject>',
                  b'<image href="https://example.invalid/image.png"/>',
                  b'<use href="file:///example.txt"/>',
                  b'<rect fill="url(https://example.invalid/x)"/>',
                  b'<rect style="fill:u\\72l(https://example.invalid/x)"/>',
                  b'<rect style="background-image:url(file:///example.txt)"/>',
                  b'<style>@import "https://example.invalid/x";</style>']
        documents = [b'<svg xmlns="http://www.w3.org/2000/svg">' + body + b'</svg>' for body in bodies]
        documents += [b'<!DOCTYPE svg [<!ENTITY e SYSTEM "file:///example.txt">]><svg>&e;</svg>',
                      b'<?xml-stylesheet href="https://example.invalid/x"?><svg/>',
                      b'<svg width="999999in"/>', b'<svg width="8192" height="8192"/>',
                      b'<svg width="NaN"/>', b'<svg><g></svg>', b'<html/>']
        for document in documents:
            with self.subTest(document=document):
                with self.assertRaises(inline.InlineImageError):
                    inline.decode_data_image(data_url(document))

    def test_static_svg_local_gradients_styles_and_text_are_allowed(self):
        document = (b'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg">'
                    b'<defs><linearGradient id="shade"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
                    b'<rect fill="url(#shade)" style="stroke:#000;stroke-width:1"/>'
                    b'<text xml:space="preserve">A &amp; B</text></svg>')
        self.assertEqual(inline.decode_data_image(data_url(document)).data, document)

    def test_local_svg_uses_same_security_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagram.svg"
            path.write_bytes(SVG)
            self.assertEqual(image_assets.validate_local_image_file(str(path), directory), str(path.resolve()))
            path.write_bytes(b'<svg><script>alert(1)</script></svg>')
            with self.assertRaises(image_assets.ImageReferenceError):
                image_assets.validate_local_image_file(str(path), directory)


class InlineSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp.name).resolve()
        sync._cloudinary_cache = {}
        sync._image_sha1_cache.clear()

    def tearDown(self):
        sync._cloudinary_cache = None
        sync._image_sha1_cache.clear()
        self.temp.cleanup()

    def test_upload_deduplicates_and_temporary_attachment_is_removed(self):
        paths = []
        def upload(path, *_):
            paths.append(Path(path))
            self.assertEqual(Path(path).read_bytes(), SVG)
            self.assertTrue(Path(path).resolve().is_relative_to(self.vault))
            return {"url": URL, "public_id": "inline"}
        with patch.object(sync, "upload_to_cloudinary", side_effect=upload) as uploaded, patch.object(sync, "save_cloudinary_cache"):
            for reference in (data_url(SVG), data_url(SVG, encoded=False)):
                block = sync.create_image_block(reference, None, str(self.vault), CONFIG)
                self.assertEqual(block["image"]["external"]["url"], URL)
            uploaded.assert_called_once()
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual(list(self.vault.glob(".inline-image-*")), [])
            manifest = sync.build_image_asset_manifest("![diagram](" + data_url(SVG) + ")", str(self.vault))
            self.assertEqual(sync.mark_cloudinary_manifest_committed(str(self.vault), manifest), 2)

    def test_rejected_inline_image_leaves_notice_and_following_body(self):
        reference = data_url(b'<svg><script>example_payload</script></svg>')
        markdown = "before\n![bad](" + reference + ")\nafter"
        log = io.StringIO()
        with redirect_stdout(log), patch.object(sync, "get_or_upload_cloudinary_image") as upload:
            blocks = sync.markdown_to_notion_blocks(markdown, vault_dir=str(self.vault), cloudinary_config=CONFIG)
        text = json.dumps(blocks, ensure_ascii=False)
        self.assertIn("인라인 이미지 생략", text)
        self.assertIn("after", text)
        self.assertNotIn(reference, text + log.getvalue())
        upload.assert_not_called()
        manifest = sync.build_image_asset_manifest(markdown, str(self.vault))
        self.assertEqual(manifest[0]["status"], "skipped")
        self.assertNotIn(reference, json.dumps(manifest))

    def test_missing_configuration_uses_inline_notice(self):
        with patch.object(sync, "get_or_upload_cloudinary_image") as upload:
            block = sync.create_image_block(data_url(SVG), None, str(self.vault), None)
        self.assertEqual(block["type"], "paragraph")
        upload.assert_not_called()

    def test_network_upload_failure_preserves_page_and_state(self):
        path = self.vault / "Daily_Logs/note.md"
        path.parent.mkdir()
        path.write_text("![diagram](" + data_url(SVG) + ")", encoding="utf-8")
        state = {"pages": {"daily::note": {"url": URL, "content_hash": "previous"}}}
        original = copy.deepcopy(state)
        with patch.object(sync, "upload_to_cloudinary", side_effect=sync.CloudinaryUploadError("timeout")), patch.object(sync, "query_existing_page") as query, patch.object(sync, "replace_page_content_in_place") as replace:
            with self.assertRaisesRegex(sync.CloudinaryUploadError, "timeout"):
                sync.create_or_update_notion_page("example", "example", str(path), "Daily_Logs/note.md",
                                                vault_dir=str(self.vault), cloudinary_config=CONFIG,
                                                available_properties={"Sync Key"}, sync_key="daily::note", sync_state=state)
        self.assertEqual(state, original)
        query.assert_not_called()
        replace.assert_not_called()
        self.assertEqual(list(self.vault.glob(".inline-image-*")), [])

    def test_cleanup_protects_inline_asset_by_content_hash(self):
        daily = self.vault / "Daily_Logs"
        daily.mkdir()
        (daily / "note.md").write_text("![diagram](" + data_url(SVG) + ")", encoding="utf-8")
        live = cleanup.scan_live_images(str(self.vault), ["Daily_Logs"])
        image = inline.decode_data_image(data_url(SVG))
        cache = {"sha1:" + image.sha1: {"url": URL, "sha1": image.sha1, "filename": image.filename}}
        used, stale = cleanup.classify_groups(cleanup.group_cache_entries(cache), live)
        self.assertEqual(len(used), 1)
        self.assertEqual(stale, [])
        self.assertEqual(live["missing_refs"], [])

    def test_page_sync_with_valid_and_rejected_inline_images_completes_and_reuses_state(self):
        path = self.vault / "Daily_Logs/note.md"
        path.parent.mkdir()
        valid = data_url(png(), "image/png")
        rejected = data_url(b'<svg><foreignObject/></svg>')
        markdown = "before\n![valid](" + valid + ")\n![rejected](" + rejected + ")\nafter"
        path.write_text(markdown, encoding="utf-8")
        state = {"pages": {}}
        with patch.object(sync, "upload_to_cloudinary", return_value={"url": URL}), patch.object(sync, "save_cloudinary_cache"), patch.object(sync, "query_existing_page", return_value={"id": "example-page", "url": URL}) as query, patch.object(sync, "replace_page_content_in_place") as replace:
            for _ in range(2):
                result = sync.create_or_update_notion_page(
                    "example", "example", str(path), "Daily_Logs/note.md",
                    vault_dir=str(self.vault), cloudinary_config=CONFIG,
                    available_properties={"Sync Key"}, sync_key="daily::note", sync_state=state)
                self.assertEqual(result, URL)
            query.assert_called_once()
            replace.assert_called_once()
        rendered = json.dumps(replace.call_args.args[3], ensure_ascii=False)
        self.assertIn("after", rendered)
        self.assertIn("인라인 이미지 생략", rendered)
        self.assertNotIn(valid, rendered)
        self.assertEqual(path.read_text(encoding="utf-8"), markdown)
        self.assertTrue(state["pages"]["daily::note"]["content_hash"])
        self.assertTrue(all(entry["status"] == "committed" for entry in sync._cloudinary_cache.values()))

    def test_code_examples_are_not_uploaded_or_protected_as_assets(self):
        reference = data_url(SVG)
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                markdown = fence + "markdown\n![diagram](" + reference + ")\n" + fence
                with patch.object(sync, "get_or_upload_cloudinary_image") as upload:
                    blocks = sync.markdown_to_notion_blocks(markdown, vault_dir=str(self.vault), cloudinary_config=CONFIG)
                self.assertEqual(blocks[0]["type"], "code")
                upload.assert_not_called()
                self.assertEqual(sync.build_image_asset_manifest(markdown, str(self.vault)), [])
        self.assertEqual(list(notion_render.iter_markdown_image_references("`![diagram](" + reference + ")`")), [])

    def test_intentionally_skipped_inline_images_are_reported_without_blocking_cleanup(self):
        daily = self.vault / "Daily_Logs"
        daily.mkdir()
        reference = data_url(b'<svg><script>example_payload</script></svg>')
        (daily / "note.md").write_text("![diagram](" + reference + ")", encoding="utf-8")
        live = cleanup.scan_live_images(str(self.vault), ["Daily_Logs"])
        self.assertEqual(live["missing_refs"], [])
        self.assertEqual(len(live["skipped_inline_refs"]), 1)
        self.assertNotIn(reference, live["skipped_inline_refs"][0])

    def test_http_urls_and_unsafe_file_references_keep_existing_policy(self):
        block = sync.create_image_block("https://example.invalid/image.png", None, str(self.vault), None)
        self.assertEqual(block["type"], "image")
        for reference in ("file:///example.png", "javascript:example", "../outside.png", "data%3Aimage/png,test"):
            with self.subTest(reference=reference), self.assertRaises(sync.CloudinaryUploadError):
                sync.create_image_block(reference, None, str(self.vault), CONFIG)

    def test_image_syntax_in_fence_language_label_is_not_uploaded(self):
        markdown = "```![example](" + data_url(SVG) + ")\nexample\n```"
        with patch.object(sync, "get_or_upload_cloudinary_image") as upload:
            blocks = sync.markdown_to_notion_blocks(markdown, vault_dir=str(self.vault), cloudinary_config=CONFIG)
        upload.assert_not_called()
        self.assertEqual(blocks[0]["type"], "code")
        self.assertEqual(sync.build_image_asset_manifest(markdown, str(self.vault)), [])

    def test_unclosed_code_in_callout_does_not_hide_image_outside_callout(self):
        reference = data_url(SVG)
        markdown = "> [!NOTE]\n> ```markdown\n> example\n\n![diagram](" + reference + ")"
        manifest = sync.build_image_asset_manifest(markdown, str(self.vault))
        self.assertEqual([entry["sha1"] for entry in manifest], [hashlib.sha1(SVG).hexdigest()])
        daily = self.vault / "Daily_Logs"
        daily.mkdir()
        (daily / "note.md").write_text(markdown, encoding="utf-8")
        self.assertIn(hashlib.sha1(SVG).hexdigest(), cleanup.scan_live_images(str(self.vault), ["Daily_Logs"])["live_sha1s"])


if __name__ == "__main__":
    unittest.main()
