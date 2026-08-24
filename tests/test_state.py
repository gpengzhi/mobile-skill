"""Session lifecycle and cleanup — filesystem-backed, no ADB."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mobile_skill import state
from mobile_skill.errors import MobileSkillError


def test_home_reads_env(msk_home: Path) -> None:
    assert state.home() == msk_home


def test_create_and_get_session(msk_home: Path) -> None:
    created = state.create_session("emu-1234")
    got = state.get_session(created["id"])
    assert got["id"] == created["id"]
    assert got["device_id"] == "emu-1234"
    assert got["state"] == "active"
    assert got["last_observation"] is None


def test_device_busy_rejects_second_lease(msk_home: Path) -> None:
    state.create_session("emu-A")
    with pytest.raises(MobileSkillError) as excinfo:
        state.create_session("emu-A")
    assert excinfo.value.code == "device_busy"


def test_different_devices_ok(msk_home: Path) -> None:
    state.create_session("emu-A")
    state.create_session("emu-B")
    assert len(state.list_sessions()) == 2


def test_stop_session(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    stopped = state.stop_session(s["id"])
    assert stopped["state"] == "stopped"
    assert "stopped_at" in stopped


def test_pause_then_resume(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    state.update_session(s["id"], last_observation={"id": "obs-x"}, unlock_verified_at=1.0)
    paused = state.pause_session(s["id"])
    assert paused["state"] == "paused"
    resumed = state.resume_session(s["id"])
    assert resumed["state"] == "active"
    assert resumed["last_observation"] is None
    assert resumed["unlock_verified_at"] is None
    assert resumed["pause_reason"] is None


def test_pause_when_stopped_rejected(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    state.stop_session(s["id"])
    with pytest.raises(MobileSkillError) as excinfo:
        state.pause_session(s["id"])
    assert excinfo.value.code == "invalid_session_state"


def test_resume_when_active_rejected(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    with pytest.raises(MobileSkillError) as excinfo:
        state.resume_session(s["id"])
    assert excinfo.value.code == "invalid_session_state"


def test_request_help_transitions_and_resume_resolves(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    paused = state.request_help(s["id"], "login_required", "please log in")
    assert paused["state"] == "paused"
    assert paused["help_request"]["status"] == "waiting_for_user"
    assert paused["help_request"]["reason"] == "login_required"
    resumed = state.resume_session(s["id"])
    assert resumed["help_request"]["status"] == "resolved"
    assert "resolved_at" in resumed["help_request"]


def test_get_missing_session_raises(msk_home: Path) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        state.get_session("no-such-id")
    assert excinfo.value.code == "session_not_found"


def test_cleanup_dry_run_reports_but_does_not_delete(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    state.stop_session(s["id"])
    directory = state.screenshots_dir(s["id"])
    directory.mkdir(parents=True)
    (directory / "obs.jpg").write_bytes(b"x" * 128)

    later = datetime.now(timezone.utc) + timedelta(days=30)
    report = state.cleanup(dry_run=True, now=later)

    assert s["id"] in report["sessions_pruned"]
    assert report["bytes_reclaimable"] >= 128
    assert directory.exists()  # dry-run
    assert state.get_session(s["id"])  # session still there


def test_cleanup_removes_stopped_and_screenshots(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    state.stop_session(s["id"])
    directory = state.screenshots_dir(s["id"])
    directory.mkdir(parents=True)
    (directory / "obs.jpg").write_bytes(b"data")

    later = datetime.now(timezone.utc) + timedelta(days=30)
    state.cleanup(now=later)

    with pytest.raises(MobileSkillError):
        state.get_session(s["id"])
    assert not directory.exists()


def test_cleanup_keeps_recent_stopped(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    state.stop_session(s["id"])
    report = state.cleanup()  # now = now(); stopped_at ~ now → within retention
    assert report["sessions_pruned"] == []
    assert state.get_session(s["id"])["state"] == "stopped"


def test_cleanup_idle_stops_active(msk_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_IDLE_SESSION_TTL_S", "1")
    s = state.create_session("emu-1")
    state.update_session(s["id"], last_activity_at=time.time() - 3600)
    report = state.cleanup()
    assert s["id"] in report["sessions_idle_stopped"]
    got = state.get_session(s["id"])
    assert got["state"] == "stopped"
    assert got["stop_reason"] == "idle_timeout"


def test_cleanup_prunes_orphan_screenshot_dirs(msk_home: Path) -> None:
    screenshots_root = state.home() / "screenshots"
    orphan = screenshots_root / "orphan-xyz"
    orphan.mkdir(parents=True)
    (orphan / "old.jpg").write_bytes(b"x")

    old_time = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    import os
    os.utime(orphan / "old.jpg", (old_time, old_time))
    os.utime(orphan, (old_time, old_time))

    report = state.cleanup()
    assert str(orphan) in report["screenshot_directories_pruned"]
    assert not orphan.exists()


def test_cleanup_writes_only_when_state_changes(msk_home: Path) -> None:
    state.cleanup()  # no sessions → nothing to write
    assert not state.sessions_path().exists()


def test_state_file_written_atomically(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    data = json.loads(state.sessions_path().read_text())
    assert s["id"] in data["sessions"]
    assert data["sessions"][s["id"]]["state"] == "active"


def test_session_ids_are_short_and_hex(msk_home: Path) -> None:
    s = state.create_session("emu-1")
    assert len(s["id"]) == 6
    assert all(c in "0123456789abcdef" for c in s["id"])
