[CmdletBinding()]
param(
    [ValidateSet("Off", "Local", "External", "ExternalOriginals", "Notion")]
    [string]$Mode = "Off",
    [ValidateSet("Notion")]
    [string]$Service = "Notion",
    [ValidatePattern('^([01]\d|2[0-3]):[0-5]\d$')]
    [string]$Time = "02:30",
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string[]]$Days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    [string]$DaysCsv = "",
    [ValidateSet("Auto", "en", "ko")]
    [string]$Language = "Auto",
    [switch]$PruneBackups,
    [ValidateRange(1, 10000)]
    [int]$BackupRetentionCount = 100,
    [switch]$DisableAutoUpdateCheck,
    [switch]$EnableStartup,
    [switch]$RunMissed,
    [string]$WorkspacePath = "__KEEP__",
    [ValidateSet("", "simple", "research", "software")]
    [string]$RuleTemplate = "",
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$vaultRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$runtimeDir = Join-Path $PSScriptRoot ".runtime"
$configPath = Join-Path $runtimeDir "tray_settings.json"
$scheduledTaskName = "Log2Topic_Scheduled_Update"
$legacyTaskNames = @(
    "Log2Topic_Local_Update",
    "Log2Topic_Notion_Sync",
    "ResearchNotes_Local_Update",
    "ResearchNotes_Notion_Sync"
)
$startupDirectory = [Environment]::GetFolderPath("Startup")
$startupShortcut = Join-Path $startupDirectory "Log2Topic Tray.lnk"
$iconPath = Join-Path $vaultRoot "assets\log2topic.ico"
$effectiveMode = if ($Mode -eq "Notion") { "External" } else { $Mode }
$validDays = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
$effectiveDays = @()
if ([string]::IsNullOrWhiteSpace($DaysCsv)) {
    $effectiveDays = @($Days)
}
else {
    $effectiveDays = @($DaysCsv.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
$invalidDays = @($effectiveDays | Where-Object { $_ -notin $validDays })
if ($invalidDays.Count -gt 0) {
    throw "Invalid schedule day: $($invalidDays -join ', ')"
}

function Save-SettingsAtomically {
    param([Parameter(Mandatory = $true)]$Settings)

    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $temporaryPath = "$configPath.$PID.tmp"
    $backupPath = "$configPath.$PID.bak"
    $json = $Settings | ConvertTo-Json -Depth 4
    [IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, (New-Object Text.UTF8Encoding($false)))

    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        if (Test-Path -LiteralPath $backupPath) {
            Remove-Item -LiteralPath $backupPath -Force
        }
        [IO.File]::Replace($temporaryPath, $configPath, $backupPath)
        Remove-Item -LiteralPath $backupPath -Force
    }
    else {
        Move-Item -LiteralPath $temporaryPath -Destination $configPath
    }
}

function Set-StartupShortcut {
    param([bool]$Enabled)

    if (-not $Enabled) {
        if (Test-Path -LiteralPath $startupShortcut) {
            Remove-Item -LiteralPath $startupShortcut -Force
        }
        return
    }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($startupShortcut)
    $appPath = Join-Path $vaultRoot "Log2Topic.exe"
    if (Test-Path -LiteralPath $appPath -PathType Leaf) {
        $shortcut.TargetPath = $appPath
        $shortcut.Arguments = ""
    }
    else {
        $trayScript = Join-Path $PSScriptRoot "log2topic_tray.ps1"
        if (-not (Test-Path -LiteralPath $trayScript -PathType Leaf)) {
            throw "Tray script was not found: $trayScript"
        }
        $shortcut.TargetPath = (Join-Path $PSHOME "powershell.exe")
        $shortcut.Arguments = "-NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$trayScript`""
    }
    $shortcut.WorkingDirectory = $vaultRoot
    $shortcut.IconLocation = if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
        "$iconPath,0"
    }
    else {
        "$env:SystemRoot\System32\shell32.dll,167"
    }
    $shortcut.Description = "Start the Log2Topic tray app after Windows login"
    $shortcut.Save()
}

function Remove-ScheduledTasksByName {
    param([Parameter(Mandatory = $true)][string[]]$Names)

    $tasks = @(Get-ScheduledTask -TaskName $Names -ErrorAction SilentlyContinue)
    if ($tasks.Count -gt 0) {
        $tasks | Unregister-ScheduledTask -Confirm:$false
    }
}

