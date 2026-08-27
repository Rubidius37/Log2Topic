# Windows automatic updates

Log2Topic checks the latest GitHub Release shortly after the tray starts and then every six hours. A manual check is also available from the tray menu.

Releases must contain an asset named `Log2Topic-windows.zip`. The updater verifies the asset SHA-256 digest when GitHub provides one, replaces application files, preserves `Workspace`, `runtime`, and `scripts/.runtime`, then starts the tray again.

To publish a release:

1. Update the source and commit the changes.
2. Create and push a semantic-version tag, for example `v1.0.1`.
3. GitHub Actions builds the Windows executable and publishes `Log2Topic-windows.zip`.

The first release containing the updater must be installed manually. Later releases can update existing installations automatically. The updater log is written to `scripts/.runtime/update.log`.
