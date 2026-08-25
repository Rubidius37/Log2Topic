@echo off
chcp 65001 > nul 2>&1
setlocal

set "ROOT=%~dp0"
set "WORKSPACE=%ROOT%Workspace\"

if not exist "%WORKSPACE%Classification_Rules.md" (
    echo [ERROR] Workspace\Classification_Rules.md was not found. Restore it from Git.
    exit /b 1
)

if not exist "%WORKSPACE%Daily_Logs" mkdir "%WORKSPACE%Daily_Logs"
if not exist "%WORKSPACE%attachments" mkdir "%WORKSPACE%attachments"

echo Workspace setup is ready.
exit /b 0