function Set-ScheduledUpdate {
    Remove-ScheduledTasksByName -Names $legacyTaskNames
    if ($effectiveMode -eq "Off") {
        Remove-ScheduledTasksByName -Names @($scheduledTaskName)
        return
    }
    if ($effectiveDays.Count -eq 0) {
        throw "At least one day must be selected for automatic updates."
    }

    $batchName = if ($effectiveMode -eq "External" -and $Service -eq "Notion") {
        "run_notion_sync.bat"
    }
    elseif ($effectiveMode -eq "ExternalOriginals" -and $Service -eq "Notion") {
        "run_notion_daily_sync.bat"
    }
    else {
        "run_local.bat"
    }
    $batchArgs = if ($effectiveMode -eq "ExternalOriginals" -and $Service -eq "Notion") {
        "--all-daily --nopause"
    }
    else {
        "--nopause"
    }
    $batchPath = Join-Path $PSScriptRoot $batchName
    if (-not (Test-Path -LiteralPath $batchPath -PathType Leaf)) {
        throw "Scheduled launcher was not found: $batchPath"
    }

    $runAt = [DateTime]::ParseExact($Time, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/d /c `"`"$batchPath`" $batchArgs`"" `
        -WorkingDirectory $vaultRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $effectiveDays -At $runAt

    $settingsArguments = @{
        AllowStartIfOnBatteries = $true
        DontStopIfGoingOnBatteries = $true
        ExecutionTimeLimit = New-TimeSpan -Hours 2
        MultipleInstances = "IgnoreNew"
    }
    if ($RunMissed) {
        $settingsArguments.StartWhenAvailable = $true
    }
    $taskSettings = New-ScheduledTaskSettingsSet @settingsArguments
    $description = if ($effectiveMode -eq "External" -and $Service -eq "Notion") {
        "Update local Log2Topic documents and sync the optional Notion integration."
    }
    elseif ($effectiveMode -eq "ExternalOriginals" -and $Service -eq "Notion") {
        "Sync original Log2Topic daily logs only to the optional Notion integration."
    }
    else {
        "Update local Log2Topic documents without external services."
    }

    Register-ScheduledTask `
        -TaskName $scheduledTaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $taskSettings `
        -Force `
        -Description $description | Out-Null
}

if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "Windows Task Scheduler PowerShell commands are unavailable on this PC."
}
if ($effectiveMode -ne "Off" -and $effectiveDays.Count -eq 0) {
    throw "At least one day must be selected for automatic updates."
}
foreach ($launcherName in @("run_local.bat", "run_notion_sync.bat", "run_notion_daily_sync.bat")) {
    $launcherPath = Join-Path $PSScriptRoot $launcherName
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        throw "Scheduled launcher was not found: $launcherPath"
    }
}
if ($ValidateOnly) {
    Write-Host "Log2Topic automation configuration is valid."
    return
}

Set-ScheduledUpdate
Set-StartupShortcut -Enabled $EnableStartup.IsPresent

$existingUpdateRepo = "Rubidius37/Log2Topic"
$existingSkippedVersion = ""
$existingWorkspacePath = ""
if (Test-Path -LiteralPath $configPath -PathType Leaf) {
    try {
        $prev = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($null -ne $prev.PSObject.Properties["update_repo"] -and $prev.update_repo) {
            $existingUpdateRepo = [string]$prev.update_repo
        }
        if ($null -ne $prev.PSObject.Properties["skipped_update_version"] -and $prev.skipped_update_version) {
            $existingSkippedVersion = [string]$prev.skipped_update_version
        }
        if ($null -ne $prev.PSObject.Properties["workspace_path"] -and $prev.workspace_path) {
            $existingWorkspacePath = [string]$prev.workspace_path
        }
    }
    catch {
    }
}

$resolvedWorkspacePath = $existingWorkspacePath
if ($WorkspacePath -ne "__KEEP__") {
    $trimmedWp = $WorkspacePath.Trim()
    $defaultBundledWp = [IO.Path]::GetFullPath((Join-Path $vaultRoot "Workspace"))
    if ([string]::IsNullOrWhiteSpace($trimmedWp)) {
        $resolvedWorkspacePath = ""
    }
    else {
        $fullWp = [IO.Path]::GetFullPath($trimmedWp)
        if ([string]::Equals($fullWp, $defaultBundledWp, [StringComparison]::OrdinalIgnoreCase)) {
            $resolvedWorkspacePath = ""
        }
        else {
            $resolvedWorkspacePath = $fullWp
        }
    }
}

$settings = [ordered]@{
    version = 2
    start_at_logon = $EnableStartup.IsPresent
    schedule_mode = $effectiveMode
    external_service = $Service
    schedule_time = $Time
    schedule_days = @($effectiveDays)
    run_missed = $RunMissed.IsPresent
    ui_language = $Language
    prune_backups = $PruneBackups.IsPresent
    backup_retention_count = $BackupRetentionCount
    auto_check_updates = (-not $DisableAutoUpdateCheck.IsPresent)
    update_repo = $existingUpdateRepo
    skipped_update_version = $existingSkippedVersion
    workspace_path = $resolvedWorkspacePath
}
Save-SettingsAtomically -Settings $settings

if ($resolvedWorkspacePath -or $RuleTemplate) {
    $resolveBat = Join-Path $PSScriptRoot "resolve_python.bat"
    if (Test-Path -LiteralPath $resolveBat -PathType Leaf) {
        $targetWs = if ($resolvedWorkspacePath) { $resolvedWorkspacePath } else { Join-Path $vaultRoot "Workspace" }
        $backupRoot = Join-Path $PSScriptRoot "source_id_backups"
        $pyCode = "import sys; sys.path.insert(0, r'$PSScriptRoot'); from workspace_paths import ensure_workspace_initialized; ensure_workspace_initialized(r'$targetWs', template_name=r'$RuleTemplate' or None, backup_root=r'$backupRoot')"
        cmd.exe /d /c "call `"$resolveBat`" && %PYTHON_CMD% -c `"$pyCode`"" | Out-Null
    }
}

Write-Host "Log2Topic automation settings were updated."
