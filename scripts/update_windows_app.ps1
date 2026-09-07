[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$AssetUrl,
    [string]$ExpectedSha256,
    [int]$CurrentProcessId = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$installRoot = [IO.Path]::GetFullPath($InstallRoot)
$runtimeRoot = Join-Path $installRoot "scripts\.runtime"
$downloadPath = Join-Path $runtimeRoot "Log2Topic-update-$([Guid]::NewGuid().ToString('N')).zip"
$extractRoot = Join-Path $runtimeRoot "update-$([Guid]::NewGuid().ToString('N'))"
$logPath = Join-Path $runtimeRoot "update.log"

function Write-UpdateLog {
    param([string]$Message)
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Add-Content -LiteralPath $logPath -Value ("{0} {1}" -f (Get-Date -Format s), $Message)
}

function Get-ArchiveRoot {
    $directories = @(Get-ChildItem -LiteralPath $extractRoot -Directory)
    if ($directories.Count -eq 1 -and (Test-Path -LiteralPath (Join-Path $directories[0].FullName "Log2Topic.bat"))) {
        return $directories[0].FullName
    }
    return $extractRoot
}

function Wait-UpdateProcessExit {
    param(
        [int]$ProcessId,
        [ValidateRange(1, 2147483647)][int]$TimeoutMilliseconds = 30000
    )

    if ($ProcessId -le 0) {
        Write-UpdateLog "No application process specified; exit wait skipped."
        return
    }

    Write-UpdateLog "Waiting for application process $ProcessId to exit."
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        try {
            $process = Get-Process -Id $ProcessId -ErrorAction Stop
        }
        catch {
            # PowerShell 5.1 reports an absent PID as ProcessCommandException.
            if ($_.FullyQualifiedErrorId -eq "NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand") {
                Write-UpdateLog "Application process $ProcessId is no longer running; exit confirmed."
                return
            }
            throw
        }
        $process.Dispose()

        $remaining = $TimeoutMilliseconds - $timer.ElapsedMilliseconds
        if ($remaining -le 0) {
            throw "Timed out waiting for application process $ProcessId to exit after $TimeoutMilliseconds ms; files were not replaced."
        }
        Start-Sleep -Milliseconds ([int][Math]::Min(200, $remaining))
    }
}

function Copy-UpdatedFiles {
    param([string]$SourceRoot)

    $excludedRoots = @(
        (Join-Path $SourceRoot "Workspace"),
        (Join-Path $SourceRoot "runtime"),
        (Join-Path $SourceRoot "scripts\.runtime"),
        (Join-Path $SourceRoot ".git")
    ) | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') }

    $sourcePrefix = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\') + '\'
    foreach ($file in Get-ChildItem -LiteralPath $SourceRoot -File -Recurse) {
        $fullPath = [IO.Path]::GetFullPath($file.FullName)
        if ($excludedRoots | Where-Object { $fullPath.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) }) {
            continue
        }
        $relativePath = $fullPath.Substring($sourcePrefix.Length)
        $destination = Join-Path $installRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $fullPath -Destination $destination -Force
    }
}

try {
    Write-UpdateLog "Update download started: $AssetUrl"
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    Invoke-WebRequest -Uri $AssetUrl -OutFile $downloadPath -UseBasicParsing

    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
        $actualHash = (Get-FileHash -LiteralPath $downloadPath -Algorithm SHA256).Hash
        if (-not [string]::Equals($actualHash, $ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Update package SHA-256 mismatch."
        }
    }

    Wait-UpdateProcessExit -ProcessId $CurrentProcessId

    Write-UpdateLog "Extracting update package."
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    Expand-Archive -LiteralPath $downloadPath -DestinationPath $extractRoot -Force
    Write-UpdateLog "Update file replacement started."
    Copy-UpdatedFiles -SourceRoot (Get-ArchiveRoot)
    Write-UpdateLog "Update files installed."
    Write-UpdateLog "Restarting application."
    Start-Process -FilePath (Join-Path $installRoot "Log2Topic.exe") -WorkingDirectory $installRoot -ErrorAction Stop | Out-Null
    Write-UpdateLog "Application restart requested."
}
catch {
    Write-UpdateLog ("Update failed: " + $_.Exception.Message)
    exit 1
}
finally {
    Remove-Item -LiteralPath $downloadPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
}
