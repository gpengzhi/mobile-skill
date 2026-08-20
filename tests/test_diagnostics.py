import unittest
from unittest.mock import patch

from mobile_skill import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_doctor_reports_unicode_limitation(self):
        with (
            patch(
                "mobile_skill.diagnostics.android.list_devices",
                return_value=[{"serial": "device-a", "state": "device"}],
            ),
            patch("mobile_skill.diagnostics.android.screen_size", return_value=(321, 654)),
            patch(
                "mobile_skill.diagnostics.android.capture",
                return_value=(unittest.mock.Mock(), (321, 654)),
            ),
            patch(
                "mobile_skill.diagnostics.android.input_capabilities",
                return_value={
                    "ascii": {"status": "ready"},
                    "unicode": {"status": "unavailable"},
                },
            ),
            patch("mobile_skill.diagnostics.state.list_sessions", return_value=[]),
        ):
            result = diagnostics.doctor()

        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["checks"]["input"]["unicode"]["status"], "unavailable")

    def test_doctor_checks_screenshot_capture(self):
        with (
            patch(
                "mobile_skill.diagnostics.android.list_devices",
                return_value=[{"serial": "device-a", "state": "device"}],
            ),
            patch("mobile_skill.diagnostics.android.screen_size", return_value=(321, 654)),
            patch(
                "mobile_skill.diagnostics.android.capture",
                return_value=(unittest.mock.Mock(), (321, 654)),
            ),
            patch(
                "mobile_skill.diagnostics.android.input_capabilities",
                return_value={
                    "ascii": {"status": "ready"},
                    "unicode": {"status": "ready"},
                },
            ),
            patch("mobile_skill.diagnostics.state.list_sessions", return_value=[]),
        ):
            result = diagnostics.doctor()

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["checks"]["screenshot"]["status"], "ready")

    def test_doctor_does_not_choose_between_multiple_devices(self):
        with (
            patch(
                "mobile_skill.diagnostics.android.list_devices",
                return_value=[
                    {"serial": "device-a", "state": "device"},
                    {"serial": "device-b", "state": "device"},
                ],
            ),
            patch("mobile_skill.diagnostics.android.capture") as capture,
            patch("mobile_skill.diagnostics.state.list_sessions", return_value=[]),
        ):
            result = diagnostics.doctor()

        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["checks"]["device"]["status"], "attention")
        capture.assert_not_called()

    def test_codex_checks_distinguish_config_from_vision(self):
        completed = unittest.mock.Mock(returncode=0, stdout="enabled: true\n", stderr="")
        with (
            patch("mobile_skill.diagnostics.shutil.which", return_value="/usr/bin/codex"),
            patch("mobile_skill.diagnostics._run", return_value=completed),
            patch("mobile_skill.diagnostics.Path.is_file", return_value=True),
        ):
            result = diagnostics.codex_checks()

        self.assertEqual(result["skill"]["status"], "ready")
        self.assertEqual(result["vision"]["status"], "unverified")
        self.assertEqual(result["vision"]["image_tool"], "view_image")

    def test_claude_code_checks_distinguish_config_from_vision(self):
        version = unittest.mock.Mock(returncode=0, stdout="2.1.158\n", stderr="")
        with (
            patch("mobile_skill.diagnostics.shutil.which", return_value="/usr/bin/claude"),
            patch("mobile_skill.diagnostics._run", return_value=version),
            patch("mobile_skill.diagnostics.Path.is_file", return_value=True),
        ):
            result = diagnostics.claude_code_checks()

        self.assertEqual(result["skill"]["status"], "ready")
        self.assertEqual(result["vision"]["status"], "unverified")
        self.assertEqual(result["vision"]["image_tool"], "Read")


if __name__ == "__main__":
    unittest.main()
