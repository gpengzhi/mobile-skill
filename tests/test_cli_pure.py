"""Pure-function tests for cli helpers — no session state, no ADB."""

from __future__ import annotations

import argparse

import pytest

from mobile_skill import cli
from mobile_skill.errors import MobileSkillError


@pytest.mark.parametrize(
    "argv, expected",
    [
        ([], []),
        (["session", "start"], ["session", "start"]),
        (["--json", "session", "start"], ["--json", "session", "start"]),
        (["session", "--json", "start"], ["--json", "session", "start"]),
        (["tap", "--json", "1", "2"], ["--json", "tap", "1", "2"]),
    ],
)
def test_hoist_json_flag(argv: list[str], expected: list[str]) -> None:
    assert cli._hoist_json_flag(argv) == expected


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_settle_request_none_when_not_observing() -> None:
    ns = _ns(command="tap", observe_after=False, settle_ms=None)
    assert cli._settle_request(ns) is None


def test_settle_ms_without_observe_after_rejected() -> None:
    ns = _ns(command="tap", observe_after=False, settle_ms=100)
    with pytest.raises(MobileSkillError) as excinfo:
        cli._settle_request(ns)
    assert excinfo.value.code == "settle_requires_observe_after"


def test_settle_request_default_source() -> None:
    ns = _ns(command="tap", observe_after=True, settle_ms=None)
    ms, source = cli._settle_request(ns)
    assert ms == cli.DEFAULT_SETTLE_MS["tap"]
    assert source == "default"


def test_settle_request_override_source() -> None:
    ns = _ns(command="swipe", observe_after=True, settle_ms=250)
    ms, source = cli._settle_request(ns)
    assert ms == 250
    assert source == "override"


@pytest.mark.parametrize("bad", [-1, cli.MAX_SETTLE_MS + 1])
def test_settle_request_range_check(bad: int) -> None:
    ns = _ns(command="tap", observe_after=True, settle_ms=bad)
    with pytest.raises(MobileSkillError) as excinfo:
        cli._settle_request(ns)
    assert excinfo.value.code == "invalid_settle_duration"


def test_default_settle_covers_every_action() -> None:
    expected = {
        "tap", "double-tap", "long-press", "swipe", "wait",
        "type", "press", "home", "back", "app-switcher", "app",
    }
    assert set(cli.DEFAULT_SETTLE_MS) == expected


def test_sequence_terminal_settle_covers_supported_action_types() -> None:
    from mobile_skill import sequence

    assert set(cli.SEQUENCE_TERMINAL_SETTLE_MS) == sequence.SUPPORTED_ACTIONS


def test_settle_request_uses_injected_default_ms() -> None:
    ns = _ns(command="sequence", observe_after=True, settle_ms=None)
    ms, source = cli._settle_request(ns, default_ms=1234)
    assert ms == 1234
    assert source == "default"


@pytest.mark.parametrize("device_size", [(1080, 2400), (1440, 3200), (720, 1600)])
def test_device_point_corners(device_size: tuple[int, int]) -> None:
    observation = {"width": device_size[0], "height": device_size[1]}
    assert cli._device_point(observation, 0, 0) == (0, 0)
    max_coord = cli.NORMALIZED_COORDINATE_MAX
    assert cli._device_point(observation, max_coord, max_coord) == (
        device_size[0] - 1,
        device_size[1] - 1,
    )


def test_device_point_midpoint_rounds() -> None:
    observation = {"width": 1000, "height": 2000}
    x, y = cli._device_point(observation, 500, 500)
    assert abs(x - 500) <= 1 and abs(y - 1000) <= 1


@pytest.mark.parametrize(
    "x, y",
    [(-1, 0), (0, -1), (cli.NORMALIZED_COORDINATE_MAX + 1, 0), (0, cli.NORMALIZED_COORDINATE_MAX + 1)],
)
def test_device_point_out_of_range(x: int, y: int) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        cli._device_point({"width": 100, "height": 200}, x, y)
    assert excinfo.value.code == "invalid_coordinate"
