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

if not exist "%ROOT%scripts\organizer_metadata.json" (
    dir /b /s "%WORKSPACE%Daily_Logs\*.md" > nul 2>&1
    if errorlevel 1 (
        powershell.exe -NoProfile -Command "$u = New-Object System.Text.UTF8Encoding($false); [System.IO.File]::WriteAllText('%WORKSPACE%Daily_Logs\260901 일지.md', \"# Projects`n## Sample Project`n### Testing`n#### Functional Test`n저장 버튼을 누르면 입력한 내용이 파일에 기록되는 것을 확인했다.`n`n#### Regression Test`n기존 파일을 다시 열었을 때 줄바꿈이 유지되는 것을 확인했다.`n\", $u); [System.IO.File]::WriteAllText('%WORKSPACE%Daily_Logs\260902 일지.md', \"# Projects`n## Sample Project`n### Testing`n#### Functional Test`n한글 파일명으로 저장하고 다시 여는 동작을 확인했다.`n\", $u)" > nul 2>&1
    )
)

echo Workspace setup is ready.
exit /b 0
