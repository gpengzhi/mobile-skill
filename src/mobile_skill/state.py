"""Persistent mobile-skill session state."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import MobileSkillError


DEFAULT_RETENTION_DAYS = 7
DEFAULT_IDLE_SESSION_TTL_S = 1800


def home() -> Path:
    configured = os.environ.get("MOBILE_SKILL_HOME")
    if configured:
        return Path(configured).expanduser()
    state_root = os.environ.get("XDG_STATE_HOME")
    if state_root:
        return Path(state_root).expanduser() / "mobile-skill"
    return Path.home() / ".local" / "state" / "mobile-skill"


def sessions_path() -> Path:
    return home() / "sessions.json"


def screenshots_dir(session_id: str) -> Path:
    return home() / "screenshots" / session_id


def retention_days() -> int:
    configured = os.environ.get("MOBILE_SKILL_RETENTION_DAYS")
    if configured is None:
        return DEFAULT_RETENTION_DAYS
    try:
        value = int(configured)
    except ValueError as error:
        raise MobileSkillError(
            "invalid_retention_days",
            "MOBILE_SKILL_RETENTION_DAYS must be a non-negative integer",
        ) from error
    if value < 0:
        raise MobileSkillError(
            "invalid_retention_days",
            "MOBILE_SKILL_RETENTION_DAYS must be a non-negative integer",
        )
    return value


def idle_session_ttl_s() -> int:
    configured = os.environ.get("MOBILE_SKILL_IDLE_SESSION_TTL_S")
    if configured is None:
        return DEFAULT_IDLE_SESSION_TTL_S
    try:
        value = int(configured)
    except ValueError as error:
        raise MobileSkillError(
            "invalid_idle_session_ttl",
            "MOBILE_SKILL_IDLE_SESSION_TTL_S must be a non-negative integer",
        ) from error
    if value < 0:
        raise MobileSkillError(
            "invalid_idle_session_ttl",
            "MOBILE_SKILL_IDLE_SESSION_TTL_S must be a non-negative integer",
        )
    return value


def _activity_timestamp(session: dict[str, Any], session_id: str) -> datetime:
    last_activity = session.get("last_activity_at")
    if isinstance(last_activity, (int, float)):
        return datetime.fromtimestamp(last_activity, timezone.utc)
    return _parse_timestamp(session.get("created_at"), session_id=session_id)


def _read() -> dict[str, Any]:
    try:
        value = json.loads(sessions_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"sessions": {}}
    except (OSError, json.JSONDecodeError) as error:
        raise MobileSkillError(
            "state_unreadable", f"cannot read state file {sessions_path()}: {error}"
        ) from error
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), dict):
        raise MobileSkillError("state_invalid", f"invalid state file: {sessions_path()}")
    return value


def _write(value: dict[str, Any]) -> None:
    path = sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="sessions-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _locked():
    """Hold an exclusive lock for one read-check-write sequence on the state file."""
    path = home() / "sessions.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _parse_timestamp(value: Any, *, session_id: str) -> datetime:
    if not isinstance(value, str):
        raise MobileSkillError(
            "state_invalid", f"session {session_id} has no valid cleanup timestamp"
        )
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise MobileSkillError(
            "state_invalid", f"session {session_id} has an invalid cleanup timestamp"
        ) from error
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _directory_size(path: Path) -> int:
    if path.is_symlink():
        return path.lstat().st_size
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total


def _remove_directory(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    else:
        shutil.rmtree(path)


def cleanup(
    *,
    older_than_days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    days = retention_days() if older_than_days is None else older_than_days
    if days < 0:
        raise MobileSkillError(
            "invalid_retention_days", "cleanup retention must be a non-negative integer"
        )

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    current_time = current_time.astimezone(timezone.utc)
    cutoff = current_time - timedelta(days=days)
    idle_cutoff = current_time - timedelta(seconds=idle_session_ttl_s())
    with _locked():
        value = _read()
        screenshots_root = home() / "screenshots"
        sessions_to_remove: list[str] = []
        sessions_idle_stopped: list[str] = []
        directories_to_remove: list[Path] = []

        state_changed = False
        for session_id, session in value["sessions"].items():
            if session.get("state") not in {"active", "paused"}:
                continue
            if _activity_timestamp(session, session_id) > idle_cutoff:
                continue
            if not dry_run:
                session["state"] = "stopped"
                session["stopped_at"] = _now()
                session["stop_reason"] = "idle_timeout"
                state_changed = True
            sessions_idle_stopped.append(session_id)

        for session_id, session in value["sessions"].items():
            if session.get("state") != "stopped":
                continue
            timestamp = _parse_timestamp(
                session.get("stopped_at") or session.get("created_at"), session_id=session_id
            )
            if timestamp > cutoff:
                continue
            if Path(session_id).name != session_id or session_id in {"", ".", ".."}:
                raise MobileSkillError("state_invalid", f"invalid session id: {session_id!r}")
            sessions_to_remove.append(session_id)
            session_directory = screenshots_root / session_id
            if session_directory.exists() or session_directory.is_symlink():
                directories_to_remove.append(session_directory)

        known_sessions = set(value["sessions"])
        if screenshots_root.is_dir():
            for candidate in screenshots_root.iterdir():
                if candidate.name in known_sessions or not (
                    candidate.is_dir() or candidate.is_symlink()
                ):
                    continue
                modified_at = datetime.fromtimestamp(candidate.lstat().st_mtime, timezone.utc)
                if modified_at <= cutoff:
                    directories_to_remove.append(candidate)

        unique_directories = list(dict.fromkeys(directories_to_remove))
        bytes_reclaimable = sum(_directory_size(path) for path in unique_directories)
        if not dry_run:
            for directory in unique_directories:
                _remove_directory(directory)
            if sessions_to_remove:
                for session_id in sessions_to_remove:
                    del value["sessions"][session_id]
                state_changed = True
            if state_changed:
                _write(value)

    return {
        "dry_run": dry_run,
        "retention_days": days,
        "idle_session_ttl_s": idle_session_ttl_s(),
        "cutoff": cutoff.isoformat(timespec="seconds"),
        "sessions_idle_stopped": sessions_idle_stopped,
        "sessions_pruned": sessions_to_remove,
        "screenshot_directories_pruned": [str(path) for path in unique_directories],
        "bytes_reclaimable": bytes_reclaimable,
    }


def _require_session(value: dict[str, Any], session_id: str) -> dict[str, Any]:
    session = value["sessions"].get(session_id)
    if session is None:
        raise MobileSkillError("session_not_found", f"session not found: {session_id}")
    return session


def create_session(
    device_id: str, platform: str = "android", backend: str = "adb"
) -> dict[str, Any]:
    with _locked():
        value = _read()
        for session in value["sessions"].values():
            if session["device_id"] == device_id and session["state"] in {"active", "paused"}:
                raise MobileSkillError(
                    "device_busy",
                    f"device {device_id} is already leased by session {session['id']}",
                    f"stop session {session['id']} before starting another one",
                )
        session_id = uuid4().hex[:6]
        while session_id in value["sessions"]:
            session_id = uuid4().hex[:6]
        session = {
            "id": session_id,
            "device_id": device_id,
            "platform": platform,
            "backend": backend,
            "state": "active",
            "created_at": _now(),
            "last_activity_at": time.time(),
            "last_observation": None,
        }
        value["sessions"][session_id] = session
        _write(value)
        return session


def get_session(session_id: str) -> dict[str, Any]:
    return _require_session(_read(), session_id)


def list_sessions() -> list[dict[str, Any]]:
    return list(_read()["sessions"].values())


def _mutate(session_id: str, **changes: Any) -> dict[str, Any]:
    value = _read()
    session = _require_session(value, session_id)
    session.update(changes)
    _write(value)
    return session


def update_session(session_id: str, **changes: Any) -> dict[str, Any]:
    with _locked():
        return _mutate(session_id, **changes)


def stop_session(session_id: str) -> dict[str, Any]:
    with _locked():
        return _mutate(session_id, state="stopped", stopped_at=_now())


def pause_session(session_id: str) -> dict[str, Any]:
    with _locked():
        value = _read()
        session = _require_session(value, session_id)
        if session["state"] != "active":
            raise MobileSkillError(
                "invalid_session_state",
                f"cannot pause session {session_id}: it is {session['state']}",
            )
        session["state"] = "paused"
        _write(value)
        return session


def request_help(session_id: str, reason: str, message: str) -> dict[str, Any]:
    with _locked():
        value = _read()
        session = _require_session(value, session_id)
        if session["state"] != "active":
            raise MobileSkillError(
                "invalid_session_state",
                f"cannot request help for session {session_id}: it is {session['state']}",
            )
        session["state"] = "paused"
        session["pause_reason"] = "user_intervention"
        session["help_request"] = {
            "id": f"help-{uuid4().hex[:8]}",
            "reason": reason,
            "message": message,
            "status": "waiting_for_user",
            "created_at": _now(),
        }
        session["last_observation"] = None
        session["unlock_verified_at"] = None
        _write(value)
        return session


def resume_session(session_id: str) -> dict[str, Any]:
    with _locked():
        value = _read()
        session = _require_session(value, session_id)
        if session["state"] != "paused":
            raise MobileSkillError(
                "invalid_session_state",
                f"cannot resume session {session_id}: it is {session['state']}",
            )
        session["state"] = "active"
        session["last_observation"] = None
        session["unlock_verified_at"] = None
        session["pause_reason"] = None
        help_request = session.get("help_request")
        if help_request and help_request.get("status") == "waiting_for_user":
            help_request["status"] = "resolved"
            help_request["resolved_at"] = _now()
        _write(value)
        return session
