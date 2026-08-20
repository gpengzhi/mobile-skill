import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from mobile_skill import state
from mobile_skill.errors import MobileSkillError


class StateTests(unittest.TestCase):
    def test_invalid_state_file_has_stable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "sessions.json").write_text("{}")
            with patch.dict(os.environ, {"MOBILE_SKILL_HOME": directory}):
                with self.assertRaises(MobileSkillError) as caught:
                    state.list_sessions()

        self.assertEqual(caught.exception.code, "state_invalid")

    def test_session_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MOBILE_SKILL_HOME": directory}):
                created = state.create_session("device-a")
                self.assertEqual(created["state"], "active")
                self.assertEqual(state.get_session(created["id"])["device_id"], "device-a")
                with self.assertRaises(RuntimeError):
                    state.create_session("device-a")
                state.update_session(created["id"], last_observation={"id": "obs-1"})
                self.assertEqual(
                    state.get_session(created["id"])["last_observation"]["id"], "obs-1"
                )
                stopped = state.stop_session(created["id"])
                self.assertEqual(stopped["state"], "stopped")

                saved = json.loads(Path(directory, "sessions.json").read_text())
                self.assertEqual(len(saved["sessions"]), 1)

    def test_user_takeover_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MOBILE_SKILL_HOME": directory}):
                created = state.create_session("device-a")
                state.update_session(created["id"], last_observation={"id": "obs-1"})

                waiting = state.request_help(
                    created["id"], "login_required", "Please finish signing in on the phone."
                )
                self.assertEqual(waiting["state"], "paused")
                self.assertEqual(waiting["pause_reason"], "user_intervention")
                self.assertEqual(waiting["help_request"]["status"], "waiting_for_user")
                self.assertIsNone(waiting["last_observation"])

                resumed = state.resume_session(created["id"])
                self.assertEqual(resumed["state"], "active")
                self.assertEqual(resumed["help_request"]["status"], "resolved")
                self.assertIsNone(resumed["last_observation"])

    def test_cleanup_prunes_old_stopped_sessions_and_orphaned_screenshots(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"MOBILE_SKILL_HOME": directory, "MOBILE_SKILL_RETENTION_DAYS": "7"},
            ):
                active = state.create_session("serial-active")
                old = state.create_session("serial-old")
                recent = state.create_session("serial-recent")
                state.stop_session(old["id"])
                state.stop_session(recent["id"])
                state.update_session(old["id"], stopped_at="2026-08-01T00:00:00+00:00")
                state.update_session(recent["id"], stopped_at="2026-08-18T00:00:00+00:00")

                for session_id in (active["id"], old["id"], recent["id"]):
                    screenshot = state.screenshots_dir(session_id) / "screen.jpg"
                    screenshot.parent.mkdir(parents=True)
                    screenshot.write_bytes(b"screen")
                orphan = Path(directory, "screenshots", "orphan")
                orphan.mkdir()
                (orphan / "screen.jpg").write_bytes(b"orphan")
                old_timestamp = datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp()
                os.utime(orphan, (old_timestamp, old_timestamp))

                preview = state.cleanup(
                    dry_run=True, now=datetime(2026, 8, 19, tzinfo=timezone.utc)
                )
                self.assertEqual(preview["sessions_pruned"], [old["id"]])
                self.assertTrue(state.screenshots_dir(old["id"]).exists())
                self.assertTrue(orphan.exists())

                result = state.cleanup(now=datetime(2026, 8, 19, tzinfo=timezone.utc))

                self.assertEqual(result["sessions_pruned"], [old["id"]])
                self.assertGreaterEqual(result["bytes_reclaimable"], 12)
                self.assertFalse(state.screenshots_dir(old["id"]).exists())
                self.assertFalse(orphan.exists())
                self.assertTrue(state.screenshots_dir(active["id"]).exists())
                self.assertTrue(state.screenshots_dir(recent["id"]).exists())
                remaining = {session["id"] for session in state.list_sessions()}
                self.assertEqual(remaining, {active["id"], recent["id"]})

    def test_invalid_retention_environment_has_stable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                os.environ,
                {"MOBILE_SKILL_HOME": directory, "MOBILE_SKILL_RETENTION_DAYS": "invalid"},
            ):
                with self.assertRaises(MobileSkillError) as caught:
                    state.cleanup()

        self.assertEqual(caught.exception.code, "invalid_retention_days")
