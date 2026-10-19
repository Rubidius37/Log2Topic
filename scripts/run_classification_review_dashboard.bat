@echo off
chcp 65001 > nul 2>&1
setlocal

set "NO_PAUSE=0"
for %%A in (%*) do if /I "%%~A"=="--nopause" set "NO_PAUSE=1"

for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
set "SCRIPT_DIR=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%setup_workspace.bat" (
    call "%ROOT%setup_workspace.bat"
    if errorlevel 1 exit /b 1
)

echo ======================================================================
echo  [Log2Topic] Open Hierarchical Classification Review Dashboard
echo ======================================================================

call "%SCRIPT_DIR%resolve_python.bat"
if errorlevel 1 (
    if "%NO_PAUSE%"=="0" pause
    exit /b 1
)

if "%NO_PAUSE%"=="1" (
    if not exist "%SCRIPT_DIR%reports" mkdir "%SCRIPT_DIR%reports"
    echo.>> "%SCRIPT_DIR%reports\classification_review_dashboard.log"
    echo ======================================================================>> "%SCRIPT_DIR%reports\classification_review_dashboard.log"
    echo [%DATE% %TIME%] Starting classification review dashboard>> "%SCRIPT_DIR%reports\classification_review_dashboard.log"
    %PYTHON_CMD% -u "%SCRIPT_DIR%classification_review_dashboard.py" %* >> "%SCRIPT_DIR%reports\classification_review_dashboard.log" 2>&1
    if errorlevel 1 exit /b 1
    exit /b 0
)

%PYTHON_CMD% -u "%SCRIPT_DIR%classification_review_dashboard.py" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start the classification review dashboard.
    echo Check Classification_Rules.md and the console output above.
    echo.
    pause
    exit /b 1
)
exit /b 0
