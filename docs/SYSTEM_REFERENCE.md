# System Architecture and Maintenance

This reference describes Log2Topic's local classification architecture and maintenance rules. New users should begin with the root [README](../README.md).

[한국어](SYSTEM_REFERENCE.ko.md) · [Back to README](../README.md)

## Local processing flow

`Log2Topic.exe` is the normal user entry point. The Windows tray app owns the interface and delegates work to internal BAT files under `scripts/` and the bundled Python runtime.

1. Read Markdown source files from `Daily_Logs/`.
2. Load hierarchical rules from `Classification_Rules.md`.
3. Verify or assign a Source ID for each managed source section.
4. Generate topic history under `Subject/`.
5. Generate child reviews and Level 1-2 aggregate reviews under `Topic_Reviews/`.
6. Store classifications and review candidates in `scripts/organizer_metadata.json`.

Notion configuration is not read during this process. `Update local documents` does not call the Notion or Cloudinary modules.

## Main files and directories

- `Log2Topic.exe`: Windows tray app for normal users
- `Log2Topic.bat`: fallback PowerShell tray launcher for development environments without the EXE
- `Daily_Logs/`: source logs written by the user
- `Classification_Rules.md`: Level 1-5 category tree and optional keywords
- `Subject/`: generated documents grouped by topic
- `Topic_Reviews/`: generated child and aggregate reviews
- `attachments/`: Obsidian image attachments
- `assets/log2topic.ico`: icon used by the tray and Windows startup shortcut
- `scripts/hierarchical_classifier.py`: production local classifier
- `scripts/classification_review_dashboard.py`: local classification review server
- `scripts/classification_review_ui/`: dashboard frontend
- `app/Log2Topic.cs`: Windows tray app source
- `scripts/log2topic_tray.ps1`: fallback tray implementation for development
- `scripts/resolve_python.bat`: shared launcher that prefers the bundled Python runtime
- `scripts/configure_automation.ps1`: sign-in startup and scheduled-task registration
- `scripts/organizer_metadata.json`: local state connecting Source IDs to current classifications
- `scripts/source_id_backups/`: backups made before Source IDs or manual categories are written to source files

`Subject/`, `Topic_Reviews/`, and metadata can be regenerated. `Daily_Logs/` contains the long-term source of truth.

## Hierarchical classification rules

The classification path has up to five levels:

```text
Level 1 > Level 2 > Level 3 > Level 4 > Level 5
```

`Classification_Rules.md` uses an inherited table. A blank cell inherits the value in the same column from the preceding row, so parent names do not need to be repeated for each child path.

### Heading matching

- H1 establishes the Level 1 boundary for automatic classification.
- H2-H5 extend the path only when a category with that name exists under the current parent.
- A new section without a recognized H1 is preserved under `Unclassified/Missing Level 1`; keywords do not guess a top-level category.
- Headings deeper than the configured category path remain part of the document structure but do not extend classification.

```markdown
# Projects
## Sample Project
### Testing
```

These fictional headings classify the section as `Projects > Sample Project > Testing`.

### Keywords and sibling boundaries

Keywords are a fallback when headings do not provide enough detail. They are checked in the heading and opening body and can refine a path or add overlapping paths inside the same H1 boundary.

When sibling Level 2 categories such as `Sample Project` and `Archive Project` represent different targets, an explicitly matched target becomes a boundary. General keywords from another sibling cannot create a path across it. Put unique identifiers such as project names at Level 2 and general terms such as `Testing` or `Meeting` at Level 3 or below when possible.

For broad roots such as `Methods`, where one section can legitimately belong to several topics, all matching paths may be generated together.

### Manual classification

A full path can be written directly in a source section:

```markdown
Category: Projects/Sample Project/Testing/Functional Test/Test Case A
```

Separate multiple paths with commas:

```markdown
Category: Methods/Data Analysis/Visualization, Projects/Sample Project/Reporting
```

Using `Open classification review` from the tray reduces typing mistakes.

## Source ID

The production classifier assigns a permanent Source ID to each managed source section:

```html
<!-- research-notes-source-id: 9f2a6e1c0b7d4a33 -->
```

This comment is hidden in Obsidian reading view and omitted from generated document bodies. It lets Log2Topic track the same source section after a heading or classification path changes, remove old generated entries, and connect the section to its new path.

Source ID comments created by older versions are normalized automatically on the next local update without changing their ID values.

Before new IDs are persisted, source files are backed up to `scripts/source_id_backups/automatic/{timestamp}/`. All changes are prepared before atomic replacement. Classification stops if a source changes during scanning or if duplicate Source IDs are found.

To validate without writing changes:

```powershell
.\scripts\run_local.bat --dry-run
```

`--no-persist-source-ids` is available for special read-only environments but is not recommended for normal use because tracking becomes less stable after heading changes.

## Generated documents and reviews

A topic document contains links to source logs, Source IDs, and original headings. `Date/Log` uses a standard relative Markdown link based on the generated document's location, so Obsidian, GitHub, VS Code, and general Markdown viewers can open the source.

`Topic_Reviews/` contains:

- snapshots of records for the topic
- recent updates
- progress history
- potential issues to review
- links to source logs and child documents

A Level 1 aggregate review shows the latest 20 detailed entries, and a Level 2 aggregate review shows the latest 50. Level 3-5 reviews show the complete history for that path. If one source section belongs to several child topics, an aggregate review counts it once by Source ID.

