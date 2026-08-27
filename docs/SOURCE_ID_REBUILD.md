# Replacing source logs

Use this procedure when replacing `Workspace/Daily_Logs` with a source-log corpus from another installation.

1. Close any running local update or Notion sync.
2. Replace the files under `Workspace/Daily_Logs`.
3. From the tray menu, choose `Rebuild after replacing source logs`, or run `scripts/run_local_rebuild.bat`.
4. Confirm the prompt. The original files are backed up under `scripts/source_id_backups/rebuild`.
5. Run the normal local update again if needed.

The rebuild removes existing `research-notes-source-id` comments before classification. Existing IDs are reused when the source path and heading anchor still match the saved metadata; otherwise new IDs are generated. Normal application updates do not run this operation and do not replace `Workspace` or `scripts/.runtime`.
