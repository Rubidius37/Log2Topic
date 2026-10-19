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
set "DRY_RUN="
set "CLASSIFY_ARGS="
for %%A in (%*) do (
    if /I "%%~A"=="--nopause" (
        set "NO_PAUSE=1"
    ) else (
        if /I "%%~A"=="--dry-run" set "DRY_RUN=1"
        set CLASSIFY_ARGS=!CLASSIFY_ARGS! "%%~A"
    )
)

echo ======================================================================
echo  [Log2Topic] Update Local Markdown Research Notes
echo  Execution Time: %date% %time%
echo ======================================================================

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 exit /b 1

%PYTHON_CMD% -u "%SCRIPT_DIR%hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json %CLASSIFY_ARGS%
if errorlevel 1 (
    echo [ERROR] Local update failed!
    if not defined NO_PAUSE pause
    exit /b 1
)

echo ======================================================================
if defined DRY_RUN (
    echo  [SUCCESS] Local dry-run completed. No files were updated.
) else (
    echo  [SUCCESS] Local Subject and Topic Review files were updated.
)
echo ======================================================================
if not defined NO_PAUSE pause
exit /b 0
