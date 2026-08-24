@echo off
chcp 65001 > nul 2>&1
setlocal

set "ROOT=%~dp0"

if not exist "%ROOT%Classification_Rules.md" (
    echo [ERROR] Classification_Rules.md was not found. Restore it from Git.
    exit /b 1
)

if not exist "%ROOT%Daily_Logs" mkdir "%ROOT%Daily_Logs"
if not exist "%ROOT%attachments" mkdir "%ROOT%attachments"

echo Workspace setup is ready.
exit /b 0
