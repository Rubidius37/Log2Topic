# Changelog

## 1.1.1

- Preserved permanent Source IDs across heading renames and section moves when `organizer_metadata.json` is present; copy-paste Source ID regeneration now activates only when the same ID appears in two or more distinct source sections.
- Restored strict H1/H2/H3 classification boundaries so unrecognized top-level headings are always surfaced for review instead of silently absorbed, and added a one-click "Merge into previous" (`<!-- research-notes-merge-above -->`) action in the review dashboard.
- Restored the default keyword scan window to the opening 800 characters (`LOG2TOPIC_KEYWORD_SCAN_CHARS`) to avoid false-positive keyword matches in long notes.
- Added completion notifications with `needs_review` counts after local updates in the Windows tray app, repository display and per-version skip handling in update prompts, rollback error logging in `update_windows_app.ps1`, and confirmation prompts in `log2topic.py rebuild`.

## 1.1.0

- Classification review dashboard now supports adding new classification rules directly to `Classification_Rules.md` (with one-click prefill from the current section's heading path), resetting manual `Category:` overrides, and detecting conflicts when headings are edited after manual classification.
- Added Notion "Sync original logs only" (`--all-daily`) to both the manual tray/CLI menu and scheduled automation modes (`ExternalOriginals`), alongside optional source backup batch retention limits (off by default, configurable count).
- Expanded general Markdown editor compatibility: CommonMark link/image titles, parenthesized and angle-bracketed paths, document-relative image resolution, preserved image alt text in `Subject/` documents, unified date parsing (`YYYY-MM-DD`, `YYYY.MM.DD`, `YYYYMMDD`, `YY.MM.DD`, `YYMMDD`), and standard blockquote (`>`) rendering in Notion sync.
- Added Linux support (`Log2Topic.sh`, `setup_workspace.sh`, `scripts/*.sh`, `scripts/configure_automation.py` for `systemd --user` / `cron` and XDG autostart, and `Log2Topic-linux-v1.1.0.tar.gz` release archive), bilingual English/Korean README and scripts, and updated project license to GNU General Public License v3.0 (GPL-3.0).

## 1.0.17

- Notion sync supports bounded data URL images through validated temporary attachments and the existing Cloudinary content cache. Unsupported inline images leave a visible omission notice while the rest of the document syncs.
- SVG uploads now accept a restricted static subset and reject scripts, external references, HTML content, document types, and excessive complexity. Inline image errors and manifests do not expose the original data URL.
- Inline images remain protected during Cloudinary cleanup; image examples in fenced and inline code are excluded from upload and image manifests.

## 1.0.16

- Normal local classification now consolidates multiple Source ID comments when heading edits merge them into one source unit. It preserves the ID below the classification heading, or the first ID in the unit, and backs up the original before saving.
- Body text, nested headings, quoted markers, fenced code examples, and existing empty-parent ID relocation are preserved. Headings and ID comments inside fenced code do not act as classification boundaries or permanent IDs. IDs shared by separate units or files remain errors.
- Dry runs show retained and removed IDs. Classification reports include consolidated-unit and removed-marker counts; obsolete generated documents are cleaned up during the normal update.
- Generated image and document links consistently resolve Windows short path names before computing relative paths.
