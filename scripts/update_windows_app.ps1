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

    if ($CurrentProcessId -gt 0) {
        try {
            $process = Get-Process -Id $CurrentProcessId -ErrorAction Stop
            $process.WaitForExit(30000)
        }
        catch [ArgumentException] {
        }
    }

    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    Expand-Archive -LiteralPath $downloadPath -DestinationPath $extractRoot -Force
    Copy-UpdatedFiles -SourceRoot (Get-ArchiveRoot)
    Write-UpdateLog "Update files installed."
    Start-Process -FilePath (Join-Path $installRoot "Log2Topic.exe") -WorkingDirectory $installRoot | Out-Null
}
catch {
    Write-UpdateLog ("Update failed: " + $_.Exception.Message)
    exit 1
}
finally {
    Remove-Item -LiteralPath $downloadPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
}