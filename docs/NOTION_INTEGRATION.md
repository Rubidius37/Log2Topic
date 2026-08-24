# Notion Integration and Recovery

Notion sync is optional. Local classification and reviews work without Notion by selecting `Update local documents` from the tray.

[한국어](NOTION_INTEGRATION.ko.md) · [Back to README](../README.md)

## Prerequisites

1. Create a Notion integration.
2. Give the integration access to the database you will use.
3. Copy `scripts/.env.example` to `scripts/.env`.
4. Enter these values:

```text
NOTION_TOKEN=...
NOTION_DATABASE_ID=...
```

## Database properties

The following property is required:

| Name | Type | Purpose |
| :--- | :--- | :--- |
| `Sync Key` | `rich_text` | Permanent identity linking a local document to a Notion page |

The following properties are optional:

| Name | Type | Purpose |
| :--- | :--- | :--- |
| `Source ID` | `rich_text` | Identify the source section used by a topic document |
| `Source Heading` | `rich_text` | Display the original heading |

Do not create a `Local Relative Path` property. `Sync Key` owns page identity so the page survives a local rename or folder move.

## Run sync

For a full sync, right-click the tray icon and select `External services > Notion > Full sync`.

Full sync updates local classification first, then syncs Daily, Subject, and Topic Review documents to Notion.

For a quick sync of only the most recently modified Daily note, select `External services > Notion > Sync recent logs`. The default is one note.

```powershell
.\scripts\run_notion_daily_sync.bat --recent-daily 2
.\scripts\run_notion_daily_sync.bat Daily_Logs\2026-06\26.06.26.md
```

Daily-only mode skips `Subject/`, `Topic_Reviews/`, and orphan cleanup.

## Sync order

A full sync uses this order so managed links can resolve correctly:

1. Upload source files from `Daily_Logs/`.
2. Collect the Notion URLs of those source logs.
3. Upload `Subject/` documents and replace `Date/Log` links with Notion URLs.
4. Upload child documents from `Topic_Reviews/`.
5. Upload parent review pages and replace child-review links with Notion URLs.
6. Build a cleanup plan for pages that no longer exist locally.
7. Archive orphan or duplicate pages only when all safety checks pass.

## Sync Key and page updates

Sync Keys use formats similar to these:

```text
daily::{daily identity}
subject::{Source ID}::{category path}
timeline::{category path}
```

When a title or local folder changes but the Sync Key remains the same, Log2Topic updates properties and blocks inside the existing Page ID. The URL stays stable, so links from other pages remain valid.

Sync results are stored in `scripts/notion_sync_state.json`, including:

- Page ID and URL
- last successful content hash
- referenced-image hash
- unresolved managed links
- renderer version

Documents whose content and images have not changed are skipped on the next run. When rendering behavior changes, the internal renderer version changes and only affected documents are uploaded again.

## Link conversion

During sync, standard relative Markdown links in generated files are replaced with the corresponding managed Notion page URLs. Obsidian `[[...]]` Wikilinks left by older versions or present in source logs remain supported.

If a target page fails to upload but a previous URL exists in sync state, Log2Topic keeps using that last known URL. If the target has never synced successfully, the link remains plain display text and is resolved again on the next run.

When unresolved managed links remain, the full run ends as a partial failure and orphan cleanup is skipped.

## Markdown conversion

The Notion renderer supports:

- headings and paragraphs
- bulleted and numbered lists indented with tabs or spaces
- Obsidian callout titles and their complete nested content
- standalone `---` horizontal rules
- `$$...$$` block equations
- `$...$` inline equations
- standard Markdown links and Obsidian Wikilinks
- Obsidian image links

For long callouts or lists that exceed the Notion API child-block limit, Log2Topic creates the parent first and appends children in batches of at most 100. Nested structure is preserved where possible.

## Images and Cloudinary

Supported Obsidian image forms include:

```markdown
![[image.png]]
![[a.png]]![[b.png]]![[c.png]]
![[a.png]]description![[b.png]]
```

Images are resolved in this order:

1. path relative to the vault root or current document
2. `attachments/`
3. matching filename anywhere inside the vault

To use Cloudinary, add these values to `.env`:

```text
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_UPLOAD_PRESET=...
```

The classification review dashboard runs locally at `http://127.0.0.1:8000` without an external connection. That localhost server is unrelated to Notion image delivery.

Cloudinary is required when a document containing a local image is synced to Notion. Log2Topic does not use an automatic tunnel or localhost image fallback. Without Cloudinary, text-only documents and documents containing external `https://` images can still sync. A document with local images fails explicitly instead of being marked successful with broken links; its existing Notion page and last successful hash are preserved.

A missing image or failed Cloudinary upload also fails only the affected document.

Only validated image files located inside the vault can be sent to Cloudinary:

- allowed formats: PNG, JPEG, GIF, WebP, BMP, TIFF, and SVG
- absolute paths, `../` traversal, and URL-encoded traversal are blocked
- symlinks and junctions resolving outside the vault are blocked
- files under protected directories such as `.git`, `.obsidian`, `scripts`, and `.codex` are blocked
- the file extension must match the file signature

For example, a reference such as `![[scripts/.env]]` never creates a Cloudinary request. An unsafe image reference fails only that document and preserves the existing Notion page and last successful state. See `scripts/notion_sync_report.md` for the reason.

### Image cache

`scripts/cloudinary_cache.json` maps image-content hashes to Cloudinary URLs.

