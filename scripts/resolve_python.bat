@echo off

set "PYTHON_CMD="
for %%I in ("%~dp0..") do set "LOG2TOPIC_ROOT=%%~fI"
set "BUNDLED_PYTHON=%LOG2TOPIC_ROOT%\runtime\python\python.exe"

if exist "%BUNDLED_PYTHON%" (
    "%BUNDLED_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD="%BUNDLED_PYTHON%""
        exit /b 0
    )
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" > nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)

echo [ERROR] Log2Topic could not find a usable Python runtime.
echo Run Log2Topic.exe once to prepare the bundled runtime.
exit /b 1
