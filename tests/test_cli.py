import unittest
from unittest.mock import patch

from mobile_skill import cli


class CliTests(unittest.TestCase):
    def test_version_reports_runtime_version(self):
        args = cli.build_parser().parse_args(["version"])

        result = cli._dispatch(args)

        self.assertEqual(result["name"], "mobile-skill")
        self.assertEqual(result["version"], "0.1.0")

    def test_parser_accepts_claude_code_install(self):
        args = cli.build_parser().parse_args(["install", "claude-code"])

        self.assertEqual(args.agent, "claude-code")

    def test_cleanup_dispatches_retention_and_dry_run(self):
        args = cli.build_parser().parse_args(
            ["cleanup", "--older-than-days", "14", "--dry-run"]
        )
        cleanup_result = {"dry_run": True, "retention_days": 14}
        with patch("mobile_skill.cli.state.cleanup", return_value=cleanup_result) as cleanup:
            result = cli._dispatch(args)

        cleanup.assert_called_once_with(older_than_days=14, dry_run=True)
        self.assertEqual(result["cleanup"], cleanup_result)

    def test_session_start_runs_automatic_cleanup(self):
        args = cli.build_parser().parse_args(["session", "start"])
        cleanup_result = {"sessions_pruned": ["old1"]}
        session = {"id": "abcd", "device_id": "serial-1", "state": "active"}
        with (
            patch("mobile_skill.cli.android.require_device", return_value="serial-1"),
            patch("mobile_skill.cli.state.cleanup", return_value=cleanup_result) as cleanup,
            patch("mobile_skill.cli.state.create_session", return_value=session) as create,
        ):
            result = cli._dispatch(args)

        cleanup.assert_called_once_with()
        create.assert_called_once_with("serial-1")
        self.assertEqual(result["cleanup"], cleanup_result)

    def test_double_tap_maps_observation_coordinates(self):
        args = cli.build_parser().parse_args(
            [
                "double-tap",
                "238",
                "529",
                "--session",
                "abcd",
                "--observation",
                "obs-1",
            ]
        )
        session = {"id": "abcd"}
        observation = {
            "width": 476,
            "height": 1058,
            "device_width": 1080,
            "device_height": 2400,
        }
        with (
            patch("mobile_skill.cli._driver", return_value=(session, "serial-1")),
            patch("mobile_skill.cli._check_observation", return_value=observation),
            patch("mobile_skill.cli.android.double_tap") as double_tap,
            patch("mobile_skill.cli._invalidate_observation") as invalidate,
        ):
            result = cli._dispatch(args)

        double_tap.assert_called_once_with("serial-1", 540, 1200, 100, (1080, 2400))
        invalidate.assert_called_once_with("abcd")
        self.assertEqual(result["action"], "double-tap")
        self.assertEqual(result["interval_ms"], 100)

    def test_tap_observe_after_uses_default_settle_and_returns_observation(self):
        args = cli.build_parser().parse_args(
            [
                "tap",
                "238",
                "529",
                "--session",
                "abcd",
                "--observation",
                "obs-1",
                "--observe-after",
            ]
        )
        session = {"id": "abcd"}
        observation = {
            "width": 476,
            "height": 1058,
            "device_width": 1080,
            "device_height": 2400,
        }
        captured = {
            "ok": True,
            "type": "observation",
            "session_id": "abcd",
            "device_id": "serial-1",
            "observation_id": "obs-2",
            "path": "/tmp/obs-2.jpg",
        }
        with (
            patch("mobile_skill.cli._driver", return_value=(session, "serial-1")),
            patch("mobile_skill.cli._check_observation", return_value=observation),
            patch("mobile_skill.cli.android.tap") as tap,
            patch("mobile_skill.cli.android.wait") as wait,
            patch("mobile_skill.cli._invalidate_observation") as invalidate,
            patch("mobile_skill.cli.observations.capture", return_value=captured) as capture,
            patch("mobile_skill.cli.time.perf_counter", side_effect=[1.0, 1.301]),
        ):
            result = cli._dispatch(args)

        tap.assert_called_once_with("serial-1", 540, 1200, (1080, 2400))
        wait.assert_called_once_with(300)
        invalidate.assert_called_once_with("abcd")
        capture.assert_called_once_with("abcd", serial="serial-1")
        self.assertEqual(
            result["settle"],
            {"source": "default", "requested_ms": 300, "actual_ms": 301},
        )
        self.assertEqual(result["next_observation"]["observation_id"], "obs-2")
        self.assertNotIn("ok", result["next_observation"])

    def test_back_observe_after_accepts_settle_override(self):
        args = cli.build_parser().parse_args(
            [
                "back",
                "--session",
                "abcd",
                "--observe-after",
                "--settle-ms",
                "25",
            ]
        )
        session = {"id": "abcd"}
        captured = {
            "ok": True,
            "type": "observation",
            "session_id": "abcd",
            "device_id": "serial-1",
            "observation_id": "obs-2",
            "path": "/tmp/obs-2.jpg",
        }
        with (
            patch("mobile_skill.cli._driver", return_value=(session, "serial-1")),
            patch("mobile_skill.cli.android.back") as back,
            patch("mobile_skill.cli.android.wait") as wait,
            patch("mobile_skill.cli._invalidate_observation"),
            patch("mobile_skill.cli.observations.capture", return_value=captured),
            patch("mobile_skill.cli.time.perf_counter", side_effect=[2.0, 2.025]),
        ):
            result = cli._dispatch(args)

        back.assert_called_once_with("serial-1")
        wait.assert_called_once_with(25)
        self.assertEqual(
            result["settle"],
            {"source": "override", "requested_ms": 25, "actual_ms": 25},
        )

    def test_settle_requires_observe_after(self):
        args = cli.build_parser().parse_args(
            ["back", "--session", "abcd", "--settle-ms", "100"]
        )

        with self.assertRaises(cli.MobileSkillError) as caught:
            cli._dispatch(args)

        self.assertEqual(caught.exception.code, "settle_requires_observe_after")

    def test_post_action_observe_failure_reports_applied_action(self):
        args = cli.build_parser().parse_args(
            ["back", "--session", "abcd", "--observe-after", "--settle-ms", "0"]
        )
        session = {"id": "abcd"}
        with (
            patch("mobile_skill.cli._driver", return_value=(session, "serial-1")),
            patch("mobile_skill.cli.android.back"),
            patch("mobile_skill.cli._invalidate_observation"),
            patch(
                "mobile_skill.cli.observations.capture",
                side_effect=cli.MobileSkillError("capture_failed", "capture failed"),
            ),
            patch("mobile_skill.cli.time.perf_counter", side_effect=[3.0, 3.0]),
        ):
            with self.assertRaises(cli.MobileSkillError) as caught:
                cli._dispatch(args)

        self.assertEqual(caught.exception.code, "post_action_observe_failed")
        self.assertTrue(caught.exception.details["action_applied"])
        self.assertEqual(caught.exception.details["settle"]["requested_ms"], 0)


if __name__ == "__main__":
    unittest.main()
