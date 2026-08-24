# Log2Topic User Guide

This guide covers editor setup and everyday Log2Topic use. If this is your first launch, complete the first classification by following [Quick start in the README](../README.md#quick-start).

[한국어](USER_GUIDE.ko.md) · [Back to README](../README.md) · [Classification rules](../Classification_Rules.md) · [Notion integration](NOTION_INTEGRATION.md)

## Prepare the workspace

Log2Topic treats the top-level project folder as one Markdown workspace.

```text
Log2Topic/
|-- Log2Topic.exe
|-- Classification_Rules.md
|-- Daily_Logs/
|-- attachments/
|-- Subject/             # created after the first update
|-- Topic_Reviews/       # created after the first update
|-- scripts/
`-- runtime/
```

- Store source logs as `.md` files under `Daily_Logs/`.
- Do not edit `Subject/` or `Topic_Reviews/` directly. They are generated outputs.
- `attachments/` is the recommended location for images and attachments, but it is optional.
- Do not run the project inside a compressed archive or a restricted location such as `Program Files`.

The official distribution currently supports Windows 10/11 x64. A dedicated Python runtime is included, so you do not need to install Python or configure `PATH`.

## Configure a Markdown editor

### Obsidian

In Obsidian, choose **Open folder as vault**, then select the top-level folder containing `Log2Topic.exe` and `Classification_Rules.md`. Do not open only `Daily_Logs/`, because generated relative links would no longer resolve correctly.

No Obsidian plugin is required. The following settings are recommended for tidy files and compatibility with other Markdown tools:

- **Default location for new attachments**: `attachments`
- **Daily Notes location**: `Daily_Logs`, when you use the Daily Notes feature
- **New link format**: **Relative path to file**, when you also use other tools
- **Use Wikilinks**: either setting works for classification; turn it off for broader Markdown compatibility

You may use a folder other than `attachments/` as long as the image path in the document is valid. During Notion image sync, Log2Topic checks the document-relative path, `attachments/`, and then matching filenames inside the workspace.

### Other Markdown tools

- Open the entire Log2Topic folder as the workspace.
- Save logs under `Daily_Logs/` with the `.md` extension.
- Match the number of `#` characters in a heading to the intended classification level.
- Generated links use standard relative Markdown syntax.
- Backlink lists and graphs are not part of the Markdown standard and may not be available in every editor.

## Run Log2Topic

1. Double-click `Log2Topic.exe`.
2. On first launch, choose whether to start Log2Topic at Windows sign-in and whether to schedule an automatic task. Both can be changed later.
3. Find the Log2Topic icon in the Windows notification area. Select `^` if it is hidden.
4. Right-click the icon to update local documents, review classifications, use external services, or change automation settings.

The first launch can take a little longer while the bundled Python environment is prepared. The executable is not digitally signed yet. If Windows shows a **Windows protected your PC** dialog, verify that the file came from the official distribution and is named `Log2Topic.exe` before deciding whether to run it.

## Write classification rules

Define rules in the table inside `Classification_Rules.md` at the workspace root. Keep all six columns in their original order.

| Rule level | Log heading |
| :--- | :--- |
| Level 1 | `#` |
| Level 2 | `##` |
| Level 3 | `###` |
| Level 4 | `####` |
| Level 5 | `#####` |

When a heading exactly matches a category name, no matching keyword is required. Blank parent cells inherit the value from the row above, so you do not need to repeat a parent when adding a path beneath it. See the instructions below the table in [Classification_Rules.md](../Classification_Rules.md) for keyword syntax and level boundaries.

## Daily workflow

### Write a log

Create a Markdown file under `Daily_Logs/` and use category names as headings.

```markdown
# Projects
## Sample Project
### Testing

Write today's findings here.
```

You may choose any filename. If you used Windows Notepad, confirm that the file was not saved as `.md.txt`.

For content that belongs to several topics, select multiple paths in the classification review dashboard. You can also write full paths directly in the source section with `Category:`.

### Paste a Markdown response from an AI service

AI responses often contain headings such as `# Analysis` or `## Cause`. If pasted directly, the classifier may interpret those headings as new classification boundaries.

The safest method is to place the entire response inside a blockquote or Obsidian callout below the real classification heading. Prefix every line, including blank lines and code fences, with `>`.

```markdown
# Projects
## Sample Project
### Testing

> [!quote] AI service response
> # Analysis
>
> ## Possible cause
> Explanation of the first possible cause.
>
> ## Verification
> Description of the measurement procedure.
```

The classification path in this example is `Projects > Sample Project > Testing`. Headings inside the callout affect only its visual structure and are not treated as classification headings. When Notion sync is enabled, the title and all nested content are converted into a Notion callout.

Alternatively, ask the AI service not to use headings:

```text
Answer in Markdown, but do not use H1-H6 headings (#, ##, ###, and so on).
Write each section title in **bold** instead.
```

> [!warning] A fenced code block alone does not prevent classification
> The current classifier can still read a line beginning with `#` inside a fenced code block as a heading. When preserving code formatting, put every line of the code block inside the callout as well.

### Update local documents

Right-click the tray icon and select `Update local documents`. When the task finishes, these folders are refreshed:

- `Subject/`: history documents grouped by topic
- `Topic_Reviews/`: topic progress and review items

Direct edits to these folders may be overwritten by the next update. Make lasting changes in the source log or `Classification_Rules.md`.

### Review ambiguous classifications

Select `Open classification review` from the tray to see unclassified sections and sections that stopped at a parent category.

Selecting a child category automatically selects its parent path. Applying the selection adds or updates `Category:` metadata in the corresponding source section while preserving its headings and body. The previous source file is backed up under `scripts/source_id_backups/classification_review/`.

The dashboard opens in your default browser but is served only by a local server on this PC at `http://127.0.0.1:8000`. It does not send log content to an external service. The server stops shortly after all dashboard tabs are closed. Runtime details are written to `scripts/reports/classification_review_dashboard.log`.

## Automation

Open `Automation and sync settings...` from the tray to configure:

- starting the tray app at Windows sign-in
- whether an automatic task is enabled
- local update only, or local update followed by external-service sync
- run time and weekdays
- whether to run later when the PC was off at the scheduled time
- interface language: Windows display language, English, or Korean

Scheduled tasks are registered with Windows Task Scheduler and still run at the configured time when the tray app is closed. After changing the interface language, exit and restart Log2Topic. The tray, settings window, and classification review dashboard use the same language setting.

## Optional feature: Notion

Notion and Cloudinary are not required for local use. To connect Notion, follow the [Notion integration guide](NOTION_INTEGRATION.md) from the beginning.

Connect only one authoritative Markdown workspace to a Notion database. If several PCs with different document sets run full sync against the same database, one workspace may treat pages owned by another workspace as missing locally.

## Frequently used files

| File | Purpose |
| :--- | :--- |
| `Log2Topic.exe` | Open the tray app and access normal commands |
| `Classification_Rules.md` | Manage the topic tree and optional keywords |
| `Daily_Logs/` | Store source logs written by the user |
| `Subject/` | Generated history grouped by topic |
| `Topic_Reviews/` | Generated topic reviews |

For everyday use, it is enough to know `Log2Topic.exe`, `Classification_Rules.md`, and `Daily_Logs/`.

## Troubleshooting

### The tray icon does not appear

- Check hidden icons in the Windows notification area.
- Open `scripts/.runtime/app_error.log`.
- For bundled Python problems, see `runtime/PYTHON_RUNTIME.md`.

### A log is not classified

- Confirm that it is under `Daily_Logs/`.
- Confirm that its extension is `.md`.
- Put a space after the `#` characters in each heading.
- Check that heading names match paths in `Classification_Rules.md`.
- A new section without a recognized Level 1 heading is preserved as unclassified.

### A task does not run

- `[BUSY]` means another classification or sync is running. Try again after it finishes.
- If the dashboard reports that the source changed, refresh the page and apply again.
- Check local classification reports and logs under `scripts/reports/`.

### Notion sync fails

- Open `scripts/reports/notion_sync_report.md`.
- Verify the token and database ID in `scripts/.env`.
- Confirm that the Notion integration has access to the database.
- Follow the recovery steps in the [Notion integration guide](NOTION_INTEGRATION.md).

A failed external-service sync does not prevent you from using the local source and generated documents.

## Feedback and issues

Use the repository's GitHub `Issues` tab for bugs, setup problems, and feature requests.

- **Bug report**: something does not run or behaves differently from the documented result
- **Feature request**: a suggestion for a new capability, usability improvement, or documentation change

For a bug, include the Windows version, Markdown editor, reproduction steps, expected result, and actual result. Search existing issues first when possible.

Do not attach research data or credentials to a public issue. Remove or replace the following with synthetic data:

- real research content from `Daily_Logs/`, `Classification_Rules.md`, or `attachments/`
- Notion and Cloudinary credentials from `scripts/.env`
- page IDs, paths, and document titles from `scripts/notion_sync_state.json` or reports

Use fictional category names, filenames, and content when a minimal reproducible example is needed.
