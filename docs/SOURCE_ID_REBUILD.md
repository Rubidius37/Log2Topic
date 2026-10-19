# Replacing source logs

## Heading changes

After editing classification headings, run the normal local update. If the current rules merge several Source ID comments into one source unit, the classifier keeps the ID immediately below the classification heading (ignoring blank lines), or the first ID in that unit if none is there. It removes the other active ID comments and places the retained ID directly below the heading. Body text, nested headings, quoted ID comments, and fenced code examples are preserved. Headings and ID comments inside fenced code are treated as example content. Originals are backed up under `scripts/source_id_backups/automatic` before replacement.

IDs shared by different source units or files still produce an error. `scripts/run_local.bat --dry-run` lists each planned consolidation with its retained and removed IDs without changing source documents, generated documents, or metadata. A normal update also removes obsolete generated documents belonging to discarded IDs. You do not need to rebuild every ID for a heading change.

## Replacing an entire source corpus

Use this procedure when replacing `Workspace/Daily_Logs` with a source-log corpus from another installation.

1. Close any running local update or Notion sync.
2. Replace the files under `Workspace/Daily_Logs`.
3. From the tray menu, choose `Rebuild after replacing source logs`, or run `scripts/run_local_rebuild.bat`.
4. Confirm the prompt. The original files are backed up under `scripts/source_id_backups/rebuild`.
5. Run the normal local update again if needed.

The rebuild removes existing `research-notes-source-id` comments before classification. Existing IDs are reused when the source path and heading anchor still match the saved metadata; otherwise new IDs are generated. Normal application updates do not run this operation and do not replace `Workspace` or `scripts/.runtime`.
