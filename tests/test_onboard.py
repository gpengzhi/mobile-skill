"""onboard: drive a device from disconnected/unauthorized to ready."""

from __future__ import annotations

import pytest

from mobile_skill import android, diagnostics, onboard
from mobile_skill.errors import MobileSkillError


@pytest.fixture
def scripted_onboard(monkeypatch):
    """Wire onboard against a scripted device state sequence.

    Also stubs restart_server (records calls), time.sleep (no-op), and
    diagnostics.doctor (returns a canned final report).
    """
    state = {"index": 0, "restarts": 0}

    def list_devices():
        step = state["listings"][min(state["index"], len(state["listings"]) - 1)]
        state["index"] += 1
        return step

    def restart_server():
        state["restarts"] += 1

    monkeypatch.setattr(android, "list_devices", list_devices)
    monkeypatch.setattr(android, "restart_server", restart_server)
    monkeypatch.setattr(onboard.time, "sleep", lambda s: None)
    monkeypatch.setattr(onboard.time, "monotonic", lambda: state.get("now", 0))
    monkeypatch.setattr(
        diagnostics, "doctor", lambda serial=None: {"status": "ready", "serial": serial}
    )
    return state


def test_onboard_ready_immediately(scripted_onboard) -> None:
    scripted_onboard["listings"] = [[{"serial": "emu-1", "state": "device"}]]
    result = onboard.onboard()
    assert result["onboarding"] == [{"step": "device_ready", "serial": "emu-1"}]
    assert result["status"] == "ready"
    assert scripted_onboard["restarts"] == 0


def test_onboard_recovers_after_restart(scripted_onboard) -> None:
    scripted_onboard["listings"] = [
        [{"serial": "emu-1", "state": "unauthorized"}],
        [{"serial": "emu-1", "state": "device"}],
    ]
    result = onboard.onboard(retries=1, timeout_s=60)
    steps = [event["step"] for event in result["onboarding"]]
    assert "vendor_hint" in steps
    assert "restart_adb_server" in steps
    assert steps[-1] == "device_ready"
    assert scripted_onboard["restarts"] == 1


def test_onboard_timeout_unauthorized(scripted_onboard) -> None:
    scripted_onboard["listings"] = [[{"serial": "emu-1", "state": "unauthorized"}]]
    # Force clock past deadline on next iteration
    calls = {"n": 0}

    def monotonic():
        calls["n"] += 1
        return 999 if calls["n"] > 2 else 0

    import time as time_module
    from mobile_skill import onboard as onboard_module
    onboard_module.time.monotonic = monotonic  # override the fixture stub

    with pytest.raises(MobileSkillError) as excinfo:
        onboard.onboard(retries=0, timeout_s=1)
    assert excinfo.value.code == "device_unauthorized"


def test_onboard_no_device(scripted_onboard) -> None:
    scripted_onboard["listings"] = [[]]
    with pytest.raises(MobileSkillError) as excinfo:
        onboard.onboard(retries=0, timeout_s=0)
    assert excinfo.value.code == "device_not_found"


def test_onboard_ambiguous(scripted_onboard) -> None:
    scripted_onboard["listings"] = [
        [
            {"serial": "A", "state": "device"},
            {"serial": "B", "state": "device"},
        ]
    ]
    with pytest.raises(MobileSkillError) as excinfo:
        onboard.onboard()
    assert excinfo.value.code == "device_ambiguous"


@pytest.mark.parametrize("kwargs, code", [
    ({"timeout_s": -1}, "invalid_timeout"),
    ({"retries": -1}, "invalid_retries"),
    ({"retries": 99}, "invalid_retries"),
])
def test_onboard_input_validation(kwargs: dict, code: str) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        onboard.onboard(**kwargs)
    assert excinfo.value.code == code
