"""Capture and persist screenshot observations."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from . import android, state
from .errors import MobileSkillError


DEFAULT_MODEL_WIDTH = 476
NORMALIZED_COORDINATE_MAX = 999


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
    observation_id = f"obs-{uuid4().hex[:8]}"
    directory = state.screenshots_dir(session_id)
    raw_path = directory / f"{observation_id}.png"
    _, (device_width, device_height) = android.capture(serial, raw_path)
    model_path = directory / f"{observation_id}.jpg"
    android.compress_for_model(
        raw_path, model_path, target_width=model_width
    )

    path = raw_path if full else model_path
    observation: dict[str, Any] = {
        "id": observation_id,
        "path": str(path),
        "width": device_width,
        "height": device_height,
        "raw_path": str(raw_path),
        "model_path": str(model_path),
        "coordinate_scale": NORMALIZED_COORDINATE_MAX,
        "full": full,
        "orientation": "landscape" if device_width > device_height else "portrait",
        "coordinate_space": "normalized_0_999",
        "created_at": time.time(),
    }
    state.update_session(session_id, last_observation=observation)
    return {
        "ok": True,
        "type": "observation",
        "session_id": session_id,
        "device_id": serial,
        "observation_id": observation_id,
        **{key: value for key, value in observation.items() if key != "id"},
    }
