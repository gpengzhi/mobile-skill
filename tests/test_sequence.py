"""Bounded action sequence validation and CLI execution."""

from __future__ import annotations

import json
import io

import pytest
from PIL import Image

from mobile_skill import android, cli, sequence, state
from mobile_skill.errors import MobileSkillError


def _run(*argv: str):
    parser = cli.build_parser()
    args = parser.parse_args(cli._hoist_json_flag(list(argv)))
    return cli._dispatch(args)


@pytest.fixture
def cli_env(msk_home, fake_adb, monkeypatch):
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


def test_parse_actions_rejects_too_many_actions() -> None:
    actions = json.dumps([{"type": "wait", "duration_ms": 0}] * 6)
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert excinfo.value.code == "sequence_too_long"


def test_parse_actions_rejects_unbounded_text() -> None:
    actions = json.dumps([{"type": "type", "text": "x" * 4097}])
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert excinfo.value.code == "invalid_sequence_action"


def test_parse_actions_rejects_action_after_press_enter() -> None:
    actions = json.dumps(
        [
            {"type": "type", "text": "hi"},
            {"type": "press", "key": "enter"},
            {"type": "tap", "x": 500, "y": 500},
        ]
    )
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert excinfo.value.code == "invalid_sequence_order"
    assert "press enter" in str(excinfo.value)


def test_parse_actions_allows_press_letter_mid_sequence() -> None:
    actions = json.dumps(
        [
            {"type": "press", "key": "a"},
            {"type": "tap", "x": 500, "y": 500},
        ]
    )
    parsed = sequence.parse_actions(actions)
    assert [action["type"] for action in parsed] == ["press", "tap"]


def test_parse_actions_ordering_error_hint_lists_terminal_actions() -> None:
    actions = json.dumps(
        [
            {"type": "back"},
            {"type": "tap", "x": 500, "y": 500},
        ]
    )
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert "swipe" in excinfo.value.hint
    assert "open-url" in excinfo.value.hint
    assert "enter" in excinfo.value.hint


def test_parse_actions_rejects_sensitive_open_url() -> None:
    actions = json.dumps(
        [{"type": "open-url", "url": "bilibili://pay/xyz?amount=100"}]
    )
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert excinfo.value.code == "deeplink_requires_human"


def test_parse_actions_allows_curated_sensitive_url() -> None:
    actions = json.dumps(
        [{"type": "open-url", "url": "alipays://platformapi/startapp?appId=10000007"}]
    )
    parsed = sequence.parse_actions(actions)
    assert parsed[0]["url"] == "alipays://platformapi/startapp?appId=10000007"


def test_parse_actions_rejects_action_after_terminal() -> None:
    actions = json.dumps(
        [
            {"type": "swipe", "x1": 500, "y1": 800, "x2": 500, "y2": 300, "duration_ms": 350},
            {"type": "tap", "x": 500, "y": 500},
        ]
    )
    with pytest.raises(MobileSkillError) as excinfo:
        sequence.parse_actions(actions)
    assert excinfo.value.code == "invalid_sequence_order"


def test_sequence_executes_actions_and_observes_after(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    actions = json.dumps(
        [
            {"type": "tap", "x": 500, "y": 500, "label": "like"},
            {"type": "tap", "x": 650, "y": 500, "label": "favorite"},
        ]
    )

    result = _run(
        "sequence",
        "--session",
        session_id,
        "--observation",
        observed["observation_id"],
        "--actions",
        actions,
        "--observe-after",
        "--settle-ms",
        "0",
    )

    assert result["ok"] is True
    assert result["type"] == "action_sequence"
    assert result["observation_id"] == observed["observation_id"]
    assert [item["status"] for item in result["actions"]] == [
        "dispatched",
        "dispatched",
    ]
    assert result["actions"][0]["action"]["label"] == "like"
    assert result["next_observation"]["observation_id"] != observed["observation_id"]
    taps = [call for call in cli_env.calls if call["args"][:3] == ("shell", "input", "tap")]
    assert [call["args"][3:5] for call in taps] == [("540", "1201"), ("702", "1201")]


def test_sequence_stops_with_partial_result_on_uncertain_action(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    calls = 0

    def fail_second_tap(args, serial, binary):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise android.AndroidError("tap failed", "adb_failed")
        return ""

    cli_env.when("shell", "input", "tap", returns=fail_second_tap)
    actions = json.dumps(
        [
            {"type": "tap", "x": 400, "y": 400},
            {"type": "tap", "x": 500, "y": 500},
            {"type": "tap", "x": 600, "y": 600},
        ]
    )

    with pytest.raises(MobileSkillError) as excinfo:
        _run(
            "sequence",
            "--session",
            session_id,
            "--observation",
            observed["observation_id"],
            "--actions",
            actions,
        )

    assert excinfo.value.code == "action_result_unknown"
    assert len(excinfo.value.details["completed"]) == 1
    assert excinfo.value.details["failed"]["index"] == 1
    assert excinfo.value.details["not_attempted"] == [2]
    assert state.get_session(session_id)["last_observation"] is None
    assert calls == 2


def test_sequence_settle_uses_terminal_action_default(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    actions = json.dumps(
        [
            {"type": "tap", "x": 500, "y": 500},
            {"type": "swipe", "x1": 500, "y1": 800, "x2": 500, "y2": 300, "duration_ms": 350},
        ]
    )

    result = _run(
        "sequence",
        "--session",
        session_id,
        "--observation",
        observed["observation_id"],
        "--actions",
        actions,
        "--observe-after",
    )

    assert result["settle"]["source"] == "default"
    assert result["settle"]["requested_ms"] == cli.SEQUENCE_TERMINAL_SETTLE_MS["swipe"]


def test_sequence_settle_falls_back_to_tap_default_when_all_taps(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    actions = json.dumps(
        [
            {"type": "tap", "x": 500, "y": 500},
            {"type": "tap", "x": 650, "y": 500},
        ]
    )

    result = _run(
        "sequence",
        "--session",
        session_id,
        "--observation",
        observed["observation_id"],
        "--actions",
        actions,
        "--observe-after",
    )

    assert result["settle"]["requested_ms"] == cli.SEQUENCE_TERMINAL_SETTLE_MS["tap"]


def test_sequence_settle_ms_override_still_wins(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)
    actions = json.dumps(
        [
            {"type": "swipe", "x1": 500, "y1": 800, "x2": 500, "y2": 300, "duration_ms": 350},
        ]
    )

    result = _run(
        "sequence",
        "--session",
        session_id,
        "--observation",
        observed["observation_id"],
        "--actions",
        actions,
        "--observe-after",
        "--settle-ms",
        "50",
    )

    assert result["settle"]["source"] == "override"
    assert result["settle"]["requested_ms"] == 50


def test_sequence_type_result_does_not_include_text(cli_env) -> None:
    started = _run("session", "start")
    session_id = started["session"]["id"]
    observed = _run("observe", "--session", session_id)

    result = _run(
        "sequence",
        "--session",
        session_id,
        "--observation",
        observed["observation_id"],
        "--actions",
        json.dumps([{"type": "type", "text": "secret text"}]),
    )

    action = result["actions"][0]["action"]
    assert action["text_length"] == len("secret text")
    assert "text" not in action
