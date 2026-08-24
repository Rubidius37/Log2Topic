[CmdletBinding()]
param(
    [ValidateSet("Off", "Local", "External", "Notion")]
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
    [switch]$EnableStartup,
    [switch]$RunMissed,
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
    else {
        "run_local.bat"
    }
    $batchPath = Join-Path $PSScriptRoot $batchName
    if (-not (Test-Path -LiteralPath $batchPath -PathType Leaf)) {
        throw "Scheduled launcher was not found: $batchPath"
    }

    $runAt = [DateTime]::ParseExact($Time, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
    $action = New-ScheduledTaskAction `
        -Execute "cmd.exe" `
        -Argument "/d /c `"`"$batchPath`" --nopause`"" `
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
foreach ($launcherName in @("run_local.bat", "run_notion_sync.bat")) {
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

$settings = [ordered]@{
    version = 2
    start_at_logon = $EnableStartup.IsPresent
    schedule_mode = $effectiveMode
    external_service = $Service
    schedule_time = $Time
    schedule_days = @($effectiveDays)
    run_missed = $RunMissed.IsPresent
    ui_language = $Language
}
Save-SettingsAtomically -Settings $settings

Write-Host "Log2Topic automation settings were updated."
