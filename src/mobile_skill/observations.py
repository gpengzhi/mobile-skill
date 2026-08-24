"""Capture and persist screenshot observations."""

from __future__ import annotations

import os
import time
from typing import Any
from uuid import uuid4

from . import android, state
from .errors import MobileSkillError


DEFAULT_MODEL_WIDTH = 476
NORMALIZED_COORDINATE_MAX = 999
UNLOCK_TTL_S_DEFAULT = 30.0


def unlock_ttl_s() -> float:
    configured = os.environ.get("MOBILE_SKILL_UNLOCK_TTL_S")
    if configured is None:
        return UNLOCK_TTL_S_DEFAULT
    try:
        value = float(configured)
    except ValueError as error:
        raise MobileSkillError(
            "invalid_unlock_ttl",
            "MOBILE_SKILL_UNLOCK_TTL_S must be a non-negative number",
        ) from error
    if value < 0:
        raise MobileSkillError(
            "invalid_unlock_ttl",
            "MOBILE_SKILL_UNLOCK_TTL_S must be a non-negative number",
        )
    return value


def ensure_session_unlocked(session: dict[str, Any], serial: str) -> None:
    """Verify the phone is unlocked, respecting the session's 30s unlock cache."""
    verified_at = session.get("unlock_verified_at")
    now = time.time()
    if verified_at is not None and now - verified_at < unlock_ttl_s():
        return
    android.ensure_unlocked(serial)
    state.update_session(session["id"], unlock_verified_at=now)
    session["unlock_verified_at"] = now


def capture(
    session_id: str,
    *,
    full: bool = False,
    model_width: int = DEFAULT_MODEL_WIDTH,
    serial: str | None = None,
) -> dict[str, Any]:
    session = state.get_session(session_id)
    if session["state"] != "active":
        raise MobileSkillError(
            "session_paused" if session["state"] == "paused" else "invalid_session_state",
            f"session {session_id} is {session['state']}",
        )

    serial = serial or android.require_device(session["device_id"])
    ensure_session_unlocked(session, serial)
    observation_id = f"obs-{uuid4().hex[:8]}"
    directory = state.screenshots_dir(session_id)
    keep_raw = full or os.environ.get("MOBILE_SKILL_KEEP_RAW") == "1"
    raw_path = directory / f"{observation_id}.png" if keep_raw else None
    image_bytes, (device_width, device_height) = android.capture(serial, raw_path)
    model_path = directory / f"{observation_id}.jpg"
    android.compress_for_model(image_bytes, model_path, target_width=model_width)

    path = raw_path if full else model_path
    observation: dict[str, Any] = {
        "id": observation_id,
        "path": str(path),
        "width": device_width,
        "height": device_height,
        "raw_path": str(raw_path) if raw_path is not None else None,
        "model_path": str(model_path),
        "coordinate_scale": NORMALIZED_COORDINATE_MAX,
        "full": full,
        "orientation": "landscape" if device_width > device_height else "portrait",
        "coordinate_space": "normalized_0_999",
        "created_at": time.time(),
    }
    state.update_session(
        session_id, last_observation=observation, last_activity_at=time.time()
    )
    return {
        "ok": True,
        "type": "observation",
        "session_id": session_id,
        "device_id": serial,
        "observation_id": observation_id,
        **{key: value for key, value in observation.items() if key != "id"},
    }
