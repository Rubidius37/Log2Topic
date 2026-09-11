"""Offline Windows PowerShell 5.1 updater regression tests."""

import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE if (HERE / "scripts").is_dir() else HERE.parent
UPDATER = Path(os.environ.get(
    "LOG2TOPIC_TEST_UPDATER",
    str(PROJECT_ROOT / "scripts" / "update_windows_app.ps1"),
))
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
    r"System32\WindowsPowerShell\v1.0\powershell.exe"
)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(code, timeout=45):
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    env = os.environ.copy()
    # Do not inherit a PowerShell 7-only module search path from the test runner.
    env["PSModulePath"] = str(POWERSHELL.parent / "Modules")
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=env,
    )


@unittest.skipUnless(os.name == "nt", "Requires Windows PowerShell")
class UpdaterTests(unittest.TestCase):
    def test_release_response_parsing_uses_actual_desktop_code(self):
        source = (PROJECT_ROOT / 'app' / 'Log2Topic.cs').read_text(encoding='utf-8-sig')
        start = source.index('Dictionary<string, object> release = new JavaScriptSerializer()')
        end = source.index('ExpectedSha256 = digest', start)
        end = source.index('};', end) + 2
        body = source[start:end]
        harness = '''
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Web.Script.Serialization;
[assembly: System.Reflection.AssemblyVersion("1.0.5.0")]
public class Program {
    public class UpdateInfo { public string AssetUrl; public string ExpectedSha256; public Version Version; }
    static DoWorkEventArgs eventArgs;
    static void Parse(string json, bool notifyWhenCurrent) { BODY }
    public static void Test() {
        eventArgs = new DoWorkEventArgs(null);
        Parse("{\\"tag_name\\":\\"v1.0.6\\",\\"assets\\":[{\\"name\\":\\"Log2Topic-windows-v1.0.6.zip\\",\\"browser_download_url\\":\\"https://example.invalid/test.zip\\",\\"digest\\":\\"sha256:abc\\"}]}", true);
        var info = (UpdateInfo)eventArgs.Result;
        if (info.ExpectedSha256 != "abc") throw new Exception("Bad digest");
        if (info.Version.ToString(3) != "1.0.6") throw new Exception("Bad release version");
        eventArgs = new DoWorkEventArgs(null);
        Parse("{\\"tag_name\\":\\"v1.0.5\\",\\"assets\\":[]}", true);
        if ((string)eventArgs.Result != "current") throw new Exception("Same version not normalized");
        bool rejected = false;
        try { Parse("{\\"tag_name\\":\\"v1.0.6\\",\\"assets\\":[]}", true); }
        catch (InvalidDataException) { rejected = true; }
        if (!rejected) throw new Exception("Missing asset not reported");
    }
}
'''.replace('BODY', body)
        code = "Add-Type -ReferencedAssemblies System.Web.Extensions -TypeDefinition " + quote(harness) + "; [Program]::Test()"
        self.assert_success(run_ps("$ErrorActionPreference = 'Stop'; " + code))

    def run_wait(self, body):
        code = """
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw 'Updater syntax errors' }
$definition = $ast.Find({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Wait-UpdateProcessExit'
}, $true)
. ([scriptblock]::Create($definition.Extent.Text))
function Write-UpdateLog { param($Message) Write-Output $Message }
BODY
""".replace("SCRIPT", quote(UPDATER)).replace("BODY", body)
        return run_ps(code)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_already_exited_process(self):
        result = self.run_wait("Wait-UpdateProcessExit -ProcessId 2147483647")
        self.assert_success(result)
        self.assertIn("exit confirmed", result.stdout)

    def test_no_process_requested(self):
        result = self.run_wait("Wait-UpdateProcessExit -ProcessId 0")
        self.assert_success(result)
        self.assertIn("exit wait skipped", result.stdout)

    def test_exit_between_polls(self):
        result = self.run_wait(r"""
$script:lookups = 0
function Get-Process {
    param($Id, $ErrorAction)
    $script:lookups++
    if ($script:lookups -eq 1) {
        Microsoft.PowerShell.Management\Get-Process -Id $PID -ErrorAction Stop
    } else {
        Microsoft.PowerShell.Management\Get-Process -Id 2147483647 -ErrorAction Stop
    }
}
Wait-UpdateProcessExit -ProcessId 2147483647 -TimeoutMilliseconds 2000
if ($script:lookups -ne 2) { throw 'Expected a second lookup' }
""")
        self.assert_success(result)
        self.assertIn("exit confirmed", result.stdout)

    def test_timeout_is_failure(self):
        result = self.run_wait("Wait-UpdateProcessExit -ProcessId $PID -TimeoutMilliseconds 20")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Timed out waiting", result.stderr)

    def test_unexpected_lookup_error_is_failure(self):
        result = self.run_wait("""
function Get-Process { param($Id, $ErrorAction) throw 'lookup denied' }
Wait-UpdateProcessExit -ProcessId 123
""")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lookup denied", result.stderr)

    def run_install(self, mode):
        with tempfile.TemporaryDirectory(prefix="Log2Topic-updater-test-") as temp:
            root = Path(temp)
            install = root / "install"
            install.mkdir()
            (install / "Log2Topic.exe").write_text("old executable")
            excluded = ["Workspace/note.md", "runtime/keep.txt", "scripts/.runtime/keep.txt", ".git/keep.txt"]
            for relative in excluded:
                path = install / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("keep original")
            archive = root / "fixture.zip"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("Log2Topic/Log2Topic.bat", "fixture")
                package.writestr("Log2Topic/Log2Topic.exe", "new executable")
                for relative in excluded:
                    package.writestr("Log2Topic/" + relative, "must not copy")
            restart = root / "restart.txt"
            extra = ""
            process_id = "2147483647"
            if mode == "timeout":
                process_id = "$PID"
            elif mode == "lookup_error":
                extra = "function Get-Process { param($Id, $ErrorAction) throw 'lookup denied' }"
            code = """
$ErrorActionPreference = 'Stop'
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    Copy-Item -LiteralPath ARCHIVE -Destination $OutFile
}
function Start-Process {
    param($FilePath, $WorkingDirectory, $ErrorAction)
    if ($FilePath -ne (Join-Path INSTALL 'Log2Topic.exe')) { throw 'Wrong restart target' }
    if ($WorkingDirectory -ne INSTALL) { throw 'Wrong working directory' }
    Add-Content -LiteralPath RESTART -Value 'restart'
}
EXTRA
$hash = (Get-FileHash -LiteralPath ARCHIVE -Algorithm SHA256).Hash
& SCRIPT -InstallRoot INSTALL -AssetUrl 'https://example.invalid/fixture.zip' -ExpectedSha256 $hash -TargetVersion '1.0.6' -SkipRestartPrompt -CurrentProcessId PROCESS_ID
if ($LASTEXITCODE) { exit $LASTEXITCODE }
"""
            for key, value in {
                "ARCHIVE": quote(archive), "INSTALL": quote(install),
                "RESTART": quote(restart), "EXTRA": extra,
                "SCRIPT": quote(UPDATER), "PROCESS_ID": process_id,
            }.items():
                code = code.replace(key, value)
            result = run_ps(code)
            self.assertTrue((install / "scripts/.runtime/update.log").exists(), result.stdout + result.stderr)
            log = (install / "scripts/.runtime/update.log").read_text()
            if mode == "success":
                self.assert_success(result)
                self.assertEqual((install / "Log2Topic.exe").read_text(), "new executable")
                self.assertEqual(restart.read_text().splitlines(), ["restart"])
                self.assertIn("Application restart requested.", log)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((install / "Log2Topic.exe").read_text(), "old executable")
                self.assertFalse(restart.exists())
                self.assertNotIn("Update file replacement started.", log)
                self.assertIn("Timed out waiting" if mode == "timeout" else "lookup denied", log)
            for relative in excluded:
                self.assertEqual((install / relative).read_text(), "keep original")
            self.assertEqual(list((install / "scripts/.runtime").glob("*.zip")), [])
            self.assertEqual(list((install / "scripts/.runtime").glob("update-*")), [])

    def test_install_after_exit_preserves_data_and_restarts_once(self):
        self.run_install("success")

    def test_lookup_failure_blocks_file_replacement(self):
        self.run_install("lookup_error")

    def test_live_process_blocks_file_replacement_after_30_seconds(self):
        self.run_install("timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
