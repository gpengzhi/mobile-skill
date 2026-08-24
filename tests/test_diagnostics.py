"""diagnostics.doctor — environment checks with mocked ADB and filesystem."""

from __future__ import annotations

import pytest

from mobile_skill import android, diagnostics, installer


@pytest.fixture
def stub_ready_device(monkeypatch, tmp_path):
    """Mock android surface so doctor reports a fully-ready device."""
    def list_devices():
        return [{"serial": "emu-1", "state": "device"}]

    def screen_size(serial):
        return (1080, 2400)

    def capture(serial, output_path=None):
        # Small valid PNG bytes
        import io
        from PIL import Image

        image = Image.new("RGB", (100, 200), color=(0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
        return data, (100, 200)

    def input_capabilities(serial):
        return {"unicode": {"status": "ready"}, "ascii": {"status": "ready"}}

    monkeypatch.setattr(android, "list_devices", list_devices)
    monkeypatch.setattr(android, "screen_size", screen_size)
    monkeypatch.setattr(android, "capture", capture)
    monkeypatch.setattr(android, "input_capabilities", input_capabilities)


def test_doctor_no_device(monkeypatch, msk_home) -> None:
    monkeypatch.setattr(android, "list_devices", lambda: [])
    report = diagnostics.doctor()
    assert report["status"] == "no-ready-device"
    assert report["checks"]["device"]["status"] == "missing"


def test_doctor_ready_device(stub_ready_device, msk_home) -> None:
    report = diagnostics.doctor()
    assert report["status"] == "ready"
    assert report["checks"]["device"]["status"] == "ready"
    assert report["checks"]["screenshot"]["status"] == "ready"


def test_doctor_multiple_devices_attention(monkeypatch, msk_home) -> None:
    monkeypatch.setattr(android, "list_devices", lambda: [
        {"serial": "A", "state": "device"},
        {"serial": "B", "state": "device"},
    ])
    report = diagnostics.doctor()
    assert report["checks"]["device"]["status"] == "attention"


def test_doctor_unknown_agent(stub_ready_device, msk_home) -> None:
    report = diagnostics.doctor(agent="no-such-harness")
    agent_checks = report["checks"]["no-such-harness"]
    assert agent_checks["harness"]["status"] == "unknown"


def test_doctor_known_agent_cli_missing(stub_ready_device, msk_home, monkeypatch) -> None:
    monkeypatch.setattr(diagnostics.shutil, "which", lambda cmd: None)
    report = diagnostics.doctor(agent="claude-code")
    agent_checks = report["checks"]["claude-code"]
    assert agent_checks["cli"]["status"] == "missing"
    assert agent_checks["vision"]["status"] == "unverified"


def test_pillow_check_present() -> None:
    result = diagnostics._pillow_check()
    assert result["status"] == "ready"


def test_pillow_check_missing(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "PIL", None)
    result = diagnostics._pillow_check()
    assert result["status"] == "missing"


def test_doctor_reports_active_sessions(stub_ready_device, msk_home) -> None:
    from mobile_skill import state
    state.create_session("emu-1")
    report = diagnostics.doctor()
    assert report["checks"]["sessions"]["status"] == "attention"
    assert report["checks"]["sessions"]["active"] == 1