## Classification review dashboard

The tray launches `scripts/run_classification_review_dashboard.bat`, which displays every `needs_review` item in `scripts/organizer_metadata.json`, including:

- sections without a Level 1 category
- sections that stopped at a parent because no child could be determined
- manual paths not present in the rules
- mismatches between a source file and metadata

Selecting a child checks its parent path automatically. The save request contains only the most specific final path, preventing duplicate parent and child values in `Category:`. Clearing a parent also clears its descendants.

The dashboard edits the `Category:` line in the source section identified by Source ID, not the generated `Subject/` file. Headings and body content remain unchanged, and `Subject/` and `Topic_Reviews/` are regenerated after saving. If the source changes after the page opens, a fingerprint conflict blocks the save until the page is refreshed. Previous source files are backed up under `scripts/source_id_backups/classification_review/`.

Each browser tab keeps a persistent connection to the localhost server. After the last tab disconnects, the server stops following a three-second grace period. A reload or new connection cancels scheduled shutdown. Shutdown waits for an active category save and regeneration to finish. In the exceptional case that a browser or OS crash prevents disconnect detection, stop the server with `Ctrl+C` in its console.

The tray starts the dashboard BAT with `--nopause` in a hidden window. Standard output and errors are appended to `scripts/reports/classification_review_dashboard.log`. Running the internal BAT directly shows its console for immediate diagnostics and manual `Ctrl+C` shutdown.

## Process lock

Only one classification, Notion sync, or Cloudinary cleanup process can modify the same vault at a time. Lock information is written to `scripts/.runtime/automation.lock`.

When another operation already holds the lock, the second exits with `[BUSY]` and code `3` without modifying files or remote pages. The operating-system lock is released automatically when its process exits, so a remaining lock file alone should not be deleted manually.

The review dashboard holds the lock only while saving classifications and regenerating documents, not for the entire time the page is open.

## Atomic state storage

The following JSON state files are written completely to a temporary file in the same directory, then replaced using `flush`, `fsync`, and `os.replace`:

- `scripts/organizer_metadata*.json`
- `scripts/notion_sync_state*.json`
- `scripts/cloudinary_cache.json`

If an existing file contains malformed JSON, Log2Topic does not silently reset it to an empty state. The original file is preserved and the operation stops. Make a copy before attempting recovery; do not immediately delete a damaged state file.

## Tray and scheduled tasks

Only one `Log2Topic.exe` instance runs per workspace, and all normal commands are available from its right-click menu. The dedicated app owns both the process and tray icon, so Task Manager shows `Log2Topic`. In a development environment without the EXE, `Log2Topic.bat` starts the fallback PowerShell tray.

`Automation and sync settings...` calls `scripts/configure_automation.ps1` to manage a shortcut in the Windows Startup folder and the `Log2Topic_Scheduled_Update` task in Windows Task Scheduler. Modes are local-only or local followed by an external service; Notion is currently available as the external service. Mode, service, time, weekdays, missed-run behavior, and UI language are stored in `scripts/.runtime/tray_settings.json`. Legacy `Notion` mode is migrated to `External + Notion`, and old `Log2Topic_Local_Update`, `Log2Topic_Notion_Sync`, and `ResearchNotes_*` tasks are removed when settings are saved.

## Distribution layout

The Git distribution tracks the README and references, `Log2Topic.exe`, `app/Log2Topic.cs` and its rebuild script, the official CPython embeddable ZIP, generic classification rules, launch BAT files, Python scripts, classification review UI, and tests.

The supported environment is Windows 10/11 x64. A system Python installation and `PATH` setup are not required. On first launch, the EXE securely extracts `runtime/python-3.13.15-embed-amd64.zip` to `runtime/python/` and adds the project module path to `_pth`. If the ZIP or version changes, the runtime is replaced atomically. BAT launchers prefer the bundled Python and use system Python 3.10 or newer only as a development fallback.

Personal logs, attachments, `.env`, state JSON, reports, and generated documents are excluded by `.gitignore`. The public `Classification_Rules.md` is maintained manually in the distribution repository and is not copied from the private development workspace. Distribution users therefore do not need access to the private development repository or its history.

## Git management

The repository tracks automation code and generic classification rules, not personal logs. `.gitignore` excludes:

- `Daily_Logs/`, `Subject/`, `Topic_Reviews/`, and `attachments/`
- `scripts/.env`
- organizer metadata, Notion sync state, and Cloudinary cache
- reports and backups
- Obsidian and local-agent settings

## Maintenance principles

The following local capabilities are treated as stable operational behavior:

- five-level classification based on an H1 boundary and H2-H5 headings
- optional keywords and multiple classifications
- permanent Source IDs and cleanup of old generated entries
- classification review dashboard
- child reviews and Level 1-2 aggregate reviews
- process locking and atomic state storage
- Git-based Windows app distribution with bundled Python

Notion and Cloudinary remain optional integrations separated from the local default path. New external services or automatic source-editing features should be added only after a concrete need and failure cases are understood.

## Development verification

```powershell
.\scripts\build_windows_app.ps1
.\Log2Topic.exe --prepare-runtime
.\runtime\python\python.exe -m unittest discover -s tests
.\runtime\python\python.exe -m compileall -q scripts tests
.\runtime\python\python.exe .\scripts\hierarchical_classifier.py --validate-rules
.\runtime\python\python.exe .\scripts\hierarchical_classifier.py --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json --dry-run
```
