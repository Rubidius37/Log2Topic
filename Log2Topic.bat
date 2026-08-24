@echo off
chcp 65001 > nul 2>&1
setlocal

set "ROOT=%~dp0"

if exist "%ROOT%setup_workspace.bat" (
    call "%ROOT%setup_workspace.bat"
    if errorlevel 1 (
        echo [ERROR] Workspace setup failed.
        pause
        exit /b 1
    )
)

if exist "%ROOT%Log2Topic.exe" (
    start "" "%ROOT%Log2Topic.exe"
    if errorlevel 1 (
        echo [ERROR] Log2Topic.exe could not be started.
        pause
        exit /b 1
    )
    exit /b 0
)

start "Log2Topic" powershell.exe -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "%ROOT%scripts\log2topic_tray.ps1"
if errorlevel 1 (
    echo [ERROR] Log2Topic could not be started.
    pause
    exit /b 1
)

exit /b 0
