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
        text_suffixes = {".bat", ".cs", ".css", ".html", ".js", ".json", ".md", ".ps1", ".py"}

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
        content = read_repo_file("README.md")

        self.assertIn("# Log2Topic", content)
        self.assertIn("## 평소 사용 방법", content)
        self.assertIn("개인 지식 위키", content)
        self.assertIn("## 선택 사항: 외부 서비스", content)
        self.assertIn("Log2Topic.exe", content)
        self.assertIn("로컬 문서 갱신", content)
        self.assertIn("assets/log2topic.png", content)
        self.assertIn("Workspace/", content)
        self.assertNotIn("[English]", content)
        self.assertNotIn("README.ko.md", content)
        self.assertIn("assets/log2topic-tray-menu-ko.png", content)
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "assets", "log2topic-tray-menu-ko.png"))
        )
        self.assertIn("### Notion", content)
        self.assertIn("docs/SYSTEM_REFERENCE.md", content)
        self.assertIn("docs/NOTION_INTEGRATION.md", content)
        self.assertNotIn("run_classify_only.bat", content)
        self.assertNotIn("## Git으로 배포하고 업데이트하기", content)
        self.assertNotIn("git clone <저장소 URL>", content)
        self.assertNotIn("git pull --ff-only", content)

    def test_feedback_channel_and_issue_templates_are_distributed(self):
        readme = read_repo_file("README.md")
        bug_template = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "01-bug.yml"
        )
        feature_template = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "02-feature-request.yml"
        )
        chooser = read_repo_file(
            ".github", "ISSUE_TEMPLATE", "config.yml"
        )

        self.assertIn("## 피드백과 문제 제보", readme)
        self.assertIn("GitHub `Issues`", readme)
        self.assertIn("연구자료와 인증정보", readme)
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
        resolver = read_repo_file("scripts", "resolve_python.bat").casefold()
        runtime_reference = read_repo_file("runtime", "PYTHON_RUNTIME.md")
        automation = read_repo_file("scripts", "configure_automation.ps1")

        self.assertLess(resolver.index("bundled_python"), resolver.index("python -c"))
        self.assertIn("runtime\\python\\python.exe", resolver)
        self.assertIn("python-3.13.15-embed-amd64.zip", runtime_reference)
        self.assertIn('Join-Path $vaultRoot "Log2Topic.exe"', automation)
        self.assertIn("[string]$DaysCsv", automation)
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
            "docs/USER_GUIDE.md",
            "docs/NOTION_INTEGRATION.md",
            "docs/SYSTEM_REFERENCE.md",
            "Workspace/Classification_Rules.md",
            "runtime/PYTHON_RUNTIME.md",
        )
        for removed_document in (
            "README.ko.md",
            "docs/USER_GUIDE.ko.md",
            "docs/NOTION_INTEGRATION.ko.md",
            "docs/SYSTEM_REFERENCE.ko.md",
        ):
            self.assertFalse(os.path.exists(os.path.join(ROOT_DIR, removed_document)))

        for relative_document in documents:
            document_path = os.path.join(ROOT_DIR, relative_document)
            document_dir = os.path.dirname(document_path)
            content = read_repo_file(*relative_document.split("/"))
            self.assertNotIn("[English]", content, relative_document)
            for raw_target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", content):
                target = raw_target.strip("<>").split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                resolved = os.path.normpath(os.path.join(document_dir, target))
                self.assertTrue(os.path.exists(resolved), f"Broken link in {relative_document}: {raw_target}")


if __name__ == "__main__":
    unittest.main()
