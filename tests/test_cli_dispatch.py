"""CLI dispatch integration — walk the observation/action loop end-to-end.

Uses cli.build_parser + cli._dispatch, backed by FakeAdb for ADB and a
canned android.capture for screenshots.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from mobile_skill import android, cli, deeplinks
from mobile_skill.errors import MobileSkillError


def _run(*argv: str):
    parser = cli.build_parser()
    args = parser.parse_args(cli._hoist_json_flag(list(argv)))
    return cli._dispatch(args)


@pytest.fixture
def cli_env(msk_home, fake_adb, monkeypatch):
    """One device, unlocked, capture returns a small PNG."""
    fake_adb.when(
        "devices", "-l", returns="List of devices attached\nemu-1 device\n"
    )
    fake_adb.when("shell", "dumpsys", "power", returns="mWakefulness=Awake\n")
    fake_adb.when("shell", "dumpsys", "window", returns="Idle\n")

    def capture(serial, output_path=None):
        image = Image.new("RGB", (1080, 2400), color=(1, 2, 3))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data)
        return data, (1080, 2400)

    monkeypatch.setattr(android, "capture", capture)
    return fake_adb


def test_session_lifecycle(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    assert started["session"]["state"] == "active"
    listed = _run("session", "list")
    assert any(s["id"] == session_id for s in listed["sessions"])
    stopped = _run("session", "stop", session_id)
    assert stopped["session"]["state"] == "stopped"


def test_observe_returns_openable_image(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    assert observed["ok"] is True
    assert Path(observed["path"]).is_file()
    assert observed["coordinate_scale"] == 999
    assert observed["width"] == 1080 and observed["height"] == 2400


def test_tap_with_stale_observation(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    _run("observe", "--session", session_id)
    with pytest.raises(MobileSkillError) as excinfo:
        _run("tap", "500", "500", "--session", session_id, "--observation", "obs-wrong")
    assert excinfo.value.code == "stale_observation"


def test_tap_invalidates_observation(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    obs_id = observed["observation_id"]
    result = _run("tap", "500", "500", "--session", session_id, "--observation", obs_id)
    assert result["ok"] is True
    with pytest.raises(MobileSkillError) as excinfo:
        _run("tap", "600", "600", "--session", session_id, "--observation", obs_id)
    assert excinfo.value.code == "stale_observation"


def test_tap_with_observe_after(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    obs_id = observed["observation_id"]
    result = _run(
        "tap", "500", "500",
        "--session", session_id, "--observation", obs_id,
        "--observe-after", "--settle-ms", "0",
    )
    assert "next_observation" in result
    assert result["next_observation"]["observation_id"] != obs_id
    assert Path(result["next_observation"]["path"]).is_file()
    assert result["settle"]["source"] == "override"


def test_settle_without_observe_after_rejected(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    obs_id = observed["observation_id"]
    with pytest.raises(MobileSkillError) as excinfo:
        _run(
            "tap", "500", "500",
            "--session", session_id, "--observation", obs_id, "--settle-ms", "100",
        )
    assert excinfo.value.code == "settle_requires_observe_after"


def test_type_empty_rejected(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    with pytest.raises(MobileSkillError) as excinfo:
        _run("type", "", "--session", session_id)
    assert excinfo.value.code == "empty_text"


def test_wait_does_not_require_unlock(cli_env, monkeypatch) -> None:
    # Even if the phone is locked, `wait` is allowed to proceed
    started = _run("session", "start")
    session_id = started["session"]["id"]
    fake = cli_env
    # replace power output to indicate locked
    fake._rules = [
        rule for rule in fake._rules
        if rule[0] != ("shell", "dumpsys", "power")
    ]
    fake.when("shell", "dumpsys", "power", returns="Asleep\n")
    result = _run("wait", "--duration", "10", "--session", session_id)
    assert result["action"] == "wait"


def test_swipe_out_of_range_normalized_coord(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    obs_id = observed["observation_id"]
    with pytest.raises(MobileSkillError) as excinfo:
        _run(
            "swipe", "-1", "0", "500", "500",
            "--session", session_id, "--observation", obs_id,
        )
    assert excinfo.value.code == "invalid_coordinate"


def test_app_open_url_deeplink_outcome(cli_env, monkeypatch) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    cli_env.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="tv.danmaku.bili/.IntentHandler\n",
    )

    def fake_finalize(serial, url, expected_activity):
        return {
            "actual_activity": "tv.danmaku.bili/.M",
            "outcome": "verified",
            "template": "bilibili://search?keyword={keyword}",
            "recorded": True,
        }

    monkeypatch.setattr(deeplinks, "finalize_open_url", fake_finalize)
    result = _run(
        "app", "open-url", "bilibili://search?keyword=Minecraft",
        "--session", session_id, "--observe-after", "--settle-ms", "0",
    )
    assert result["deeplink_outcome"]["outcome"] == "verified"
    assert result["action"] == "app-open-url"


def test_home_action(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    result = _run("home", "--session", session_id)
    assert result["action"] == "home"


def test_press_action_records_key(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    result = _run("press", "enter", "--session", session_id)
    assert result["key"] == "enter"


def test_devices_lists_from_adb(cli_env) -> None:
    result = _run("devices")
    assert result["devices"] == [{"serial": "emu-1", "state": "device"}]


def test_version() -> None:
    result = _run("version")
    assert result["name"] == "mobile-skill"
    assert "version" in result


def test_install_list(monkeypatch, tmp_path) -> None:
    # Redirect HOME so we don't touch the real user's dot-directories.
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _run("install", "--list")
    names = {h["name"] for h in result["harnesses"]}
    assert "claude-code" in names and "codex" in names


def test_apps_list_user_visible(cli_env) -> None:
    cli_env.when(
        "shell", "cmd", "package", "query-activities",
        returns="  com.a/.Main\n  com.b/.Main\n",
    )
    result = _run("apps", "list", "--user-visible")
    assert result["user_visible"] is True
    assert result["apps"] == ["com.a", "com.b"]


def test_app_registry_uses_curated(cli_env) -> None:
    result = _run("app", "registry", "tv.danmaku.bili")
    assert result["apps"][0]["package"] == "tv.danmaku.bili"
    assert result["apps"][0]["entries"]


def test_app_registry_forget_and_reset(cli_env) -> None:
    # forget on empty is a no-op
    _run("app", "registry", "--forget", "custom://x")
    # reset on empty succeeds
    result = _run("app", "registry", "--reset-learned")
    assert result["cleared_apps"] == 0


def test_app_registry_forget_and_reset_are_exclusive(cli_env) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        _run("app", "registry", "--forget", "u://x", "--reset-learned")
    assert excinfo.value.code == "conflicting_flags"


def test_cleanup_dry_run(cli_env) -> None:
    result = _run("cleanup", "--dry-run")
    assert result["cleanup"]["dry_run"] is True
