[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$vaultRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$workspaceRoot = Join-Path $vaultRoot "Workspace"
if (-not (Test-Path -LiteralPath (Join-Path $workspaceRoot "Classification_Rules.md") -PathType Leaf)) {
    $workspaceRoot = $vaultRoot
}
$runtimeDir = Join-Path $PSScriptRoot ".runtime"
$configPath = Join-Path $runtimeDir "tray_settings.json"
$configurationScript = Join-Path $PSScriptRoot "configure_automation.ps1"
$iconPath = Join-Path $vaultRoot "assets\log2topic.ico"
$requiredLaunchers = @(
    "run_local.bat",
    "run_classification_review_dashboard.bat",
    "run_notion_daily_sync.bat",
    "run_notion_sync.bat",
    "run_local_rebuild.bat"
)
$dayDefinitions = @(
    [PSCustomObject]@{ Value = "Monday"; Label = "월" },
    [PSCustomObject]@{ Value = "Tuesday"; Label = "화" },
    [PSCustomObject]@{ Value = "Wednesday"; Label = "수" },
    [PSCustomObject]@{ Value = "Thursday"; Label = "목" },
    [PSCustomObject]@{ Value = "Friday"; Label = "금" },
    [PSCustomObject]@{ Value = "Saturday"; Label = "토" },
    [PSCustomObject]@{ Value = "Sunday"; Label = "일" }
)

trap {
    try {
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        $errorPath = Join-Path $runtimeDir "tray_error.log"
        $errorText = ($_ | Out-String) + [Environment]::NewLine
        [IO.File]::WriteAllText($errorPath, $errorText, (New-Object Text.UTF8Encoding($false)))
        [Windows.Forms.MessageBox]::Show(
            "Log2Topic 트레이를 실행하지 못했습니다.`n`n$errorPath",
            "Log2Topic 실행 오류",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
    catch {
    }
    exit 1
}

foreach ($launcher in $requiredLaunchers) {
    $launcherPath = Join-Path $PSScriptRoot $launcher
    if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
        throw "Required launcher was not found: $launcherPath"
    }
}
if (-not (Test-Path -LiteralPath $configurationScript -PathType Leaf)) {
    throw "Automation configuration script was not found: $configurationScript"
}
if ($ValidateOnly) {
    Write-Host "Log2Topic tray files are valid."
    return
}

function Get-DefaultSettings {
    return [PSCustomObject]@{
        version = 1
        start_at_logon = $false
        schedule_mode = "Off"
        external_service = "Notion"
        schedule_time = "02:30"
        schedule_days = @("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        run_missed = $true
    }
}

function Get-TraySettings {
    $defaults = Get-DefaultSettings
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        return $defaults
    }

    try {
        $saved = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        foreach ($propertyName in @("start_at_logon", "schedule_mode", "external_service", "schedule_time", "schedule_days", "run_missed")) {
            if ($null -ne $saved.PSObject.Properties[$propertyName]) {
                $defaults.$propertyName = $saved.$propertyName
            }
        }
        if ($defaults.schedule_mode -eq "Notion") {
            $defaults.schedule_mode = "External"
            $defaults.external_service = "Notion"
        }
        return $defaults
    }
    catch {
        [Windows.Forms.MessageBox]::Show(
            "자동 실행 설정 파일을 읽을 수 없습니다. 기본값으로 열겠습니다.`n`n$($_.Exception.Message)",
            "Log2Topic 설정 경고",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return $defaults
    }
}

function Show-Notification {
    param(
        [string]$Title,
        [string]$Message,
        [Windows.Forms.ToolTipIcon]$Icon = [Windows.Forms.ToolTipIcon]::Info
    )

    $script:notifyIcon.BalloonTipTitle = $Title
    $script:notifyIcon.BalloonTipText = $Message
    $script:notifyIcon.BalloonTipIcon = $Icon
    $script:notifyIcon.ShowBalloonTip(3500)
}

function Start-InternalBatch {
    param(
        [Parameter(Mandatory = $true)][string]$Filename,
        [string]$Arguments = "",
        [switch]$Hidden
    )

    $batchPath = Join-Path $PSScriptRoot $Filename
    $commandLine = if ([string]::IsNullOrWhiteSpace($Arguments)) {
        "`"`"$batchPath`"`""
    }
    else {
        "`"`"$batchPath`" $Arguments`""
    }
    if ($Hidden) {
        Start-Process -FilePath $env:ComSpec -ArgumentList "/d /c $commandLine" -WorkingDirectory $vaultRoot -WindowStyle Hidden | Out-Null
    }
    else {
        Start-Process -FilePath $env:ComSpec -ArgumentList "/d /c $commandLine" -WorkingDirectory $vaultRoot | Out-Null
    }
}

function Open-PathInExplorer {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
    Start-Process -FilePath "explorer.exe" -ArgumentList "`"$Path`"" | Out-Null
}

function Get-ScheduleSummary {
    param($Settings)

    switch ($Settings.schedule_mode) {
        "Local" { $modeLabel = "로컬 갱신" }
        "External" { $modeLabel = "외부 서비스 ($($Settings.external_service))" }
        default { return "자동 동기화: 사용 안 함" }
    }
    return "자동 동기화: $modeLabel $($Settings.schedule_time)"
}

function Show-SettingsDialog {
    $settings = Get-TraySettings
    $form = New-Object Windows.Forms.Form
    $form.Text = "Log2Topic 설정"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object Drawing.Size(420, 405)
    $form.Font = New-Object Drawing.Font("Segoe UI", 9)

    $intro = New-Object Windows.Forms.Label
    $intro.Location = New-Object Drawing.Point(20, 18)
    $intro.Size = New-Object Drawing.Size(380, 42)
    $intro.Text = "트레이 자동 실행과 정기 갱신 시간을 설정합니다.`n외부 서비스는 해당 서비스의 연동 설정이 완료된 경우에만 선택하세요."
    $form.Controls.Add($intro)

    $startupCheck = New-Object Windows.Forms.CheckBox
    $startupCheck.Location = New-Object Drawing.Point(20, 70)
    $startupCheck.Size = New-Object Drawing.Size(330, 24)
    $startupCheck.Text = "Windows 로그인 시 Log2Topic 트레이 자동 실행"
    $startupCheck.Checked = [bool]$settings.start_at_logon
    $form.Controls.Add($startupCheck)

    $modeLabel = New-Object Windows.Forms.Label
    $modeLabel.Location = New-Object Drawing.Point(20, 112)
    $modeLabel.Size = New-Object Drawing.Size(110, 22)
    $modeLabel.Text = "자동 작업"
    $form.Controls.Add($modeLabel)

    $modeCombo = New-Object Windows.Forms.ComboBox
    $modeCombo.Location = New-Object Drawing.Point(135, 108)
    $modeCombo.Size = New-Object Drawing.Size(245, 24)
    $modeCombo.DropDownStyle = "DropDownList"
    [void]$modeCombo.Items.Add("사용 안 함")
    [void]$modeCombo.Items.Add("로컬 문서 갱신")
    [void]$modeCombo.Items.Add("로컬 갱신 후 외부 서비스 동기화")
    $modeCombo.SelectedIndex = switch ($settings.schedule_mode) {
        "Local" { 1 }
        "External" { 2 }
        "Notion" { 2 }
        default { 0 }
    }
    $form.Controls.Add($modeCombo)

    $timeLabel = New-Object Windows.Forms.Label
    $serviceLabel = New-Object Windows.Forms.Label
    $serviceLabel.Location = New-Object Drawing.Point(20, 153)
    $serviceLabel.Size = New-Object Drawing.Size(110, 22)
    $serviceLabel.Text = "외부 서비스"
    $form.Controls.Add($serviceLabel)

    $serviceCombo = New-Object Windows.Forms.ComboBox
    $serviceCombo.Location = New-Object Drawing.Point(135, 149)
    $serviceCombo.Size = New-Object Drawing.Size(245, 24)
    $serviceCombo.DropDownStyle = "DropDownList"
    [void]$serviceCombo.Items.Add("Notion")
    $serviceCombo.SelectedIndex = 0
    $form.Controls.Add($serviceCombo)

    $timeLabel.Location = New-Object Drawing.Point(20, 194)
    $timeLabel.Size = New-Object Drawing.Size(110, 22)
    $timeLabel.Text = "실행 시간"
    $form.Controls.Add($timeLabel)

    $timePicker = New-Object Windows.Forms.DateTimePicker
    $timePicker.Location = New-Object Drawing.Point(135, 190)
    $timePicker.Size = New-Object Drawing.Size(100, 24)
    $timePicker.Format = "Custom"
    $timePicker.CustomFormat = "HH:mm"
    $timePicker.ShowUpDown = $true
    try {
        $parsedTime = [DateTime]::ParseExact([string]$settings.schedule_time, "HH:mm", [Globalization.CultureInfo]::InvariantCulture)
        $timePicker.Value = Get-Date -Hour $parsedTime.Hour -Minute $parsedTime.Minute -Second 0
    }
    catch {
        $timePicker.Value = Get-Date -Hour 2 -Minute 30 -Second 0
    }
    $form.Controls.Add($timePicker)

    $daysLabel = New-Object Windows.Forms.Label
    $daysLabel.Location = New-Object Drawing.Point(20, 235)
    $daysLabel.Size = New-Object Drawing.Size(110, 22)
    $daysLabel.Text = "실행 요일"
    $form.Controls.Add($daysLabel)

    $daysList = New-Object Windows.Forms.CheckedListBox
    $daysList.Location = New-Object Drawing.Point(135, 231)
    $daysList.Size = New-Object Drawing.Size(245, 60)
    $daysList.MultiColumn = $true
    $daysList.ColumnWidth = 48
    $daysList.CheckOnClick = $true
    $selectedDays = @($settings.schedule_days)
    for ($index = 0; $index -lt $dayDefinitions.Count; $index++) {
        [void]$daysList.Items.Add($dayDefinitions[$index].Label)
        $daysList.SetItemChecked($index, $dayDefinitions[$index].Value -in $selectedDays)
    }
    $form.Controls.Add($daysList)

    $missedCheck = New-Object Windows.Forms.CheckBox
    $missedCheck.Location = New-Object Drawing.Point(20, 311)
    $missedCheck.Size = New-Object Drawing.Size(360, 24)
    $missedCheck.Text = "예약 시간에 PC가 꺼져 있었다면 다음 기회에 실행"
    $missedCheck.Checked = [bool]$settings.run_missed
    $form.Controls.Add($missedCheck)

    $saveButton = New-Object Windows.Forms.Button
    $saveButton.Location = New-Object Drawing.Point(224, 358)
    $saveButton.Size = New-Object Drawing.Size(76, 30)
    $saveButton.Text = "저장"
    $saveButton.DialogResult = [Windows.Forms.DialogResult]::None
    $form.Controls.Add($saveButton)

    $cancelButton = New-Object Windows.Forms.Button
    $cancelButton.Location = New-Object Drawing.Point(308, 358)
    $cancelButton.Size = New-Object Drawing.Size(76, 30)
    $cancelButton.Text = "취소"
    $cancelButton.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.CancelButton = $cancelButton
    $form.Controls.Add($cancelButton)

    $updateEnabledState = {
        $enabled = $modeCombo.SelectedIndex -ne 0
        $serviceCombo.Enabled = $modeCombo.SelectedIndex -eq 2
        $timePicker.Enabled = $enabled
        $daysList.Enabled = $enabled
        $missedCheck.Enabled = $enabled
    }
    $modeCombo.Add_SelectedIndexChanged($updateEnabledState)
    & $updateEnabledState

    $saveButton.Add_Click({
        $mode = switch ($modeCombo.SelectedIndex) {
            1 { "Local" }
            2 { "External" }
            default { "Off" }
        }
        $chosenDays = @()
        for ($index = 0; $index -lt $dayDefinitions.Count; $index++) {
            if ($daysList.GetItemChecked($index)) {
                $chosenDays += $dayDefinitions[$index].Value
            }
        }
        if ($mode -ne "Off" -and $chosenDays.Count -eq 0) {
            [Windows.Forms.MessageBox]::Show(
                "자동 작업을 사용할 때는 실행 요일을 하나 이상 선택하세요.",
                "Log2Topic 설정",
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            return
        }
        if ($chosenDays.Count -eq 0) {
            $chosenDays = @($dayDefinitions | ForEach-Object { $_.Value })
        }

        try {
            & $configurationScript `
                -Mode $mode `
                -Service "Notion" `
                -Time $timePicker.Value.ToString("HH:mm") `
                -Days $chosenDays `
                -EnableStartup:$startupCheck.Checked `
                -RunMissed:$missedCheck.Checked
            $form.DialogResult = [Windows.Forms.DialogResult]::OK
            $form.Close()
        }
        catch {
            [Windows.Forms.MessageBox]::Show(
                "설정을 저장하지 못했습니다.`n`n$($_.Exception.Message)",
                "Log2Topic 설정 오류",
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Error
            ) | Out-Null
        }
    })

    $result = $form.ShowDialog()
    $form.Dispose()
    if ($result -eq [Windows.Forms.DialogResult]::OK) {
        $script:currentSettings = Get-TraySettings
        $script:scheduleMenuItem.Text = Get-ScheduleSummary -Settings $script:currentSettings
        Show-Notification -Title "Log2Topic" -Message "자동 실행 설정을 저장했습니다."
    }
}

$hashProvider = [Security.Cryptography.SHA256]::Create()
try {
    $rootBytes = [Text.Encoding]::UTF8.GetBytes($vaultRoot.ToLowerInvariant())
    $rootHash = ([BitConverter]::ToString($hashProvider.ComputeHash($rootBytes))).Replace("-", "").Substring(0, 16)
}
finally {
    $hashProvider.Dispose()
}
$createdNew = $false
$mutex = New-Object Threading.Mutex($true, "Local\Log2TopicTray_$rootHash", [ref]$createdNew)
if (-not $createdNew) {
    $mutex.Dispose()
    return
}

$firstRun = -not (Test-Path -LiteralPath $configPath -PathType Leaf)
$script:currentSettings = Get-TraySettings
$script:notifyIcon = New-Object Windows.Forms.NotifyIcon
$script:customIcon = $null
if (Test-Path -LiteralPath $iconPath -PathType Leaf) {
    $script:customIcon = New-Object Drawing.Icon($iconPath)
    $script:notifyIcon.Icon = $script:customIcon
}
else {
    $script:notifyIcon.Icon = [Drawing.SystemIcons]::Application
}
$script:notifyIcon.Text = "Log2Topic"
$script:notifyIcon.Visible = $true

$contextMenu = New-Object Windows.Forms.ContextMenuStrip
$localItem = $contextMenu.Items.Add("로컬 문서 갱신")
$reviewItem = $contextMenu.Items.Add("분류 검토 대시보드 열기")
[void]$contextMenu.Items.Add((New-Object Windows.Forms.ToolStripSeparator))
$externalServicesItem = $contextMenu.Items.Add("외부 서비스")
$notionItem = $externalServicesItem.DropDownItems.Add("Notion")
$dailyNotionItem = $notionItem.DropDownItems.Add("최근 일지 동기화")
$fullNotionItem = $notionItem.DropDownItems.Add("전체 동기화")
[void]$contextMenu.Items.Add((New-Object Windows.Forms.ToolStripSeparator))
$openWorkspaceItem = $contextMenu.Items.Add("작업 폴더 열기")
$openLogsItem = $contextMenu.Items.Add("실행 로그 열기")
[void]$contextMenu.Items.Add((New-Object Windows.Forms.ToolStripSeparator))
$script:scheduleMenuItem = $contextMenu.Items.Add((Get-ScheduleSummary -Settings $script:currentSettings))
$settingsItem = $contextMenu.Items.Add("자동 실행 및 동기화 설정...")
[void]$contextMenu.Items.Add((New-Object Windows.Forms.ToolStripSeparator))
$exitItem = $contextMenu.Items.Add("종료")

$localItem.Add_Click({
    Start-InternalBatch -Filename "run_local.bat"
    Show-Notification -Title "Log2Topic" -Message "로컬 문서 갱신을 시작했습니다."
})
$reviewItem.Add_Click({
    Start-InternalBatch -Filename "run_classification_review_dashboard.bat" -Arguments "--nopause" -Hidden
    Show-Notification -Title "Log2Topic" -Message "분류 검토 대시보드를 여는 중입니다."
})
$dailyNotionItem.Add_Click({
    Start-InternalBatch -Filename "run_notion_daily_sync.bat"
    Show-Notification -Title "Log2Topic" -Message "최근 일지 Notion 동기화를 시작했습니다."
})
$fullNotionItem.Add_Click({
    Start-InternalBatch -Filename "run_notion_sync.bat"
    Show-Notification -Title "Log2Topic" -Message "전체 Notion 동기화를 시작했습니다."
})
$openWorkspaceItem.Add_Click({ Open-PathInExplorer -Path $workspaceRoot })
$openLogsItem.Add_Click({ Open-PathInExplorer -Path (Join-Path $PSScriptRoot "reports") })
$script:scheduleMenuItem.Enabled = $false
$settingsItem.Add_Click({ Show-SettingsDialog })
$script:notifyIcon.Add_DoubleClick({ Open-PathInExplorer -Path $vaultRoot })
$exitItem.Add_Click({ [Windows.Forms.Application]::ExitThread() })
$script:notifyIcon.ContextMenuStrip = $contextMenu

try {
    Show-Notification -Title "Log2Topic" -Message "트레이에서 실행 기능과 자동 동기화 설정을 사용할 수 있습니다."
    $firstRunTimer = $null
    if ($firstRun) {
        $firstRunTimer = New-Object Windows.Forms.Timer
        $firstRunTimer.Interval = 500
        $firstRunTimer.Add_Tick({
            $firstRunTimer.Stop()
            Show-SettingsDialog
        })
        $firstRunTimer.Start()
    }
    [Windows.Forms.Application]::Run()
}
finally {
    if ($null -ne $firstRunTimer) {
        $firstRunTimer.Dispose()
    }
    $script:notifyIcon.Visible = $false
    $contextMenu.Dispose()
    $script:notifyIcon.Dispose()
    if ($null -ne $script:customIcon) {
        $script:customIcon.Dispose()
    }
    if ($createdNew) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
