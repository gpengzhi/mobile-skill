import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mobile_skill import installer
from mobile_skill.errors import MobileSkillError


class InstallerTests(unittest.TestCase):
    def test_link_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source")
            destination = Path(directory, "nested", "destination")
            source.write_text("test")

            installer._link(source, destination)
            installer._link(source, destination)

            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), source.resolve())

    def test_link_refuses_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "source")
            destination = Path(directory, "destination")
            source.write_text("source")
            destination.write_text("existing")

            with self.assertRaises(MobileSkillError) as caught:
                installer._link(source, destination)

            self.assertEqual(caught.exception.code, "install_conflict")

    def test_link_accepts_launcher_already_at_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory, "msk")
            launcher.write_text("launcher")

            installer._link(launcher, launcher)

            self.assertTrue(launcher.is_file())

    def test_skill_source_requires_complete_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MobileSkillError) as caught:
                installer.skill_source(Path(directory))

        self.assertEqual(caught.exception.code, "install_source_missing")

    def test_install_codex_links_cli_and_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "project")
            root.mkdir()
            (root / "msk").write_text("launcher")
            (root / "skill").mkdir()
            codex_home = Path(directory, "codex")
            with (
                patch.dict(
                    os.environ,
                    {"HOME": directory, "CODEX_HOME": str(codex_home)},
                ),
                patch("mobile_skill.installer.Path.home", return_value=Path(directory)),
                patch("mobile_skill.installer.project_root", return_value=root),
                patch("mobile_skill.installer.shutil.which", return_value="/usr/bin/codex"),
            ):
                result = installer.install_codex()

            self.assertEqual(result["agent"], "codex")
            self.assertTrue(Path(directory, ".local", "bin", "msk").is_symlink())
            self.assertTrue((codex_home / "skills" / "mobile-skill").is_symlink())

    def test_install_claude_code_links_cli_and_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "project")
            root.mkdir()
            (root / "msk").write_text("launcher")
            (root / "skill").mkdir()
            claude_home = Path(directory, "claude")
            with (
                patch.dict(
                    os.environ,
                    {"HOME": directory, "CLAUDE_CONFIG_DIR": str(claude_home)},
                ),
                patch("mobile_skill.installer.Path.home", return_value=Path(directory)),
                patch("mobile_skill.installer.project_root", return_value=root),
                patch("mobile_skill.installer.shutil.which", return_value="/usr/bin/claude"),
            ):
                result = installer.install_claude_code()

            self.assertEqual(result["agent"], "claude-code")
            self.assertTrue((claude_home / "skills" / "mobile-skill").is_symlink())

    def test_missing_agent_cli_has_stable_error(self):
        with patch("mobile_skill.installer.shutil.which", return_value=None):
            with self.assertRaises(MobileSkillError) as caught:
                installer.install_claude_code()

        self.assertEqual(caught.exception.code, "claude_code_not_found")


if __name__ == "__main__":
    unittest.main()
