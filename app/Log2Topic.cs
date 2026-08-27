using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Log2Topic")]
[assembly: AssemblyDescription("Local-first Markdown research log organizer")]
[assembly: AssemblyCompany("Log2Topic")]
[assembly: AssemblyProduct("Log2Topic")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Log2Topic contributors")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace Log2TopicDesktop
{
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            string root = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory);
            UiText.Initialize(root);
            string mutexName = "Local\\Log2TopicDesktop_" + HashPath(root).Substring(0, 16);
            bool createdNew;
            using (Mutex mutex = new Mutex(true, mutexName, out createdNew))
            {
                if (!createdNew)
                {
                    return 0;
                }

                try
                {
                    WorkspaceBootstrap.Ensure(root);
                    RuntimeBootstrap.Ensure(root);
                    if (args.Any(value => string.Equals(value, "--prepare-runtime", StringComparison.OrdinalIgnoreCase)))
                    {
                        return 0;
                    }

                    NativeMethods.SetCurrentProcessExplicitAppUserModelID("Log2Topic.Desktop");
                    Application.EnableVisualStyles();
                    Application.SetCompatibleTextRenderingDefault(false);
                    bool showSettings = args.Any(value => string.Equals(value, "--settings", StringComparison.OrdinalIgnoreCase));
                    Application.Run(new TrayApplicationContext(root, showSettings));
                    return 0;
                }
                catch (Exception exception)
                {
                    WriteStartupError(root, exception);
                    if (!args.Any(value => string.Equals(value, "--prepare-runtime", StringComparison.OrdinalIgnoreCase)))
                    {
                        MessageBox.Show(
                            UiText.Get("Log2Topic could not start.", "Log2Topic을 실행하지 못했습니다.") + "\n\n" + exception.Message +
                            "\n\n" + UiText.Get("Details: scripts\\.runtime\\app_error.log", "자세한 내용: scripts\\.runtime\\app_error.log"),
                            UiText.Get("Log2Topic startup error", "Log2Topic 실행 오류"),
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Error);
                    }
                    return 1;
                }
            }
        }

        private static string HashPath(string value)
        {
            using (SHA256 sha256 = SHA256.Create())
            {
                byte[] hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(value.ToLowerInvariant()));
                return BitConverter.ToString(hash).Replace("-", string.Empty);
            }
        }

        private static void WriteStartupError(string root, Exception exception)
        {
            try
            {
                string directory = Path.Combine(root, "scripts", ".runtime");
                Directory.CreateDirectory(directory);
                File.WriteAllText(
                    Path.Combine(directory, "app_error.log"),
                    DateTime.Now.ToString("s") + Environment.NewLine + exception + Environment.NewLine,
                    new UTF8Encoding(false));
            }
            catch
            {
            }
        }
    }

    internal static class UiText
    {
        internal const string Auto = "Auto";
        internal const string English = "en";
        internal const string Korean = "ko";
        private static bool useKorean;

        internal static void Initialize(string root)
        {
            string requested = Environment.GetEnvironmentVariable("LOG2TOPIC_LANGUAGE") ?? Auto;
            string path = Path.Combine(root, "scripts", ".runtime", "tray_settings.json");
            try
            {
                if (File.Exists(path))
                {
                    JavaScriptSerializer serializer = new JavaScriptSerializer();
                    Dictionary<string, object> value = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
                    object raw;
                    if (string.Equals(requested, Auto, StringComparison.OrdinalIgnoreCase) &&
                        value.TryGetValue("ui_language", out raw) && raw != null)
                    {
                        requested = Convert.ToString(raw);
                    }
                }
            }
            catch
            {
            }
            SetLanguage(requested);
        }

        internal static void SetLanguage(string requested)
        {
            if (string.Equals(requested, Korean, StringComparison.OrdinalIgnoreCase))
            {
                useKorean = true;
                return;
            }
            if (string.Equals(requested, English, StringComparison.OrdinalIgnoreCase))
            {
                useKorean = false;
                return;
            }
            useKorean = string.Equals(CultureInfo.CurrentUICulture.TwoLetterISOLanguageName, "ko", StringComparison.OrdinalIgnoreCase);
        }

        internal static string Get(string english, string korean)
        {
            return useKorean ? korean : english;
        }
    }

    internal static class WorkspaceBootstrap
    {
        internal static string ResolvePath(string root)
        {
            string bundledWorkspace = Path.Combine(root, "Workspace");
            string bundledRules = Path.Combine(bundledWorkspace, "Classification_Rules.md");
            return File.Exists(bundledRules) ? bundledWorkspace : root;
        }

        internal static void Ensure(string root)
        {
            string workspaceRoot = ResolvePath(root);
            string rulesPath = Path.Combine(workspaceRoot, "Classification_Rules.md");
            if (!File.Exists(rulesPath))
            {
                throw new FileNotFoundException(
                    UiText.Get(
                        "Classification_Rules.md is missing. Restore it inside Workspace.",
                        "Classification_Rules.md가 없습니다. Workspace 폴더 안에서 복원하세요."),
                    rulesPath);
            }

            Directory.CreateDirectory(Path.Combine(workspaceRoot, "Daily_Logs"));
            Directory.CreateDirectory(Path.Combine(workspaceRoot, "attachments"));
        }
    }

    internal static class RuntimeBootstrap
    {
        internal const string PythonVersion = "3.13.15";
        internal const string ArchiveName = "python-3.13.15-embed-amd64.zip";

        internal static void Ensure(string root)
        {
            string runtimeRoot = Path.Combine(root, "runtime");
            string archivePath = Path.Combine(runtimeRoot, ArchiveName);
            string pythonRoot = Path.Combine(runtimeRoot, "python");
            string pythonPath = Path.Combine(pythonRoot, "python.exe");
            string markerPath = Path.Combine(pythonRoot, "runtime-version.txt");

            if (File.Exists(pythonPath) && File.Exists(markerPath) &&
                string.Equals(File.ReadAllText(markerPath).Trim(), PythonVersion, StringComparison.Ordinal))
            {
                return;
            }
            if (!File.Exists(archivePath))
            {
                throw new FileNotFoundException(
                    UiText.Get("The bundled Python runtime is missing: ", "프로젝트 전용 Python 런타임 파일이 없습니다: ") + archivePath,
                    archivePath);
            }

            Directory.CreateDirectory(runtimeRoot);
            string temporaryRoot = Path.Combine(runtimeRoot, "python.extract-" + Guid.NewGuid().ToString("N"));
            string backupRoot = Path.Combine(runtimeRoot, "python.backup-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temporaryRoot);
            try
            {
                ExtractSafely(archivePath, temporaryRoot);
                ConfigureSearchPath(temporaryRoot);
                File.WriteAllText(
                    Path.Combine(temporaryRoot, "runtime-version.txt"),
                    PythonVersion + Environment.NewLine,
                    new UTF8Encoding(false));

                bool movedOldRuntime = false;
                if (Directory.Exists(pythonRoot))
                {
                    Directory.Move(pythonRoot, backupRoot);
                    movedOldRuntime = true;
                }
                try
                {
                    Directory.Move(temporaryRoot, pythonRoot);
                    if (movedOldRuntime)
                    {
                        Directory.Delete(backupRoot, true);
                    }
                }
                catch
                {
                    if (Directory.Exists(pythonRoot))
                    {
                        Directory.Delete(pythonRoot, true);
                    }
                    if (movedOldRuntime && Directory.Exists(backupRoot))
                    {
                        Directory.Move(backupRoot, pythonRoot);
                    }
                    throw;
                }
            }
            finally
            {
                if (Directory.Exists(temporaryRoot))
                {
                    Directory.Delete(temporaryRoot, true);
                }
                if (Directory.Exists(backupRoot))
                {
                    Directory.Delete(backupRoot, true);
                }
            }
        }

        private static void ExtractSafely(string archivePath, string destinationRoot)
        {
            string destinationPrefix = Path.GetFullPath(destinationRoot)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            using (FileStream stream = File.OpenRead(archivePath))
            using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read))
            {
                foreach (ZipArchiveEntry entry in archive.Entries)
                {
                    string destination = Path.GetFullPath(Path.Combine(destinationRoot, entry.FullName));
                    if (!destination.StartsWith(destinationPrefix, StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidDataException(UiText.Get("The Python runtime ZIP contains an invalid path: ", "Python 런타임 ZIP에 잘못된 경로가 있습니다: ") + entry.FullName);
                    }
                    if (string.IsNullOrEmpty(entry.Name))
                    {
                        Directory.CreateDirectory(destination);
                        continue;
                    }
                    Directory.CreateDirectory(Path.GetDirectoryName(destination));
                    entry.ExtractToFile(destination, true);
                }
            }
        }

        private static void ConfigureSearchPath(string pythonRoot)
        {
            string pathFile = Directory.GetFiles(pythonRoot, "python*._pth").FirstOrDefault();
            if (pathFile == null)
            {
                throw new InvalidDataException(UiText.Get("The embedded Python runtime ._pth file was not found.", "Python 임베디드 런타임의 ._pth 파일을 찾지 못했습니다."));
            }
            List<string> lines = File.ReadAllLines(pathFile).ToList();
            AddPathIfMissing(lines, @"..\..");
            AddPathIfMissing(lines, @"..\..\scripts");
            File.WriteAllLines(pathFile, lines, new UTF8Encoding(false));
        }

        private static void AddPathIfMissing(List<string> lines, string value)
        {
            if (!lines.Any(line => string.Equals(line.Trim(), value, StringComparison.OrdinalIgnoreCase)))
            {
                lines.Add(value);
            }
        }
    }

    internal sealed class TraySettings
    {
        internal bool StartAtLogon;
        internal string ScheduleMode = "Off";
        internal string ExternalService = "Notion";
        internal string ScheduleTime = "02:30";
        internal List<string> ScheduleDays = new List<string>(DayValues);
        internal bool RunMissed = true;
        internal string UiLanguage = UiText.Auto;

        internal static readonly string[] DayValues =
        {
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        };

        internal static TraySettings Load(string path)
        {
            TraySettings settings = new TraySettings();
            if (!File.Exists(path))
            {
                return settings;
            }
            try
            {
                JavaScriptSerializer serializer = new JavaScriptSerializer();
                Dictionary<string, object> value = serializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
                settings.StartAtLogon = GetBool(value, "start_at_logon", settings.StartAtLogon);
                settings.ScheduleMode = GetString(value, "schedule_mode", settings.ScheduleMode);
                settings.ExternalService = GetString(value, "external_service", settings.ExternalService);
                settings.ScheduleTime = GetString(value, "schedule_time", settings.ScheduleTime);
                settings.RunMissed = GetBool(value, "run_missed", settings.RunMissed);
                settings.UiLanguage = GetString(value, "ui_language", settings.UiLanguage);
                if (string.Equals(settings.ScheduleMode, "Notion", StringComparison.OrdinalIgnoreCase))
                {
                    settings.ScheduleMode = "External";
                }
                object daysValue;
                if (value.TryGetValue("schedule_days", out daysValue))
                {
                    IEnumerable values = daysValue as IEnumerable;
                    if (values != null && !(daysValue is string))
                    {
                        List<string> days = new List<string>();
                        foreach (object day in values)
                        {
                            string text = Convert.ToString(day);
                            if (DayValues.Contains(text))
                            {
                                days.Add(text);
                            }
                        }
                        if (days.Count > 0)
                        {
                            settings.ScheduleDays = days;
                        }
                    }
                }
                return settings;
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    UiText.Get("The settings file could not be read. Defaults will be used.", "자동 실행 설정 파일을 읽을 수 없어 기본값으로 엽니다.") + "\n\n" + exception.Message,
                    UiText.Get("Log2Topic settings warning", "Log2Topic 설정 경고"),
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
                return settings;
            }
        }

        private static string GetString(Dictionary<string, object> value, string key, string fallback)
        {
            object raw;
            return value.TryGetValue(key, out raw) && raw != null ? Convert.ToString(raw) : fallback;
        }

        private static bool GetBool(Dictionary<string, object> value, string key, bool fallback)
        {
            object raw;
            if (!value.TryGetValue(key, out raw) || raw == null)
            {
                return fallback;
            }
            bool result;
            return bool.TryParse(Convert.ToString(raw), out result) ? result : fallback;
        }
    }

    internal sealed class TrayApplicationContext : ApplicationContext
    {
        private readonly string root;
        private readonly string workspaceRoot;
        private readonly string scriptsRoot;
        private readonly string settingsPath;
        private readonly NotifyIcon notifyIcon;
        private readonly ContextMenuStrip menu;
        private readonly ToolStripMenuItem scheduleSummaryItem;
        private Icon customIcon;
        private System.Windows.Forms.Timer firstRunTimer;
        private System.Windows.Forms.Timer updateTimer;
        private BackgroundWorker settingsWorker;
        private BackgroundWorker updateWorker;
        private bool settingsSaveInProgress;

        internal TrayApplicationContext(string rootPath, bool showSettings = false)
        {
            root = rootPath;
            workspaceRoot = WorkspaceBootstrap.ResolvePath(root);
            scriptsRoot = Path.Combine(root, "scripts");
            settingsPath = Path.Combine(scriptsRoot, ".runtime", "tray_settings.json");
            ValidateRequiredFiles();
            bool firstRun = showSettings || !File.Exists(settingsPath);

            notifyIcon = new NotifyIcon();
            string iconPath = Path.Combine(root, "assets", "log2topic.ico");
            customIcon = File.Exists(iconPath) ? new Icon(iconPath) : null;
            notifyIcon.Icon = customIcon ?? SystemIcons.Application;
            notifyIcon.Text = "Log2Topic";
            notifyIcon.Visible = true;

            menu = new ContextMenuStrip();
                AddMenuItem(UiText.Get("Rebuild after replacing source logs", "원본 일지 교체 후 ID 재생성"), delegate
                {
                    StartBatch("run_local_rebuild.bat", string.Empty, false);
                });
            AddMenuItem(UiText.Get("Update local documents", "로컬 문서 갱신"), delegate
            {
                StartBatch("run_local.bat", string.Empty, false);
                Notify(UiText.Get("Updating local documents.", "로컬 문서 갱신을 시작했습니다."));
            });
            AddMenuItem(UiText.Get("Open classification review", "분류 검토 대시보드 열기"), delegate
            {
                StartBatch("run_classification_review_dashboard.bat", "--nopause", true);
                Notify(UiText.Get("Opening classification review.", "분류 검토 대시보드를 여는 중입니다."));
            });
            menu.Items.Add(new ToolStripSeparator());
            ToolStripMenuItem external = new ToolStripMenuItem(UiText.Get("External services", "외부 서비스"));
            ToolStripMenuItem notion = new ToolStripMenuItem("Notion");
            notion.DropDownItems.Add(CreateMenuItem(UiText.Get("Sync recent logs", "최근 일지 동기화"), delegate
            {
                StartBatch("run_notion_daily_sync.bat", string.Empty, false);
                Notify(UiText.Get("Syncing recent logs to Notion.", "최근 일지 Notion 동기화를 시작했습니다."));
            }));
            notion.DropDownItems.Add(CreateMenuItem(UiText.Get("Full sync", "전체 동기화"), delegate
            {
                StartBatch("run_notion_sync.bat", string.Empty, false);
                Notify(UiText.Get("Starting full Notion sync.", "전체 Notion 동기화를 시작했습니다."));
            }));
            external.DropDownItems.Add(notion);
            menu.Items.Add(external);
            menu.Items.Add(new ToolStripSeparator());
            AddMenuItem(UiText.Get("Open workspace", "작업 폴더 열기"), delegate { OpenFolder(workspaceRoot); });
            AddMenuItem(UiText.Get("Open run logs", "실행 로그 열기"), delegate { OpenFolder(Path.Combine(scriptsRoot, "reports")); });
            menu.Items.Add(new ToolStripSeparator());
            scheduleSummaryItem = new ToolStripMenuItem(ScheduleSummary(TraySettings.Load(settingsPath)));
            scheduleSummaryItem.Enabled = false;
            menu.Items.Add(scheduleSummaryItem);
            AddMenuItem(UiText.Get("Check for updates", "업데이트 확인"), delegate { CheckForUpdates(true); });
            AddMenuItem(UiText.Get("Automation and sync settings...", "자동 실행 및 동기화 설정..."), delegate { ShowSettings(); });
            menu.Items.Add(new ToolStripSeparator());
            AddMenuItem(UiText.Get("Exit", "종료"), delegate { ExitThread(); });

            notifyIcon.ContextMenuStrip = menu;
            notifyIcon.DoubleClick += delegate { OpenFolder(workspaceRoot); };
            updateTimer = new System.Windows.Forms.Timer();
            updateTimer.Interval = 30000;
            updateTimer.Tick += delegate
            {
                updateTimer.Stop();
                updateTimer.Interval = 6 * 60 * 60 * 1000;
                updateTimer.Start();
                CheckForUpdates(false);
            };
            updateTimer.Start();
            Notify(UiText.Get("Log2Topic is available from the system tray.", "트레이에서 실행 기능과 자동 동기화 설정을 사용할 수 있습니다."));

            if (firstRun)
            {
                firstRunTimer = new System.Windows.Forms.Timer();
                firstRunTimer.Interval = 500;
                firstRunTimer.Tick += delegate
                {
                    firstRunTimer.Stop();
                    ShowSettings();
                };
                firstRunTimer.Start();
            }
        }

        private void ValidateRequiredFiles()
        {
            string[] names =
            {
                "run_local.bat", "run_classification_review_dashboard.bat",
                "run_notion_daily_sync.bat", "run_notion_sync.bat", "run_local_rebuild.bat",
                "configure_automation.ps1"
            };
            foreach (string name in names)
            {
                string path = Path.Combine(scriptsRoot, name);
                if (!File.Exists(path))
                {
                    throw new FileNotFoundException(UiText.Get("A required launcher is missing: ", "필수 실행 파일이 없습니다: ") + path, path);
                }
            }
        }

        private ToolStripMenuItem CreateMenuItem(string text, EventHandler handler)
        {
            ToolStripMenuItem item = new ToolStripMenuItem(text);
            item.Click += handler;
            return item;
        }

        private void AddMenuItem(string text, EventHandler handler)
        {
            menu.Items.Add(CreateMenuItem(text, handler));
        }

        private void StartBatch(string filename, string arguments, bool hidden)
        {
            string batchPath = Path.Combine(scriptsRoot, filename);
            string comSpec = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe";
            string command = "/d /c \"\"" + batchPath + "\"";
            if (!string.IsNullOrWhiteSpace(arguments))
            {
                command += " " + arguments;
            }
            command += "\"";
            ProcessStartInfo startInfo = new ProcessStartInfo(comSpec, command);
            startInfo.WorkingDirectory = root;
            startInfo.CreateNoWindow = hidden;
            startInfo.UseShellExecute = !hidden;
            if (hidden)
            {
                startInfo.WindowStyle = ProcessWindowStyle.Hidden;
            }
            Process.Start(startInfo);
        }

        private void OpenFolder(string path)
        {
            Directory.CreateDirectory(path);
            Process.Start(new ProcessStartInfo("explorer.exe", "\"" + path + "\"") { UseShellExecute = true });
        }

        private void CheckForUpdates(bool notifyWhenCurrent)
        {
            if (updateWorker != null && updateWorker.IsBusy)
            {
                return;
            }

            updateWorker = new BackgroundWorker();
            updateWorker.DoWork += delegate(object sender, DoWorkEventArgs eventArgs)
            {
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
                using (WebClient client = new WebClient())
                {
                    client.Headers[HttpRequestHeader.UserAgent] = "Log2Topic-Updater";
                    string json = client.DownloadString("https://api.github.com/repos/Rubidius37/Log2Topic/releases/latest");
                    Dictionary<string, object> release = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(json);
                    string tagName = Convert.ToString(release["tag_name"]);
                    Version latestVersion;
                    if (!Version.TryParse(tagName.TrimStart('v', 'V'), out latestVersion) ||
                        latestVersion.CompareTo(typeof(Program).Assembly.GetName().Version) <= 0)
                    {
                        eventArgs.Result = notifyWhenCurrent ? "current" : null;
                        return;
                    }

                    Dictionary<string, object> updateAsset = null;
                    foreach (object rawAsset in (object[])release["assets"])
                    {
                        Dictionary<string, object> asset = rawAsset as Dictionary<string, object>;
                        if (asset != null && string.Equals(Convert.ToString(asset["name"]), "Log2Topic-windows.zip", StringComparison.OrdinalIgnoreCase))
                        {
                            updateAsset = asset;
                            break;
                        }
                    }
                    if (updateAsset == null)
                    {
                        eventArgs.Result = null;
                        return;
                    }

                    string digest = updateAsset.ContainsKey("digest") ? Convert.ToString(updateAsset["digest"]) : string.Empty;
                    if (digest.StartsWith("sha256:", StringComparison.OrdinalIgnoreCase))
                    {
                        digest = digest.Substring(7);
                    }
                    eventArgs.Result = new UpdateInfo
                    {
                        AssetUrl = Convert.ToString(updateAsset["browser_download_url"]),
                        ExpectedSha256 = digest
                    };
                }
            };
            updateWorker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs eventArgs)
            {
                updateWorker.Dispose();
                updateWorker = null;
                if (eventArgs.Error != null)
                {
                    if (notifyWhenCurrent)
                    {
                        Notify(UiText.Get("Update check failed.", "업데이트 확인에 실패했습니다."));
                    }
                    return;
                }
                if (string.Equals(eventArgs.Result as string, "current", StringComparison.Ordinal))
                {
                    Notify(UiText.Get("Log2Topic is up to date.", "Log2Topic은 최신 버전입니다."));
                    return;
                }
                UpdateInfo update = eventArgs.Result as UpdateInfo;
                if (update == null)
                {
                    return;
                }
                Notify(UiText.Get("A new version is installing.", "새 버전을 설치합니다."));
                StartUpdater(update.AssetUrl, update.ExpectedSha256);
                ExitThread();
            };
            updateWorker.RunWorkerAsync();
        }

        private void StartUpdater(string assetUrl, string expectedSha256)
        {
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
            string updater = Path.Combine(scriptsRoot, "update_windows_app.ps1");
            string arguments = "-NoProfile -ExecutionPolicy Bypass -File " + Quote(updater) +
                " -InstallRoot " + Quote(root) + " -AssetUrl " + Quote(assetUrl) +
                " -ExpectedSha256 " + Quote(expectedSha256) + " -CurrentProcessId " + Process.GetCurrentProcess().Id;
            Process.Start(new ProcessStartInfo(powershell, arguments)
            {
                WorkingDirectory = root,
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden
            });
        }

        private sealed class UpdateInfo
        {
            internal string AssetUrl;
            internal string ExpectedSha256;
        }

        private void ShowSettings()
        {
            if (settingsSaveInProgress)
            {
                Notify(UiText.Get("Automation settings are being saved.", "자동 실행 설정을 저장하고 있습니다."));
                return;
            }
            using (SettingsForm form = new SettingsForm(TraySettings.Load(settingsPath), SaveSettingsAsync))
            {
                form.ShowDialog();
            }
        }

        private void SaveSettingsAsync(TraySettings settings)
        {
            settingsSaveInProgress = true;
            scheduleSummaryItem.Text = UiText.Get("Automatic update: saving...", "자동 동기화: 설정 저장 중...");
            Notify(UiText.Get("Saving automation settings.", "자동 실행 설정을 저장하는 중입니다."));

            settingsWorker = new BackgroundWorker();
            settingsWorker.DoWork += delegate { ApplySettings(settings); };
            settingsWorker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs eventArgs)
            {
                settingsSaveInProgress = false;
                settingsWorker.Dispose();
                settingsWorker = null;
                scheduleSummaryItem.Text = ScheduleSummary(TraySettings.Load(settingsPath));
                if (eventArgs.Error != null)
                {
                    MessageBox.Show(
                        UiText.Get("Settings could not be saved.", "설정을 저장하지 못했습니다.") + "\n\n" + eventArgs.Error.Message,
                        UiText.Get("Log2Topic settings error", "Log2Topic 설정 오류"),
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    return;
                }
                Notify(UiText.Get("Settings saved. Restart Log2Topic to apply a language change.", "설정을 저장했습니다. 언어 변경은 Log2Topic을 다시 실행하면 적용됩니다."));
            };
            try
            {
                settingsWorker.RunWorkerAsync();
            }
            catch
            {
                settingsSaveInProgress = false;
                scheduleSummaryItem.Text = ScheduleSummary(TraySettings.Load(settingsPath));
                settingsWorker.Dispose();
                settingsWorker = null;
                throw;
            }
        }

        private void ApplySettings(TraySettings settings)
        {
            string powershell = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                "WindowsPowerShell", "v1.0", "powershell.exe");
            string script = Path.Combine(scriptsRoot, "configure_automation.ps1");
            StringBuilder arguments = new StringBuilder();
            arguments.Append("-NoProfile -ExecutionPolicy Bypass -File ").Append(Quote(script));
            arguments.Append(" -Mode ").Append(settings.ScheduleMode);
            arguments.Append(" -Service ").Append(settings.ExternalService);
            arguments.Append(" -Time ").Append(settings.ScheduleTime);
            arguments.Append(" -DaysCsv ").Append(Quote(string.Join(",", settings.ScheduleDays.ToArray())));
            arguments.Append(" -Language ").Append(settings.UiLanguage);
            if (settings.StartAtLogon)
            {
                arguments.Append(" -EnableStartup");
            }
            if (settings.RunMissed)
            {
                arguments.Append(" -RunMissed");
            }

            ProcessStartInfo startInfo = new ProcessStartInfo(powershell, arguments.ToString());
            startInfo.WorkingDirectory = root;
            startInfo.UseShellExecute = false;
            startInfo.CreateNoWindow = true;
            startInfo.RedirectStandardOutput = true;
            startInfo.RedirectStandardError = true;
            using (Process process = Process.Start(startInfo))
            {
                string output = process.StandardOutput.ReadToEnd();
                string error = process.StandardError.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    throw new InvalidOperationException(
                        UiText.Get("The automation settings script failed.", "자동 실행 설정 스크립트가 실패했습니다.") + "\n\n" + (string.IsNullOrWhiteSpace(error) ? output : error));
                }
            }
        }

        private static string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private static string ScheduleSummary(TraySettings settings)
        {
            if (string.Equals(settings.ScheduleMode, "Local", StringComparison.OrdinalIgnoreCase))
            {
                return UiText.Get("Automatic update: local ", "자동 동기화: 로컬 갱신 ") + settings.ScheduleTime;
            }
            if (string.Equals(settings.ScheduleMode, "External", StringComparison.OrdinalIgnoreCase))
            {
                return UiText.Get("Automatic update: external service (", "자동 동기화: 외부 서비스 (") + settings.ExternalService + ") " + settings.ScheduleTime;
            }
            return UiText.Get("Automatic update: off", "자동 동기화: 사용 안 함");
        }

        private void Notify(string message)
        {
            notifyIcon.BalloonTipTitle = "Log2Topic";
            notifyIcon.BalloonTipText = message;
            notifyIcon.BalloonTipIcon = ToolTipIcon.Info;
            notifyIcon.ShowBalloonTip(3500);
        }

        protected override void ExitThreadCore()
        {
            if (firstRunTimer != null)
            {
                firstRunTimer.Dispose();
                firstRunTimer = null;
            }
            notifyIcon.Visible = false;
            notifyIcon.Dispose();
            menu.Dispose();
            if (customIcon != null)
            {
                customIcon.Dispose();
                customIcon = null;
            }
            base.ExitThreadCore();
        }
    }

    internal sealed class SettingsForm : Form
    {
        private readonly CheckBox startupCheck;
        private readonly ComboBox modeCombo;
        private readonly ComboBox serviceCombo;
        private readonly DateTimePicker timePicker;
        private readonly CheckedListBox daysList;
        private readonly CheckBox missedCheck;
        private readonly ComboBox languageCombo;
        private readonly Action<TraySettings> saveAction;

        internal SettingsForm(TraySettings settings, Action<TraySettings> onSave)
        {
            saveAction = onSave;
            Text = UiText.Get("Log2Topic settings", "Log2Topic 설정");
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(420, 450);
            Font = new Font("Segoe UI", 9F);

            AddLabel(UiText.Get(
                "Configure tray startup and scheduled updates.\nChoose an external service only after connecting it.",
                "트레이 자동 실행과 정기 갱신 시간을 설정합니다.\n외부 서비스는 연동 설정을 마친 경우에만 선택하세요."), 20, 18, 380, 42);
            startupCheck = new CheckBox
            {
                Location = new Point(20, 70), Size = new Size(350, 24),
                Text = UiText.Get("Start Log2Topic when Windows signs in", "Windows 로그인 시 Log2Topic 자동 실행"), Checked = settings.StartAtLogon
            };
            Controls.Add(startupCheck);

            AddLabel(UiText.Get("Automatic task", "자동 작업"), 20, 112, 110, 22);
            modeCombo = CreateCombo(135, 108, 245);
            modeCombo.Items.AddRange(new object[] {
                UiText.Get("Off", "사용 안 함"),
                UiText.Get("Update local documents", "로컬 문서 갱신"),
                UiText.Get("Update locally, then sync external service", "로컬 갱신 후 외부 서비스 동기화")
            });
            modeCombo.SelectedIndex = string.Equals(settings.ScheduleMode, "Local", StringComparison.OrdinalIgnoreCase) ? 1 :
                string.Equals(settings.ScheduleMode, "External", StringComparison.OrdinalIgnoreCase) ? 2 : 0;

            AddLabel(UiText.Get("External service", "외부 서비스"), 20, 153, 110, 22);
            serviceCombo = CreateCombo(135, 149, 245);
            serviceCombo.Items.Add("Notion");
            serviceCombo.SelectedIndex = 0;

            AddLabel(UiText.Get("Run time", "실행 시간"), 20, 194, 110, 22);
            timePicker = new DateTimePicker
            {
                Location = new Point(135, 190), Size = new Size(100, 24),
                Format = DateTimePickerFormat.Custom, CustomFormat = "HH:mm", ShowUpDown = true
            };
            DateTime parsed;
            timePicker.Value = DateTime.TryParseExact(
                settings.ScheduleTime, "HH:mm", System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.None, out parsed)
                ? DateTime.Today.Add(parsed.TimeOfDay)
                : DateTime.Today.AddHours(2).AddMinutes(30);
            Controls.Add(timePicker);

            AddLabel(UiText.Get("Run days", "실행 요일"), 20, 235, 110, 22);
            daysList = new CheckedListBox
            {
                Location = new Point(135, 231), Size = new Size(245, 60),
                MultiColumn = true, ColumnWidth = 48, CheckOnClick = true
            };
            string[] dayLabels = UiText.Get("Mon,Tue,Wed,Thu,Fri,Sat,Sun", "월,화,수,목,금,토,일").Split(',');
            for (int index = 0; index < dayLabels.Length; index++)
            {
                daysList.Items.Add(dayLabels[index], settings.ScheduleDays.Contains(TraySettings.DayValues[index]));
            }
            Controls.Add(daysList);

            missedCheck = new CheckBox
            {
                Location = new Point(20, 311), Size = new Size(360, 24),
                Text = UiText.Get("Run later if the PC was off at the scheduled time", "예약 시간에 PC가 꺼져 있었다면 다음 기회에 실행"), Checked = settings.RunMissed
            };
            Controls.Add(missedCheck);

            AddLabel(UiText.Get("Language", "언어"), 20, 350, 110, 22);
            languageCombo = CreateCombo(135, 346, 245);
            languageCombo.Items.AddRange(new object[] {
                UiText.Get("System default (applies after restart)", "시스템 기본값 (다시 실행 후 적용)"),
                "English", "한국어"
            });
            languageCombo.SelectedIndex = string.Equals(settings.UiLanguage, UiText.English, StringComparison.OrdinalIgnoreCase) ? 1 :
                string.Equals(settings.UiLanguage, UiText.Korean, StringComparison.OrdinalIgnoreCase) ? 2 : 0;

            Button saveButton = new Button { Location = new Point(224, 400), Size = new Size(76, 30), Text = UiText.Get("Save", "저장") };
            Button cancelButton = new Button
            {
                Location = new Point(308, 400), Size = new Size(76, 30), Text = UiText.Get("Cancel", "취소"), DialogResult = DialogResult.Cancel
            };
            saveButton.Click += SaveClicked;
            Controls.Add(saveButton);
            Controls.Add(cancelButton);
            AcceptButton = saveButton;
            CancelButton = cancelButton;
            modeCombo.SelectedIndexChanged += delegate { UpdateEnabledState(); };
            UpdateEnabledState();
        }

        private void SaveClicked(object sender, EventArgs eventArgs)
        {
            TraySettings settings = new TraySettings();
            settings.StartAtLogon = startupCheck.Checked;
            settings.ScheduleMode = modeCombo.SelectedIndex == 1 ? "Local" : modeCombo.SelectedIndex == 2 ? "External" : "Off";
            settings.ExternalService = "Notion";
            settings.UiLanguage = languageCombo.SelectedIndex == 1 ? UiText.English : languageCombo.SelectedIndex == 2 ? UiText.Korean : UiText.Auto;
            settings.ScheduleTime = timePicker.Value.ToString("HH:mm");
            settings.ScheduleDays.Clear();
            for (int index = 0; index < TraySettings.DayValues.Length; index++)
            {
                if (daysList.GetItemChecked(index))
                {
                    settings.ScheduleDays.Add(TraySettings.DayValues[index]);
                }
            }
            if (!string.Equals(settings.ScheduleMode, "Off", StringComparison.OrdinalIgnoreCase) && settings.ScheduleDays.Count == 0)
            {
                MessageBox.Show(
                    UiText.Get("Select at least one run day for an automatic task.", "자동 작업을 사용할 때는 실행 요일을 하나 이상 선택하세요."),
                    UiText.Get("Log2Topic settings", "Log2Topic 설정"), MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            if (settings.ScheduleDays.Count == 0)
            {
                settings.ScheduleDays.AddRange(TraySettings.DayValues);
            }
            settings.RunMissed = missedCheck.Checked;
            try
            {
                saveAction(settings);
                DialogResult = DialogResult.OK;
                Close();
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    UiText.Get("Settings could not be saved.", "설정을 저장하지 못했습니다.") + "\n\n" + exception.Message,
                    UiText.Get("Log2Topic settings error", "Log2Topic 설정 오류"), MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void UpdateEnabledState()
        {
            bool enabled = modeCombo.SelectedIndex != 0;
            serviceCombo.Enabled = modeCombo.SelectedIndex == 2;
            timePicker.Enabled = enabled;
            daysList.Enabled = enabled;
            missedCheck.Enabled = enabled;
        }

        private void AddLabel(string text, int x, int y, int width, int height)
        {
            Controls.Add(new Label { Text = text, Location = new Point(x, y), Size = new Size(width, height) });
        }

        private ComboBox CreateCombo(int x, int y, int width)
        {
            ComboBox combo = new ComboBox
            {
                Location = new Point(x, y), Size = new Size(width, 24), DropDownStyle = ComboBoxStyle.DropDownList
            };
            Controls.Add(combo);
            return combo;
        }
    }

    internal static class NativeMethods
    {
        [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        internal static extern int SetCurrentProcessExplicitAppUserModelID(string appID);
    }
}
