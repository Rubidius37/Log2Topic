[CmdletBinding()]
param(
    [switch]$SkipRuntimeDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$source = Join-Path $root "app\Log2Topic.cs"
$output = Join-Path $root "Log2Topic.exe"
$icon = Join-Path $root "assets\log2topic.ico"
$runtimeDirectory = Join-Path $root "runtime"
$pythonVersion = "3.13.15"
$archiveName = "python-$pythonVersion-embed-amd64.zip"
$archivePath = Join-Path $runtimeDirectory $archiveName
$archiveUrl = "https://www.python.org/ftp/python/$pythonVersion/$archiveName"
$archiveSha256 = "D1F04D990AEE1253D8569E8E5104E30FA9F5FA830899F14843448872D936A2CF"

function Resolve-CSharpCompiler {
    $candidates = @(
        (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "The .NET Framework C# compiler was not found."
}

if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "Windows app source was not found: $source"
}
if (-not (Test-Path -LiteralPath $icon -PathType Leaf)) {
    throw "Log2Topic icon was not found: $icon"
}

New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null
if (-not $SkipRuntimeDownload -and -not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    $temporaryArchive = "$archivePath.download"
    try {
        Write-Host "Downloading official CPython $pythonVersion embeddable runtime..."
        Invoke-WebRequest -Uri $archiveUrl -OutFile $temporaryArchive -UseBasicParsing
        Move-Item -LiteralPath $temporaryArchive -Destination $archivePath
    }
    finally {
        if (Test-Path -LiteralPath $temporaryArchive) {
            Remove-Item -LiteralPath $temporaryArchive -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $archivePath -PathType Leaf)) {
    throw "Python runtime archive was not found: $archivePath"
}
$actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
if ($actualHash -ne $archiveSha256) {
    throw "Python runtime SHA-256 mismatch. Expected $archiveSha256 but found $actualHash."
}

$compiler = Resolve-CSharpCompiler
$references = @(
    "System.dll",
    "System.Core.dll",
    "System.Drawing.dll",
    "System.Windows.Forms.dll",
    "System.Web.Extensions.dll",
    "System.IO.Compression.dll",
    "System.IO.Compression.FileSystem.dll"
)
$arguments = @(
    "/nologo",
    "/target:winexe",
    "/optimize+",
    "/platform:anycpu",
    "/out:$output",
    "/win32icon:$icon"
) + @($references | ForEach-Object { "/reference:$_" }) + @($source)

Write-Host "Building Log2Topic.exe..."
& $compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "C# compiler failed with exit code $LASTEXITCODE."
}

Write-Host "Built: $output"
if (-not $SkipRuntimeDownload) {
    Write-Host "Runtime: $archivePath"
}
