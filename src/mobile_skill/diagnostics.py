"""Environment and Agent integration diagnostics."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import PIL
except ImportError:
    PIL = None

from . import android, state


PILLOW_REQUIRED_MAJOR = 10


def _pillow_check() -> dict[str, Any]:
    if PIL is None:
        return _check("missing", hint="pip install Pillow")
    major = PIL.__version__.partition(".")[0]
    ready = major.isdigit() and int(major) >= PILLOW_REQUIRED_MAJOR
    return _check(
        "ready" if ready else "unsupported",
        version=PIL.__version__,
        required=f">={PILLOW_REQUIRED_MAJOR}",
    )


def _check(status: str, **details: Any) -> dict[str, Any]:
    return {"status": status, **details}


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def _agent_checks(agent: str) -> dict[str, Any]:
    if agent == "codex":
        command = "codex"
        home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        install_hint = "run `msk install codex`"
        image_tool = "view_image"
    else:
        command = "claude"
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        install_hint = "run `msk install claude-code`"
        image_tool = "Read"

    executable = shutil.which(command)
    if executable is None:
        return {
            "cli": _check("missing", hint=f"install {command} CLI"),
            "skill": _check("unknown"),
            "vision": _check("unverified"),
        }

    try:
        version = _run([executable, "--version"])
        cli = _check(
            "ready" if version.returncode == 0 else "error",
            path=executable,
            version=version.stdout.strip() or version.stderr.strip(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        cli = _check("error", path=executable, message=str(error))
    skill_path = home / "skills" / "mobile-skill" / "SKILL.md"

    return {
        "cli": cli,
        "skill": _check(
            "ready" if skill_path.is_file() else "missing",
            path=str(skill_path),
            hint=None if skill_path.is_file() else install_hint,
        ),
        "vision": _check(
            "unverified",
            image_tool=image_tool,
            reason="configuration checks cannot prove image understanding",
            hint="run a visual black-box test with the configured model",
        ),
    }


def codex_checks() -> dict[str, Any]:
    return _agent_checks("codex")


def claude_code_checks() -> dict[str, Any]:
    return _agent_checks("claude-code")


def doctor(agent: str | None = None) -> dict[str, Any]:
    devices = android.list_devices()
    ready = [device for device in devices if device["state"] == "device"]
    requested = os.environ.get("ANDROID_SERIAL")
    if requested:
        selected = next((device for device in ready if device["serial"] == requested), None)
    else:
        selected = ready[0] if len(ready) == 1 else None
    if selected:
        device_status = "ready"
        device_hint = None
    elif ready:
        device_status = "attention"
        device_hint = "set ANDROID_SERIAL or start a Session with --device"
    else:
        device_status = "missing"
        device_hint = "connect and authorize an Android phone"
    active_sessions = [
        session for session in state.list_sessions() if session["state"] in {"active", "paused"}
    ]
    checks: dict[str, Any] = {
        "python": _check(
            "ready" if sys.version_info >= (3, 11) else "unsupported",
            version=".".join(map(str, sys.version_info[:3])),
            required=">=3.11",
        ),
        "pillow": _pillow_check(),
        "adb": _check("ready", path=android.adb_path()),
        "device": _check(
            device_status,
            devices=devices,
            hint=device_hint,
        ),
        "sessions": _check(
            "ready" if not active_sessions else "attention",
            active=len(active_sessions),
            session_ids=[session["id"] for session in active_sessions],
        ),
    }

    result: dict[str, Any] = {
        "adb": android.adb_path(),
        "devices": devices,
        "checks": checks,
    }
    if selected:
        serial = selected["serial"]
        try:
            result["screen"] = {"device": serial, "size": android.screen_size(serial)}
        except Exception as error:
            checks["screen"] = _check("error", message=str(error))
        try:
            with tempfile.TemporaryDirectory(prefix="mobile-skill-doctor-") as directory:
                raw_path = Path(directory, "screen.png")
                _, capture_size = android.capture(serial, raw_path)
                _, model_size = android.compress_for_model(raw_path, Path(directory, "screen.jpg"))
            checks["screenshot"] = _check("ready", size=capture_size, model_size=model_size)
        except Exception as error:
            checks["screenshot"] = _check("error", message=str(error))
        try:
            checks["input"] = android.input_capabilities(serial)
        except Exception as error:
            checks["input"] = _check("error", message=str(error))
        result["status"] = (
            "ready"
            if checks["screenshot"]["status"] == "ready"
            and checks["input"].get("unicode", {}).get("status") == "ready"
            and "screen" in result
            else "limited"
        )
    elif ready:
        result["status"] = "limited"
    else:
        result["status"] = "no-ready-device"

    if agent in {"codex", "claude-code"}:
        agent_checks = codex_checks() if agent == "codex" else claude_code_checks()
        checks[agent] = agent_checks
        if any(
            item["status"] not in {"ready", "unverified"}
            for item in agent_checks.values()
        ):
            result["status"] = "limited"
    return result
