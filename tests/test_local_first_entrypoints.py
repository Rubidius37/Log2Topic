import os
import re
import subprocess
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read_repo_file(*parts):
    with open(os.path.join(ROOT_DIR, *parts), "r", encoding="utf-8") as file_obj:
        return file_obj.read()


class LocalFirstEntrypointTests(unittest.TestCase):
    def test_classification_rules_follow_repository_ownership(self):
        if not os.path.isdir(os.path.join(ROOT_DIR, ".git")) or not os.path.exists(os.path.join(ROOT_DIR, ".gitignore")):
            self.skipTest("Requires a Git repository checkout.")
        ignore_lines = {
            line.strip() for line in read_repo_file(".gitignore").splitlines()
        }
        is_distribution = os.path.exists(os.path.join(ROOT_DIR, "setup_workspace.bat"))

        if is_distribution:
            tracked = subprocess.check_output(
                ["git", "ls-files", "Workspace/Classification_Rules.md"],
                cwd=ROOT_DIR,
                text=True,
                encoding="utf-8",
            ).strip()
            self.assertEqual("Workspace/Classification_Rules.md", tracked)
            self.assertNotIn("/Workspace/Classification_Rules.md", ignore_lines)
        else:
            self.assertIn("Classification_Rules.md", ignore_lines)

    def test_private_workspace_markers_are_absent_from_project_sources(self):
        private_markers = ("Research_" + "Notes", "C:" + "\\Users\\" + "HP")
        excluded_dirs = {
            ".git",
            "__pycache__",
            "Workspace",
            "source_id_backups",
        }
        text_suffixes = {".bat", ".cs", ".css", ".html", ".js", ".json", ".md", ".ps1", ".py", ".sh"}

        matches = []
        for current_root, dirnames, filenames in os.walk(ROOT_DIR):
            dirnames[:] = [name for name in dirnames if name not in excluded_dirs]
            for filename in filenames:
                if os.path.splitext(filename)[1].casefold() not in text_suffixes:
                    continue
                path = os.path.join(current_root, filename)
                with open(path, "r", encoding="utf-8") as file_obj:
                    content = file_obj.read().casefold()
                    if any(marker.casefold() in content for marker in private_markers):
                        matches.append(os.path.relpath(path, ROOT_DIR))

        self.assertEqual([], matches)

    def test_local_launcher_has_no_notion_dependency(self):
        content = read_repo_file("scripts", "run_local.bat").casefold()

        self.assertIn("hierarchical_classifier.py", content)
        self.assertIn("resolve_python.bat", content)
        self.assertNotIn("sync_to_notion.py", content)
        self.assertNotIn("notion_token", content)
        self.assertNotIn(".env", content)

    def test_optional_notion_launchers_are_explicit(self):
        full_sync = read_repo_file("scripts", "run_notion_sync.bat").casefold()
        daily_sync = read_repo_file("scripts", "run_notion_daily_sync.bat").casefold()
        sync_script = read_repo_file("scripts", "sync_to_notion.py").casefold()

        self.assertIn("hierarchical_classifier.py", full_sync)
        self.assertIn("sync_to_notion.py", full_sync)
        self.assertIn("--daily-only", daily_sync)
        self.assertIn("sync_args", daily_sync)
        self.assertNotIn("ngrok", sync_script)
        self.assertNotIn("subprocess.popen", sync_script)

    def test_review_dashboard_is_an_internal_tray_launcher(self):
        content = read_repo_file(
            "scripts", "run_classification_review_dashboard.bat"
        ).casefold()

        self.assertIn("classification_review_dashboard.py", content)
        self.assertIn("classification_review_dashboard.log", content)
        self.assertIn("--nopause", content)
        self.assertFalse(
            os.path.exists(
                os.path.join(ROOT_DIR, "run_classification_review_dashboard.bat")
            )
        )

    def test_tray_uses_one_configurable_scheduled_task(self):
        configuration = read_repo_file("scripts", "configure_automation.ps1")
        tray = read_repo_file("scripts", "log2topic_tray.ps1")

        for task_name in (
            "Log2Topic_Local_Update",
            "Log2Topic_Notion_Sync",
            "ResearchNotes_Local_Update",
            "ResearchNotes_Notion_Sync",
        ):
            self.assertIn(task_name, configuration)
        self.assertIn("Log2Topic_Scheduled_Update", configuration)
        self.assertIn('"External"', configuration)
        self.assertIn('external_service = $Service', configuration)
        self.assertIn('ui_language = $Language', configuration)
        self.assertIn('"run_local.bat"', configuration)
        self.assertIn('"run_notion_sync.bat"', configuration)
        self.assertIn("자동 실행 및 동기화 설정", tray)
        self.assertIn('$contextMenu.Items.Add("외부 서비스")', tray)
        self.assertIn('$externalServicesItem.DropDownItems.Add("Notion")', tray)
        self.assertIn('run_classification_review_dashboard.bat" -Arguments "--nopause" -Hidden', tray)

    def test_log2topic_is_the_only_end_user_root_launcher(self):
        launcher = read_repo_file("Log2Topic.bat").casefold()

        self.assertIn("log2topic.exe", launcher)
        self.assertIn("log2topic_tray.ps1", launcher)
        self.assertIn("-windowstyle hidden", launcher)
        for filename in (
            "run_local.bat",
            "run_classification_review_dashboard.bat",
            "run_notion_daily_sync.bat",
            "run_notion_sync.bat",
            "run_classify_hierarchical_preview.bat",
        ):
            self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, filename)))
            if filename != "run_classify_hierarchical_preview.bat":
                self.assertTrue(os.path.exists(os.path.join(ROOT_DIR, "scripts", filename)))

    def test_tray_uses_the_project_icon(self):
        tray = read_repo_file("scripts", "log2topic_tray.ps1")
        automation = read_repo_file("scripts", "configure_automation.ps1")
        icon_path = os.path.join(ROOT_DIR, "assets", "log2topic.ico")
        png_path = os.path.join(ROOT_DIR, "assets", "log2topic.png")

        self.assertIn("assets\\log2topic.ico", tray)
        self.assertIn("assets\\log2topic.ico", automation)
        self.assertTrue(os.path.exists(icon_path))
        self.assertTrue(os.path.exists(png_path))
        executable_path = os.path.join(ROOT_DIR, "Log2Topic.exe")
        self.assertTrue(os.path.exists(executable_path))
        with open(executable_path, "rb") as executable_file:
            self.assertEqual(b"MZ", executable_file.read(2))
        with open(icon_path, "rb") as icon_file:
            self.assertEqual(b"\x00\x00\x01\x00", icon_file.read(4))
        with open(png_path, "rb") as png_file:
            self.assertEqual(b"\x89PNG\r\n\x1a\n", png_file.read(8))

    def test_windows_app_source_and_rebuild_script_are_distributed(self):
        app_source = read_repo_file("app", "Log2Topic.cs")
        build_script = read_repo_file("scripts", "build_windows_app.ps1")

        self.assertIn("namespace Log2TopicDesktop", app_source)
        self.assertIn("WorkspaceBootstrap.Ensure(root)", app_source)
        self.assertIn('Path.Combine(root, "Workspace")', app_source)
        self.assertIn('Path.Combine(workspaceRoot, "Daily_Logs")', app_source)
        self.assertIn('Path.Combine(workspaceRoot, "attachments")', app_source)
        self.assertIn('arguments.Append(" -Language ")', app_source)
        self.assertIn('Join-Path $root "app\\Log2Topic.cs"', build_script)
        self.assertIn("Get-FileHash", build_script)
        self.assertIn("$archiveSha256", build_script)

    def test_public_test_suite_is_complete(self):
        public_tests = (
            "test_atomic_state.py",
            "test_classification_review_dashboard.py",
            "test_cloudinary_lifecycle.py",
            "test_hierarchical_classifier.py",
            "test_local_first_entrypoints.py",
            "test_notion_retry_safety.py",
            "test_process_lock.py",
            "test_sync_parallel_roots.py",
        )

        for filename in public_tests:
            self.assertTrue(os.path.exists(os.path.join(ROOT_DIR, "tests", filename)), filename)

    def test_distribution_workspace_setup_remains_supported(self):
        setup_path = os.path.join(ROOT_DIR, "setup_workspace.bat")
        if not os.path.exists(setup_path):
            self.skipTest("Private source workspace does not use distribution setup.")

        setup = read_repo_file("setup_workspace.bat")
        self.assertIn("Workspace\\Classification_Rules.md", setup)
        self.assertNotIn("Classification_Rules.example.md", setup)
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "Workspace", "Classification_Rules.md"))
        )
        self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, "Classification_Rules.example.md")))

    def test_obsolete_root_launchers_are_removed(self):
        for filename in (
            "run_classify_only.bat",
            "run_classify_and_sync_to_notion.bat",
            "run_sync_daily_only_to_notion.bat",
            "run_classify_hierarchical_preview.bat",
        ):
            self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, filename)))

    def test_external_ai_classification_audit_is_removed(self):
        audit_stem = "ai_classification" + "_audit"
        retired_files = (
            f"{audit_stem}.py",
            f"run_{audit_stem}.bat",
            "register_ai_" + "audit_scheduler.ps1",
        )
        for filename in retired_files:
            self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, "scripts", filename)))

        env_example = read_repo_file("scripts", ".env.example").casefold()
        project_docs = (
            read_repo_file("README.md")
            + read_repo_file("docs", "USER_GUIDE.md")
            + read_repo_file("docs", "SYSTEM_REFERENCE.md")
        ).casefold()
        self.assertNotIn("gem" + "ini_api_key", env_example)
        self.assertNotIn("ai_" + "audit_", env_example)
        self.assertNotIn(audit_stem, project_docs)

    def test_zip_distribution_builder_is_retired(self):
        self.assertFalse(
            os.path.exists(
                os.path.join(ROOT_DIR, "scripts", "make_portable_distribution_zip.bat")
            )
        )
        docs = (
            read_repo_file("README.md")
            + read_repo_file("docs", "USER_GUIDE.md")
            + read_repo_file("docs", "SYSTEM_REFERENCE.md")
        ).casefold()
        self.assertNotIn("portable " + "zip", docs)

    def test_readme_uses_local_launcher_as_default(self):
        en_content = read_repo_file("README.md")
        ko_content = read_repo_file("README.ko.md")

        self.assertIn("# Log2Topic", en_content)
        self.assertIn("## Quick Start", en_content)
        self.assertIn("[한국어](README.ko.md)", en_content)
        self.assertIn("assets/readme-demo.gif", en_content)
        self.assertIn("Log2Topic.exe", en_content)

        self.assertIn("# Log2Topic", ko_content)
        self.assertIn("[English](README.md)", ko_content)
        self.assertIn("## 처음 시작하기", ko_content)
        self.assertIn("Markdown 기록 도구", ko_content)
        self.assertIn("## 선택 사항: 외부 서비스", ko_content)
        self.assertIn("Log2Topic.exe", ko_content)
        self.assertIn("로컬 문서 갱신", ko_content)
        self.assertIn("assets/log2topic.png", ko_content)
        self.assertIn("assets/readme-demo-ko.gif", ko_content)
        self.assertIn("Workspace/", ko_content)
        self.assertIn("assets/log2topic-tray-menu-ko.png", ko_content)
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "assets", "log2topic-tray-menu-ko.png"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "assets", "readme-demo.gif"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "assets", "readme-demo-ko.gif"))
        )
        self.assertIn("### Notion", ko_content)
        self.assertIn("docs/SYSTEM_REFERENCE.md", ko_content)
        self.assertIn("docs/NOTION_INTEGRATION.md", ko_content)
        self.assertNotIn("run_classify_only.bat", ko_content)
        self.assertNotIn("## Git으로 배포하고 업데이트하기", ko_content)
        self.assertNotIn("git clone <저장소 URL>", ko_content)
        self.assertNotIn("git pull --ff-only", ko_content)

    def test_feedback_channel_and_issue_templates_are_distributed(self):
        readme = read_repo_file("README.ko.md")
        en_readme = read_repo_file("README.md")
        self.assertIn("## Feedback & Issues", en_readme)
        self.assertIn("## 피드백과 문제 제보", readme)
        self.assertIn("GitHub `Issues`", readme)
        self.assertIn("연구자료와 인증정보", readme)
        if not os.path.isdir(os.path.join(ROOT_DIR, ".github", "ISSUE_TEMPLATE")):
            self.skipTest("Issue templates are only present in the Git repository.")
        bug_template = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "01-bug.yml"
        )
        feature_template = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "02-feature-request.yml"
        )
        chooser = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "config.yml"
        )
        self.assertIn("name: 버그 제보", bug_template)
        self.assertIn("id: steps", bug_template)
        self.assertIn("name: 기능 제안", feature_template)
        self.assertIn("id: proposal", feature_template)
        self.assertIn("blank_issues_enabled: false", chooser)

    def test_notion_database_id_uses_single_setting_name(self):
        legacy_name = "DESTINATION_" + "DATABASE_ID"
        files = (
            read_repo_file("scripts", "sync_to_notion.py")
            + read_repo_file("scripts", ".env.example")
            + read_repo_file("docs", "NOTION_INTEGRATION.md")
        )

        self.assertIn("NOTION_DATABASE_ID", files)
        self.assertNotIn(legacy_name, files)

    def test_bundled_python_is_the_primary_runtime(self):
        if not os.path.exists(os.path.join(ROOT_DIR, "runtime", "PYTHON_RUNTIME.md")):
            self.skipTest("Bundled Windows Python runtime is not present in this distribution.")
        resolver = read_repo_file("scripts", "resolve_python.bat").casefold()
        runtime_reference = read_repo_file("runtime", "PYTHON_RUNTIME.md")
        automation = read_repo_file("scripts", "configure_automation.ps1")

        self.assertLess(resolver.index("bundled_python"), resolver.index("python -c"))
        self.assertIn("runtime\\python\\python.exe", resolver)
        self.assertIn("python-3.13.15-embed-amd64.zip", runtime_reference)
        self.assertIn('Join-Path $vaultRoot "Log2Topic.exe"', automation)
        self.assertIn("[string]$DaysCsv", automation)
        if os.path.exists(os.path.join(ROOT_DIR, "runtime", "python-3.13.15-embed-amd64.zip")):
            self.assertTrue(
                os.path.exists(
                    os.path.join(ROOT_DIR, "runtime", "python-3.13.15-embed-amd64.zip")
                )
            )

    @unittest.skipUnless(os.name == "nt", "Automation configuration is Windows-only.")
    def test_automation_accepts_exe_and_legacy_day_arguments(self):
        powershell = os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        script = os.path.join(ROOT_DIR, "scripts", "configure_automation.ps1")
        common = [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            script,
            "-Mode",
            "Local",
            "-Time",
            "02:30",
            "-ValidateOnly",
        ]

        for day_arguments in (
            ["-DaysCsv", "Monday,Tuesday,Wednesday"],
            ["-Days", "Monday"],
        ):
            result = subprocess.run(
                common + day_arguments,
                cwd=ROOT_DIR,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_linux_posix_launchers_and_automation_configurator_exist(self):
        import sys
        import tempfile

        scripts_dir = os.path.join(ROOT_DIR, "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import configure_automation

        for root_script in ("Log2Topic.sh", "setup_workspace.sh"):
            path = os.path.join(ROOT_DIR, root_script)
            self.assertTrue(os.path.exists(path), root_script)
            with open(path, "rb") as file_obj:
                raw = file_obj.read()
            self.assertTrue(raw.startswith(b"#!/usr/bin/env sh\n"), root_script)
            self.assertNotIn(b"\r\n", raw, root_script)

        for script_name in (
            "resolve_python.sh",
            "run_local.sh",
            "run_local_rebuild.sh",
            "run_classification_review_dashboard.sh",
            "run_notion_daily_sync.sh",
            "run_notion_sync.sh",
            "run_cloudinary_cleanup.sh",
        ):
            path = os.path.join(ROOT_DIR, "scripts", script_name)
            self.assertTrue(os.path.exists(path), script_name)
            with open(path, "rb") as file_obj:
                raw = file_obj.read()
            self.assertTrue(raw.startswith(b"#!/usr/bin/env sh\n"), script_name)
            self.assertNotIn(b"\r\n", raw, script_name)

        local_sh = read_repo_file("scripts", "run_local.sh").casefold()
        self.assertIn("hierarchical_classifier.py", local_sh)
        self.assertIn("resolve_python.sh", local_sh)
        self.assertNotIn("sync_to_notion.py", local_sh)

        self.assertEqual(
            configure_automation.main(
                ["--mode", "Local", "--time", "02:30", "--days-csv", "Monday,Wednesday", "--validate-only"]
            ),
            0,
        )
        service_text, timer_text = configure_automation.build_systemd_units(
            "/opt/Log2Topic",
            "External",
            "Notion",
            "03:15",
            ["Monday", "Friday"],
            True,
        )
        self.assertIn('ExecStart=/bin/sh "/opt/Log2Topic/scripts/run_notion_sync.sh" --nopause', service_text)
        self.assertIn("OnCalendar=Mon,Fri *-*-* 03:15:00", timer_text)
        self.assertIn("Persistent=true", timer_text)
        orig_service, _orig_timer = configure_automation.build_systemd_units(
            "/opt/Log2Topic",
            "ExternalOriginals",
            "Notion",
            "04:00",
            ["Tuesday"],
            False,
        )
        self.assertIn(
            'ExecStart=/bin/sh "/opt/Log2Topic/scripts/run_notion_daily_sync.sh" --all-daily --nopause',
            orig_service,
        )
        cron_line = configure_automation.build_cron_line(
            "/opt/Log2Topic", "Local", "Notion", "02:30", ["Monday", "Sunday"]
        )
        self.assertIn("30 2 * * 1,0", cron_line)
        self.assertIn("run_local.sh", cron_line)

        with tempfile.TemporaryDirectory() as temp_dir:
            desktop_path = configure_automation.apply_linux_autostart(
                "/opt/Log2Topic", True, autostart_dir=temp_dir
            )
            self.assertTrue(os.path.isfile(desktop_path))
            configure_automation.apply_linux_autostart(
                "/opt/Log2Topic", False, autostart_dir=temp_dir
            )
            self.assertFalse(os.path.exists(desktop_path))

        from unittest.mock import patch

        with patch.object(configure_automation.shutil, "which", return_value="/usr/bin/crontab"), patch.object(
            configure_automation.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["crontab", "-l"], 1, stdout="", stderr="permission denied"),
        ) as run_mock:
            self.assertFalse(configure_automation._update_crontab("0 2 * * * cmd"))
            self.assertEqual(run_mock.call_count, 1)

    def test_cross_platform_gui_and_tray_helpers(self):
        import tempfile
        import log2topic_gui

        self.assertTrue(log2topic_gui.detect_is_korean({"ui_language": "ko"}))
        self.assertFalse(log2topic_gui.detect_is_korean({"ui_language": "en"}))
        self.assertIn(
            "3 item(s)",
            log2topic_gui.format_local_update_notification(0, 3, is_korean=False),
        )
        self.assertIn(
            "검토 필요 3건",
            log2topic_gui.format_local_update_notification(0, 3, is_korean=True),
        )
        self.assertIn(
            "failed",
            log2topic_gui.format_local_update_notification(1, 0, is_korean=False),
        )
        cfg_args = log2topic_gui.build_configure_args(
            {
                "schedule_mode": "ExternalOriginals",
                "external_service": "Notion",
                "schedule_time": "03:15",
                "schedule_days": ["MON", "FRI"],
                "ui_language": "ko",
                "prune_backups": True,
                "backup_retention_count": 50,
                "start_at_logon": True,
                "run_missed": True,
                "auto_check_updates": False,
            }
        )
        self.assertIn("ExternalOriginals", cfg_args)
        self.assertIn("--prune-backups", cfg_args)
        self.assertIn("--enable-startup", cfg_args)
        self.assertIn("--disable-auto-update-check", cfg_args)
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(log2topic_gui.read_needs_review_count(temp_dir), 0)
            with open(os.path.join(temp_dir, "organizer_metadata.json"), "w", encoding="utf-8") as fobj:
                fobj.write('{"stats": {"needs_review": 4}}')
            self.assertEqual(log2topic_gui.read_needs_review_count(temp_dir), 4)

    def test_tracked_files_exclude_runtime_artifacts_and_logs(self):
        if not os.path.isdir(os.path.join(ROOT_DIR, ".git")):
            self.skipTest("Requires a Git repository checkout.")
        tracked = subprocess.check_output(
            ["git", "ls-files"],
            cwd=ROOT_DIR,
            text=True,
            encoding="utf-8",
        ).splitlines()
        bad = [
            path
            for path in tracked
            if "__pycache__/" in path
            or path.endswith((".pyc", ".pyo", ".log"))
            or path.startswith("runtime/python/")
            or "/.runtime/" in path
            or path.startswith("scripts/.runtime/")
        ]
        self.assertEqual(bad, [])

    def test_detailed_reference_documents_exist(self):
        user_guide = read_repo_file("docs", "USER_GUIDE.md")
        system_reference = read_repo_file("docs", "SYSTEM_REFERENCE.md")
        notion_reference = read_repo_file("docs", "NOTION_INTEGRATION.md")

        self.assertIn("## Markdown 편집기 설정", user_guide)
        self.assertIn("## 문제 해결", user_guide)
        self.assertIn("## Source ID", system_reference)
        self.assertIn("## 동시 실행 잠금", system_reference)
        self.assertIn("## Sync Key와 페이지 갱신", notion_reference)
        self.assertIn("## 재시도와 부분 실패", notion_reference)

    def test_korean_documents_and_relative_links(self):
        documents = (
            "README.md",
            "README.ko.md",
            "docs/USER_GUIDE.md",
            "docs/NOTION_INTEGRATION.md",
            "docs/SYSTEM_REFERENCE.md",
            "Workspace/Classification_Rules.md",
            "runtime/PYTHON_RUNTIME.md",
        )
        for removed_document in (
            "docs/USER_GUIDE.ko.md",
            "docs/NOTION_INTEGRATION.ko.md",
            "docs/SYSTEM_REFERENCE.ko.md",
        ):
            self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, removed_document)))

        for relative_document in documents:
            document_path = os.path.join(ROOT_DIR, relative_document)
            if not os.path.exists(document_path) and relative_document == "runtime/PYTHON_RUNTIME.md":
                continue
            document_dir = os.path.dirname(document_path)
            content = read_repo_file(*relative_document.split("/"))
            if relative_document not in {"README.md", "README.ko.md"}:
                self.assertNotIn("[English]", content, relative_document)
            non_code_content = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
            non_code_content = re.sub(r"`[^`\n]+`", "", non_code_content)
            for raw_target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", non_code_content):
                target = raw_target.strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:") or target.casefold().startswith("data:"):
                    continue
                resolved = os.path.normpath(os.path.join(document_dir, target))
                self.assertTrue(os.path.exists(resolved), f"Broken link in {relative_document}: {raw_target}")


if __name__ == "__main__":
    unittest.main()
