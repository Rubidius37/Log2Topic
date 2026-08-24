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
for %%A in (%*) do (
    if /I "%%~A"=="--nopause" (
        set "NO_PAUSE=1"
    ) else (
        set SYNC_ARGS=!SYNC_ARGS! "%%~A"
    )
)

echo ======================================================================
echo  [Log2Topic] Fast Daily Note Sync - Optional Notion Integration
echo  Execution Time: %date% %time%
echo ======================================================================

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 exit /b 1

%PYTHON_CMD% -u "%SCRIPT_DIR%sync_to_notion.py" --daily-only %SYNC_ARGS%
if errorlevel 1 (
    echo [ERROR] Optional Notion Daily sync failed.
    if not defined NO_PAUSE pause
    exit /b 1
)

echo ======================================================================
echo  [SUCCESS] Optional Notion Daily sync completed.
echo ======================================================================
if not defined NO_PAUSE pause
exit /b 0
