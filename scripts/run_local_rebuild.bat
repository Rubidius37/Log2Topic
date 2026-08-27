@echo off
chcp 65001 > nul 2>&1
setlocal

set "ROOT=%~dp0.."
set "SCRIPT_DIR=%~dp0"
cd /d "%ROOT%"

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 exit /b 1

echo This rebuilds Source ID markers after replacing the source-log corpus.
echo Existing source files are backed up under scripts\source_id_backups\rebuild.
echo.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0

%PYTHON_CMD% -u "%SCRIPT_DIR%hierarchical_classifier.py" --production --output-dir Subject --review-dir Topic_Reviews --metadata-file organizer_metadata.json --rebuild-source-ids
if errorlevel 1 (
    echo [ERROR] Source ID rebuild failed.
    pause
    exit /b 1
)
pause
exit /b 0
