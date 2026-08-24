"""request-help / pause / resume flow through the CLI dispatcher."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from mobile_skill import android, cli
from mobile_skill.errors import MobileSkillError


def _run(*argv: str):
    parser = cli.build_parser()
    args = parser.parse_args(cli._hoist_json_flag(list(argv)))
    return cli._dispatch(args)


@pytest.fixture
def cli_env(msk_home, fake_adb, monkeypatch):
    fake_adb.when("devices", "-l", returns="List of devices attached\nemu-1 device\n")
    fake_adb.when("shell", "dumpsys", "power", returns="mWakefulness=Awake\n")
    fake_adb.when("shell", "dumpsys", "window", returns="\n")

    def capture(serial, output_path=None):
        image = Image.new("RGB", (200, 400), color=(0, 0, 0))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
        return data, (200, 400)

    monkeypatch.setattr(android, "capture", capture)
    return fake_adb


def test_request_help_pauses_and_resume_resolves(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    _run("observe", "--session", session_id)

    help_result = _run(
        "request-help",
        "--session", session_id,
        "--reason", "login_required",
        "--message", "please log in",
    )
    assert help_result["status"] == "waiting_for_user"
    assert help_result["help_request"]["status"] == "waiting_for_user"
    assert help_result["next_action"].startswith("after the user")

    # Cannot observe while paused
    with pytest.raises(MobileSkillError) as excinfo:
        _run("observe", "--session", session_id)
    assert excinfo.value.code == "session_paused"

    resumed = _run("session", "resume", session_id)
    assert resumed["session"]["state"] == "active"
    assert resumed["session"]["help_request"]["status"] == "resolved"

    # After resume, first tap must fail (no fresh observation)
    with pytest.raises(MobileSkillError):
        _run(
            "tap", "500", "500",
            "--session", session_id, "--observation", "obs-anything",
        )
