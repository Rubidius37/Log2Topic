@echo off
chcp 65001 > nul 2>&1
setlocal EnableDelayedExpansion

for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
set "SCRIPT_DIR=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%setup_workspace.bat" (
    call "%ROOT%setup_workspace.bat"
    if errorlevel 1 exit /b 1
)

set "NO_PAUSE="
set "SYNC_ARGS="
set "CLASSIFY_ARGS="
for %%A in (%*) do (
    if /I "%%~A"=="--nopause" (
        set "NO_PAUSE=1"
    ) else if /I "%%~A"=="--no-persist-source-ids" (
        set CLASSIFY_ARGS=!CLASSIFY_ARGS! "%%~A"
    ) else if /I "%%~A"=="--initialize-source-ids" (
        set CLASSIFY_ARGS=!CLASSIFY_ARGS! "%%~A"
    ) else (
        set SYNC_ARGS=!SYNC_ARGS! "%%~A"
    )
)

echo ======================================================================
echo  [Log2Topic] Update Local Notes and Sync Optional Notion Integration
echo  Execution Time: %date% %time%
echo ======================================================================

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 exit /b 1

echo 1. Updating local Markdown research notes...
%PYTHON_CMD% -u "%SCRIPT_DIR%hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json %CLASSIFY_ARGS%
if errorlevel 1 (
    echo [ERROR] Local update failed. Notion was not changed.
    if not defined NO_PAUSE pause
    exit /b 1
)

echo 2. Syncing the optional Notion integration...
%PYTHON_CMD% -u "%SCRIPT_DIR%sync_to_notion.py" %SYNC_ARGS%
if errorlevel 1 (
    echo [ERROR] Optional Notion sync failed. Local files remain available.
    if not defined NO_PAUSE pause
    exit /b 1
)

echo ======================================================================
echo  [SUCCESS] Local update and optional Notion sync completed.
echo ======================================================================
if not defined NO_PAUSE pause
exit /b 0
