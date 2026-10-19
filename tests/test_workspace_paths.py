import os
import sys
import tempfile
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from hierarchical_classifier import parse_rules_from_markdown  # noqa: E402
from workspace_paths import (  # noqa: E402
    ensure_workspace_initialized,
    render_rule_template,
    resolve_workspace_dir,
)


class WorkspacePathTests(unittest.TestCase):
    def test_bundled_workspace_is_used_when_it_contains_rules(self):
        with tempfile.TemporaryDirectory() as root:
            script_dir = os.path.join(root, "scripts")
            workspace_dir = os.path.join(root, "Workspace")
            os.makedirs(script_dir)
            os.makedirs(workspace_dir)
            with open(
                os.path.join(workspace_dir, "Classification_Rules.md"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("rules")

            self.assertEqual(os.path.abspath(workspace_dir), resolve_workspace_dir(script_dir))

    def test_legacy_root_layout_remains_supported_without_workspace_rules(self):
        with tempfile.TemporaryDirectory() as root:
            script_dir = os.path.join(root, "scripts")
            os.makedirs(script_dir)
            with open(
                os.path.join(root, "Classification_Rules.md"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write("rules")

            self.assertEqual(os.path.abspath(root), resolve_workspace_dir(script_dir))

    def test_custom_obsidian_vault_override_via_env_or_settings(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as custom_vault:
            script_dir = os.path.join(root, "scripts")
            runtime_dir = os.path.join(script_dir, ".runtime")
            os.makedirs(runtime_dir)
            with open(
                os.path.join(runtime_dir, "tray_settings.json"),
                "w",
                encoding="utf-8",
            ) as file_obj:
                file_obj.write(f'{{"workspace_path": {custom_vault!r}}}'.replace("'", '"'))

            self.assertEqual(os.path.abspath(custom_vault), resolve_workspace_dir(script_dir))

            env_vault = os.path.join(custom_vault, "EnvVault")
            with patch.dict(os.environ, {"LOG2TOPIC_WORKSPACE": env_vault}):
                self.assertEqual(os.path.abspath(env_vault), resolve_workspace_dir(script_dir))

    def test_starter_rule_templates_initialize_and_parse_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            vault = os.path.join(temp_dir, "MyObsidianVault")
            backups = os.path.join(temp_dir, "backups")
            for tpl_name in ("simple", "research", "software"):
                ensure_workspace_initialized(vault, template_name=tpl_name, backup_root=backups)
                rules_path = os.path.join(vault, "Classification_Rules.md")
                self.assertTrue(os.path.isfile(rules_path))
                self.assertTrue(os.path.isdir(os.path.join(vault, "Daily_Logs")))
                self.assertTrue(os.path.isdir(os.path.join(vault, "attachments")))
                tree = parse_rules_from_markdown(rules_path)
                self.assertEqual(tree.errors, [], f"Template {tpl_name} had rule errors: {tree.errors}")
                self.assertGreaterEqual(len(tree.nodes), 4)
            self.assertTrue(os.path.isdir(os.path.join(backups, "rule_templates")))