- Reclassification and repeated sync do not upload an unchanged image again.
- Changing the image bytes creates a new image identity even when the filename is unchanged.
- Several documents referencing the same image share one upload result.
- An image is marked `pending` before the Notion page is updated and `committed` afterward.

### Automatic cleanup

The default automatic cleanup after a full sync delays deletion only for old `pending` uploads left by failed Notion updates. A `committed` image is never deleted automatically and appears only in the report.

Default settings:

```text
CLOUDINARY_CLEANUP_AFTER_SYNC=auto
CLOUDINARY_PENDING_GRACE_DAYS=14
CLOUDINARY_PENDING_MIN_FULL_SYNCS=3
CLOUDINARY_PENDING_MAX_DELETE=10
CLOUDINARY_PENDING_MAX_DELETE_RATIO=0.05
```

Actual deletion also requires:

```text
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

When sync partially fails or local image references cannot be resolved completely, unused counters are not advanced and no image is deleted.

To review every unused candidate manually, run:

```powershell
.\scripts\run_cloudinary_cleanup.bat
```

After reviewing the report, explicitly include `committed` images in deletion with:

```powershell
.\scripts\run_cloudinary_cleanup.bat --delete
```

Deleted images may also disappear from archived historical Notion pages.

## Retries and partial failure

Read requests and idempotent requests retry automatically after `429`, `5xx`, and timeout errors.

Page creation and block append retry automatically only after an explicit `429`, preventing duplicate pages or blocks. When a `5xx` response or connection loss makes the write result uncertain, Log2Topic does not immediately repeat the same write.

Other documents continue as far as possible when one document fails. The process exits with code `1` and `PARTIAL FAILURE` when any of these remain:

- page upload failure
- unresolved managed link
- local-state checkpoint failure
- failed orphan-cleanup safety check
- cleanup operation failure

During a partial failure, orphan archive and Cloudinary deletion are skipped. Fix the cause and run the same task again; items without a successful hash are retried.

## Recover from a failed page update

If appending a new body to an existing page fails, newly created blocks whose IDs were confirmed in the response are rolled back where possible and the previous body is preserved. If the response is lost and the result cannot be determined, the successful hash is not advanced.

If deleting old blocks fails after the new body was appended, old and new content can temporarily appear together. The next run rebuilds the complete body from the page's current blocks and removes the old blocks.

To run recovery sync before any cleanup:

```powershell
.\scripts\run_notion_sync.bat --skip-orphan-cleanup
```

## Orphan and duplicate-page protection

When `Daily_Logs/` contains no Markdown files, the local classifier leaves existing `Subject/`, `Topic_Reviews/`, and metadata unchanged.

Notion cleanup also builds a plan before archiving. Cleanup is blocked when:

- there are zero active local Sync Keys
- there are at least 10 archive candidates and they represent at least 20% of existing pages
- a conflict prevents Log2Topic from proving which page is canonical for a duplicate Sync Key
- the current run has an upload or managed-link partial failure

For an intentional large reclassification, review the cleanup plan and bypass only the quantity limit once with:

```powershell
.\scripts\run_notion_sync.bat --allow-large-cleanup
```

This option does not bypass canonical-page conflicts or failures from the current upload.

When several pages share a Sync Key, the Page ID stored in sync state is kept as canonical. If state does not identify one candidate and several candidates exist, no page is archived automatically.

## Reports

Check these files first when a problem occurs:

- `scripts/reports/notion_sync_report.md`: stage results, Sync Keys, errors, and unresolved links
- `scripts/reports/notion_orphan_cleanup_plan.md`: canonical pages, duplicate and orphan candidates, and blocking reasons
- `scripts/reports/cloudinary_cleanup_report.md`: images in use and unused candidates

Recommended recovery sequence:

1. Find the first failure in `notion_sync_report.md`.
2. Fix credentials, database properties, network access, or local files.
3. Run `scripts/run_notion_sync.bat --skip-orphan-cleanup`.
4. Confirm that failures and unresolved links are both zero.
5. Run `External services > Notion > Full sync` once more to perform any required cleanup.

## Error checklist

- `401`, `403`: verify `NOTION_TOKEN`, database ID, and integration access
- `400` property error: confirm that `Sync Key` has type `rich_text`
- `429`: wait briefly, rerun, and check API usage limits
- `5xx`, timeout: check the Notion service and network, then rerun
- `Local image file was not found`: check attachment location and exact filename
- Cloudinary upload failure: check cloud name, upload preset, and image file
- `[BUSY]`: wait for another local classification or sync to finish
- damaged state JSON: do not delete it immediately; preserve a copy before deciding how to recover

## Code layout

The Notion implementation is separated from the local classifier:

- `scripts/sync_to_notion.py`: CLI, configuration, and overall run order
- `scripts/notion_api.py`: HTTP requests, retries, page and block operations
- `scripts/notion_render.py`: Markdown-to-Notion block conversion
- `scripts/notion_state.py`: Sync Key state, hashes, checkpoints, and reports
- `scripts/sync_cleanup.py`: canonical-page selection, orphan protection, and Cloudinary post-processing
- `scripts/sync_contracts.py`: shared property names and Sync Key normalization
- `scripts/cloudinary_cleanup.py`: image usage and deletion lifecycle

API behavior belongs in `notion_api.py`, rendering in `notion_render.py`, state formats in `notion_state.py`, and cleanup policy in `sync_cleanup.py`.
