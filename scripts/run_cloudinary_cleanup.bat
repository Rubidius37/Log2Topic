@echo off
chcp 65001 > nul 2>&1
setlocal EnableDelayedExpansion

echo ======================================================================
echo  [Log2Topic] Cloudinary Image Cleanup
echo  Execution Time: %date% %time%
echo ======================================================================

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT=%%~fI\"
set "NO_PAUSE="
set "CLEANUP_ARGS="
for %%A in (%*) do (
    if /I "%%~A"=="--nopause" (
        set "NO_PAUSE=1"
    ) else (
        set CLEANUP_ARGS=!CLEANUP_ARGS! "%%~A"
    )
)

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 exit /b 1

%PYTHON_CMD% -u "%SCRIPT_DIR%cloudinary_cleanup.py" %CLEANUP_ARGS%
if errorlevel 1 (
    echo [ERROR] Cloudinary cleanup failed!
    if not defined NO_PAUSE pause
    exit /b 1
)

echo ======================================================================
echo  [SUCCESS] Cloudinary cleanup completed.
echo ======================================================================
if not defined NO_PAUSE pause
exit /b 0
