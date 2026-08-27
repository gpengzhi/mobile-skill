"""mobile-skill command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import android, deeplinks, diagnostics, ime_setup, installer, observations, onboard, sequence, state
from . import __version__
from .errors import MobileSkillError


# Post-action settling delays, deliberately conservative: measured settle
# times on a real device run well past snappy-looking values (a swipe that
# opens a page settles at 635-1035ms, a tap that opens a subpage at ~674ms),
# and a mid-animation capture leads to taps on moved targets.
DEFAULT_SETTLE_MS = {
    "tap": 800,
    "double-tap": 800,
    "long-press": 800,
    "swipe": 1200,
    "wait": 0,
    "type": 400,
    "press": 900,
    "home": 900,
    "back": 900,
    "app-switcher": 900,
    "app": 1500,
}
# Per-terminal-action settle defaults for `sequence`. Values mirror
# DEFAULT_SETTLE_MS so a sequence whose last step is `swipe` settles like a
# standalone `swipe`; `app-open`/`open-url` map onto the `app` command's
# settle. Kept as a separate mapping because the sequence action namespace
# is not identical to the CLI-command namespace (no shared `app` key).
SEQUENCE_TERMINAL_SETTLE_MS = {
    "tap": DEFAULT_SETTLE_MS["tap"],
    "double-tap": DEFAULT_SETTLE_MS["double-tap"],
    "long-press": DEFAULT_SETTLE_MS["long-press"],
    "swipe": DEFAULT_SETTLE_MS["swipe"],
    "wait": DEFAULT_SETTLE_MS["wait"],
    "type": DEFAULT_SETTLE_MS["type"],
    "press": DEFAULT_SETTLE_MS["press"],
    "home": DEFAULT_SETTLE_MS["home"],
    "back": DEFAULT_SETTLE_MS["back"],
    "app-switcher": DEFAULT_SETTLE_MS["app-switcher"],
    "app-open": DEFAULT_SETTLE_MS["app"],
    "open-url": DEFAULT_SETTLE_MS["app"],
}
MAX_SETTLE_MS = 60_000
NORMALIZED_COORDINATE_MAX = observations.NORMALIZED_COORDINATE_MAX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msk", description="Control a real Android phone")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("version")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--agent")
    commands.add_parser("devices")

    onboard_command = commands.add_parser("onboard")
    onboard_command.add_argument("--device")
    onboard_command.add_argument("--timeout", type=int, default=60, dest="timeout_s")
    onboard_command.add_argument("--retries", type=int, default=1)

    setup_ime_command = commands.add_parser("setup-ime")
    setup_ime_command.add_argument("--device")
    setup_ime_command.add_argument(
        "--apk",
        help="install a local app-uiautomator.apk instead of downloading the pinned release",
    )

    install = commands.add_parser("install")
    install.add_argument("agent", nargs="?")
    install.add_argument(
        "--list",
        action="store_true",
        dest="list_harnesses",
        help="print the registered harness table and exit",
    )
    install.add_argument(
        "--home",
        help="install to <home>/skills/mobile-skill/ for a harness not in the table",
    )
    install.add_argument(
        "--name",
        help="label to record for a --home install (defaults to the home directory name)",
    )

    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--older-than-days", type=int)
    cleanup.add_argument("--dry-run", action="store_true")

    session = commands.add_parser("session")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    start = session_commands.add_parser("start")
    start.add_argument("--device")
    session_commands.add_parser("list")
    for name in ("status", "stop", "pause", "resume"):
        command = session_commands.add_parser(name)
        command.add_argument("session_id")

    request_help = commands.add_parser("request-help")
    request_help.add_argument("--session", required=True)
    request_help.add_argument("--reason", required=True)
    request_help.add_argument("--message", required=True)

    _add_capture_options(commands.add_parser("observe"))

    tap = commands.add_parser("tap")
    _add_observation_options(tap)
    tap.add_argument("x", type=int)
    tap.add_argument("y", type=int)
    _add_post_action_options(tap)

    double_tap = commands.add_parser("double-tap")
    _add_observation_options(double_tap)
    double_tap.add_argument("x", type=int)
    double_tap.add_argument("y", type=int)
    double_tap.add_argument("--interval", type=int, default=100, dest="interval_ms")
    _add_post_action_options(double_tap)

    long_press = commands.add_parser("long-press")
    _add_observation_options(long_press)
    long_press.add_argument("x", type=int)
    long_press.add_argument("y", type=int)
    long_press.add_argument("--duration", type=int, default=800, dest="duration_ms")
    _add_post_action_options(long_press)

    swipe = commands.add_parser("swipe")
    _add_observation_options(swipe)
    swipe.add_argument("x1", type=int)
    swipe.add_argument("y1", type=int)
    swipe.add_argument("x2", type=int)
    swipe.add_argument("y2", type=int)
    swipe.add_argument("--duration", type=int, default=350, dest="duration_ms")
    _add_post_action_options(swipe)

    wait = commands.add_parser("wait")
    wait.add_argument("--duration", type=int, default=500, dest="duration_ms")
    _add_session_option(wait)
    _add_post_action_options(wait)

    type_command = commands.add_parser("type")
    type_command.add_argument("text")
    _add_session_option(type_command)
    _add_post_action_options(type_command)

    press = commands.add_parser("press")
    press.add_argument("key")
    _add_session_option(press)
    _add_post_action_options(press)

    for name in ("home", "back", "app-switcher"):
        command = commands.add_parser(name)
        _add_session_option(command)
        _add_post_action_options(command)

    app = commands.add_parser("app")
    app_commands = app.add_subparsers(dest="app_command", required=True)
    open_app = app_commands.add_parser("open")
    open_app.add_argument("package")
    _add_session_option(open_app)
    _add_post_action_options(open_app)

    open_url = app_commands.add_parser("open-url")
    open_url.add_argument("url")
    _add_session_option(open_url)
    _add_post_action_options(open_url)

    schemes = app_commands.add_parser("schemes")
    schemes.add_argument("package")
    schemes.add_argument("--device")

    registry = app_commands.add_parser("registry")
    registry.add_argument("package", nargs="?")
    registry.add_argument(
        "--forget",
        metavar="URL",
        help="remove a specific learned URL template from the learned registry",
    )
    registry.add_argument(
        "--reset-learned",
        action="store_true",
        dest="reset_learned",
        help="wipe all learned entries (curated registry is untouched)",
    )

    apps = commands.add_parser("apps")
    apps_commands = apps.add_subparsers(dest="apps_command", required=True)
    list_apps = apps_commands.add_parser("list")
    list_apps.add_argument("--user-visible", action="store_true", dest="user_visible")
    list_apps.add_argument("--device")

    action_sequence = commands.add_parser(
        "sequence", help="execute a bounded sequence of device actions"
    )
    _add_observation_options(action_sequence)
    actions = action_sequence.add_mutually_exclusive_group(required=True)
    actions.add_argument("--actions", help="JSON array of action objects")
    actions.add_argument("--actions-file", help="read the JSON action array from a file")
    _add_post_action_options(action_sequence)

    return parser


def _add_session_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session", required=True)


def _add_capture_options(parser: argparse.ArgumentParser) -> None:
    _add_session_option(parser)
    parser.add_argument("--full", action="store_true", help="return the original PNG")
    parser.add_argument(
        "--model-width", type=int, default=observations.DEFAULT_MODEL_WIDTH
    )


def _add_observation_options(parser: argparse.ArgumentParser) -> None:
    _add_session_option(parser)
    parser.add_argument("--observation", required=True)


def _add_post_action_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--observe-after",
        action="store_true",
        help="wait briefly and capture the next observation after the action",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        help="override the default post-action wait in milliseconds",
    )


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, str):
        print(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                print(f"{key}: {json.dumps(item, ensure_ascii=False)}")
            else:
                print(f"{key}: {item}")
        return
    print(value)


def _ok(**value: Any) -> dict[str, Any]:
    return {"ok": True, **value}


def _active_session(args: argparse.Namespace) -> dict[str, Any]:
    session = state.get_session(args.session)
    if session["state"] != "active":
        raise MobileSkillError(
            "session_paused" if session["state"] == "paused" else "invalid_session_state",
            f"session {args.session} is {session['state']}",
        )
    return session


def _driver(
    args: argparse.Namespace, *, require_unlocked: bool = True
) -> tuple[dict[str, Any], str]:
    session = _active_session(args)
    serial = android.require_device(session["device_id"])
    if require_unlocked:
        observations.ensure_session_unlocked(session, serial)
    state.update_session(session["id"], last_activity_at=time.time())
    return session, serial


def _check_observation(session: dict[str, Any], observation_id: str) -> dict[str, Any]:
    current = session.get("last_observation")
    if current is None or current["id"] != observation_id:
        details: dict[str, Any] = {"observation_id": observation_id}
        if current is not None:
            details["current_observation_id"] = current["id"]
            hint = f"the current observation is {current['id']}; use it or run `msk observe --session {session['id']}` for a fresh one"
        else:
            hint = f"run `msk observe --session {session['id']}`"
        raise MobileSkillError(
            "stale_observation",
            f"observation {observation_id} is not current",
            hint,
            details,
        )
    return current


def _invalidate_observation(session_id: str) -> None:
    state.update_session(session_id, last_observation=None)


def _raise_action_error(error: MobileSkillError, action: dict[str, Any]) -> None:
    if not error.details.get("action_may_have_applied"):
        raise error
    raise MobileSkillError(
        "action_result_unknown",
        "the device command failed after dispatch; the action may have applied",
        "observe the screen before taking another action; do not retry blindly",
        {
            "action_may_have_applied": True,
            "action": action,
            "cause": error.code,
        },
    ) from error


def _execute_device_action(
    session_id: str,
    action: dict[str, Any],
    execute: Callable[[Callable[[], None]], Any],
) -> Any:
    observation_invalidated = False

    def before_dispatch() -> None:
        nonlocal observation_invalidated
        if observation_invalidated:
            return
        _invalidate_observation(session_id)
        observation_invalidated = True

    try:
        outcome = execute(before_dispatch)
    except MobileSkillError as error:
        _raise_action_error(error, action)
    if not observation_invalidated:
        _invalidate_observation(session_id)
    return outcome


def _settle_request(
    args: argparse.Namespace, *, default_ms: int | None = None
) -> tuple[int, str] | None:
    observe_after = getattr(args, "observe_after", False)
    settle_ms = getattr(args, "settle_ms", None)
    if settle_ms is not None and not observe_after:
        raise MobileSkillError(
            "settle_requires_observe_after",
            "--settle-ms requires --observe-after",
        )
    if not observe_after:
        return None
    if settle_ms is None:
        requested_ms = default_ms if default_ms is not None else DEFAULT_SETTLE_MS[args.command]
    else:
        requested_ms = settle_ms
    if not 0 <= requested_ms <= MAX_SETTLE_MS:
        raise MobileSkillError(
            "invalid_settle_duration",
            f"settle duration must be between 0 and {MAX_SETTLE_MS} milliseconds",
        )
    return requested_ms, "default" if settle_ms is None else "override"


def _wait_for_settle(request: tuple[int, str]) -> dict[str, Any]:
    requested_ms, source = request
    started = time.perf_counter()
    if requested_ms:
        android.wait(requested_ms)
    actual_ms = round((time.perf_counter() - started) * 1000)
    return {
        "source": source,
        "requested_ms": requested_ms,
        "actual_ms": actual_ms,
    }


def _complete_action(
    session: dict[str, Any],
    serial: str,
    action: dict[str, Any],
    *,
    request: tuple[int, str] | None,
    observation_id: str | None = None,
) -> dict[str, Any]:
    result = _ok(session_id=session["id"], device_id=serial, **action)
    if observation_id is not None:
        result["observation_id"] = observation_id

    if request is None:
        return result

    settle = _wait_for_settle(request)
    result["settle"] = settle
    try:
        next_observation = observations.capture(session["id"], serial=serial)
    except (MobileSkillError, OSError) as error:
        raise MobileSkillError(
            "post_action_observe_failed",
            f"action succeeded but the post-action observation failed: {error}",
            f"run `msk observe --session {session['id']}`; do not repeat the action",
            {
                "action_applied": True,
                "action": action,
                "settle": settle,
            },
        ) from error
    result["next_observation"] = {
        key: value for key, value in next_observation.items() if key != "ok"
    }
    if action.get("action") == "app-open-url":
        outcome_info = deeplinks.finalize_open_url(
            serial=serial,
            url=action.get("url", ""),
            expected_activity=action.get("resolved_activity"),
        )
        result["deeplink_outcome"] = outcome_info
    return result


def _request_help(args: argparse.Namespace) -> dict[str, Any]:
    with state.command_lock(args.session):
        session = state.request_help(args.session, args.reason, args.message)
    return _ok(
        session_id=session["id"],
        device_id=session["device_id"],
        status="waiting_for_user",
        help_request=session["help_request"],
        next_action=f"after the user finishes, run `msk session resume {session['id']}`",
    )


def _observe(args: argparse.Namespace) -> dict[str, Any]:
    with state.command_lock(args.session):
        return observations.capture(args.session, full=args.full, model_width=args.model_width)


def _sequence_actions(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.actions is not None:
        raw = args.actions
    else:
        try:
            raw = Path(args.actions_file).read_text(encoding="utf-8")
        except OSError as error:
            raise MobileSkillError(
                "sequence_file_unreadable",
                f"cannot read sequence actions file {args.actions_file}: {error}",
            ) from error
    return sequence.parse_actions(raw)


def _execute_sequence_step(
    action: dict[str, Any],
    serial: str,
    observation: dict[str, Any],
    before_dispatch: Callable[[], None],
) -> Any:
    action_type = action["type"]
    size = _device_size(observation)
    if action_type == "tap":
        x, y = _device_point(observation, action["x"], action["y"])
        return android.tap(serial, x, y, size, before_dispatch=before_dispatch)
    if action_type == "double-tap":
        x, y = _device_point(observation, action["x"], action["y"])
        return android.double_tap(
            serial,
            x,
            y,
            action["interval_ms"],
            size,
            before_dispatch=before_dispatch,
        )
    if action_type == "long-press":
        x, y = _device_point(observation, action["x"], action["y"])
        return android.long_press(
            serial,
            x,
            y,
            action["duration_ms"],
            size,
            before_dispatch=before_dispatch,
        )
    if action_type == "swipe":
        x1, y1 = _device_point(observation, action["x1"], action["y1"])
        x2, y2 = _device_point(observation, action["x2"], action["y2"])
        return android.swipe(
            serial,
            x1,
            y1,
            x2,
            y2,
            action["duration_ms"],
            size,
            before_dispatch=before_dispatch,
        )
    if action_type == "wait":
        before_dispatch()
        return android.wait(action["duration_ms"])
    if action_type == "type":
        return android.type_text(serial, action["text"], before_dispatch=before_dispatch)
    if action_type == "press":
        return android.press(serial, action["key"], before_dispatch=before_dispatch)
    if action_type == "home":
        return android.home(serial, before_dispatch=before_dispatch)
    if action_type == "back":
        return android.back(serial, before_dispatch=before_dispatch)
    if action_type == "app-switcher":
        return android.app_switcher(serial, before_dispatch=before_dispatch)
    if action_type == "app-open":
        return android.launch_app(
            serial, action["package"], before_dispatch=before_dispatch
        )
    if action_type == "open-url":
        return deeplinks.open_url(
            serial, action["url"], before_dispatch=before_dispatch
        )
    raise MobileSkillError("invalid_sequence_action", f"unknown action: {action_type}")


def _execute_sequence(
    session: dict[str, Any],
    serial: str,
    observation: dict[str, Any],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, Any]:
    completed: list[dict[str, Any]] = []
    current_action: dict[str, Any] | None = None
    current_outcome: Any = None
    observation_invalidated = False

    def before_dispatch() -> None:
        nonlocal observation_invalidated
        if observation_invalidated:
            return
        _invalidate_observation(session["id"])
        observation_invalidated = True

    try:
        for index, action in enumerate(actions):
            current_action = action
            current_outcome = _execute_sequence_step(
                action, serial, observation, before_dispatch
            )
            summary = sequence.action_summary(action)
            if action["type"] == "type":
                summary["method"] = current_outcome
            elif action["type"] == "open-url":
                summary.update(current_outcome)
            completed.append(
                {
                    "index": index,
                    "action": summary,
                    "status": "dispatched",
                }
            )
    except MobileSkillError as error:
        failed_index = len(completed)
        failed_action = sequence.action_summary(current_action or actions[failed_index])
        details = {
            "completed": completed,
            "failed": {
                "index": failed_index,
                "action": failed_action,
                "status": "unknown"
                if error.details.get("action_may_have_applied")
                else "failed",
            },
            "not_attempted": list(range(failed_index + 1, len(actions))),
            "cause": error.code,
        }
        if error.details.get("action_may_have_applied"):
            details["failed"]["action_may_have_applied"] = True
            raise MobileSkillError(
                "action_result_unknown",
                "the action sequence stopped after an uncertain device command",
                "observe the screen before taking another action; do not retry blindly",
                details,
            ) from error
        raise MobileSkillError(
            "sequence_failed",
            f"the action sequence stopped at action {failed_index}",
            "observe the screen before continuing",
            details,
        ) from error

    return completed, current_action, current_outcome


def _complete_sequence(
    session: dict[str, Any],
    serial: str,
    observation_id: str,
    completed: list[dict[str, Any]],
    last_action: dict[str, Any] | None,
    last_outcome: Any,
    *,
    request: tuple[int, str] | None,
) -> dict[str, Any]:
    result = _ok(
        type="action_sequence",
        session_id=session["id"],
        device_id=serial,
        observation_id=observation_id,
        actions=completed,
    )
    if request is None:
        return result

    settle = _wait_for_settle(request)
    result["settle"] = settle
    try:
        next_observation = observations.capture(session["id"], serial=serial)
    except (MobileSkillError, OSError) as error:
        raise MobileSkillError(
            "post_action_observe_failed",
            f"action sequence succeeded but the post-action observation failed: {error}",
            f"run `msk observe --session {session['id']}`; do not repeat the sequence",
            {
                "action_applied": True,
                "actions": completed,
                "settle": settle,
            },
        ) from error
    result["next_observation"] = {
        key: value for key, value in next_observation.items() if key != "ok"
    }
    if last_action and last_action["type"] == "open-url":
        resolved_activity = (
            last_outcome.get("resolved_activity")
            if isinstance(last_outcome, dict)
            else None
        )
        result["deeplink_outcome"] = deeplinks.finalize_open_url(
            serial=serial,
            url=last_action["url"],
            expected_activity=resolved_activity,
        )
    return result


def _run_sequence(args: argparse.Namespace) -> dict[str, Any]:
    actions = _sequence_actions(args)
    terminal_type = actions[-1]["type"]
    request = _settle_request(
        args, default_ms=SEQUENCE_TERMINAL_SETTLE_MS[terminal_type]
    )
    with state.command_lock(args.session):
        session, serial = _driver(args)
        observation = _check_observation(session, args.observation)
        completed, last_action, last_outcome = _execute_sequence(
            session, serial, observation, actions
        )
        return _complete_sequence(
            session,
            serial,
            args.observation,
            completed,
            last_action,
            last_outcome,
            request=request,
        )


def _device_size(observation: dict[str, Any]) -> tuple[int, int]:
    return observation["width"], observation["height"]


def _device_point(observation: dict[str, Any], x: int, y: int) -> tuple[int, int]:
    if not 0 <= x <= NORMALIZED_COORDINATE_MAX:
        raise MobileSkillError(
            "invalid_coordinate",
            f"x coordinate must be between 0 and {NORMALIZED_COORDINATE_MAX}",
        )
    if not 0 <= y <= NORMALIZED_COORDINATE_MAX:
        raise MobileSkillError(
            "invalid_coordinate",
            f"y coordinate must be between 0 and {NORMALIZED_COORDINATE_MAX}",
        )
    device_width, device_height = _device_size(observation)
    return (
        round(x * (device_width - 1) / NORMALIZED_COORDINATE_MAX),
        round(y * (device_height - 1) / NORMALIZED_COORDINATE_MAX),
    )


def _run_action(args: argparse.Namespace) -> dict[str, Any]:
    request = _settle_request(args)
    with state.command_lock(args.session):
        return _run_action_locked(args, request)


def _run_action_locked(
    args: argparse.Namespace, request: tuple[int, str] | None
) -> dict[str, Any]:
    session, serial = _driver(args)
    observation = _check_observation(session, args.observation)
    size = _device_size(observation)
    if args.command == "tap":
        x, y = _device_point(observation, args.x, args.y)
        action = {"action": "tap", "x": args.x, "y": args.y}
        execute = lambda before: android.tap(
            serial, x, y, size, before_dispatch=before
        )
    elif args.command == "double-tap":
        x, y = _device_point(observation, args.x, args.y)
        action = {
            "action": "double-tap",
            "x": args.x,
            "y": args.y,
            "interval_ms": args.interval_ms,
        }
        execute = lambda before: android.double_tap(
            serial, x, y, args.interval_ms, size, before_dispatch=before
        )
    elif args.command == "long-press":
        x, y = _device_point(observation, args.x, args.y)
        action = {
            "action": "long-press",
            "x": args.x,
            "y": args.y,
            "duration_ms": args.duration_ms,
        }
        execute = lambda before: android.long_press(
            serial, x, y, args.duration_ms, size, before_dispatch=before
        )
    else:
        x1, y1 = _device_point(observation, args.x1, args.y1)
        x2, y2 = _device_point(observation, args.x2, args.y2)
        action = {
            "action": "swipe",
            "x1": args.x1,
            "y1": args.y1,
            "x2": args.x2,
            "y2": args.y2,
            "duration_ms": args.duration_ms,
        }
        execute = lambda before: android.swipe(
            serial, x1, y1, x2, y2, args.duration_ms, size,
            before_dispatch=before,
        )
    _execute_device_action(session["id"], action, execute)
    return _complete_action(
        session,
        serial,
        action,
        request=request,
        observation_id=args.observation,
    )


def _simple_action(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "type" and not args.text:
        raise MobileSkillError(
            "empty_text",
            "type text must not be empty",
            "pass a non-empty string, or skip the call",
        )
    request = _settle_request(args)
    with state.command_lock(args.session):
        return _simple_action_locked(args, request)


def _simple_action_locked(
    args: argparse.Namespace, request: tuple[int, str] | None
) -> dict[str, Any]:
    session, serial = _driver(args, require_unlocked=args.command != "wait")
    if args.command == "wait":
        android.wait(args.duration_ms)
        action = {"action": "wait", "duration_ms": args.duration_ms}
        _invalidate_observation(session["id"])
        return _complete_action(session, serial, action, request=request)
    if args.command == "type":
        action = {"action": "type", "text_length": len(args.text)}
        execute = lambda before: android.type_text(
            serial, args.text, before_dispatch=before
        )
    elif args.command == "press":
        action = {"action": "press", "key": args.key}
        execute = lambda before: android.press(
            serial, args.key, before_dispatch=before
        )
    elif args.command == "home":
        action = {"action": "home"}
        execute = lambda before: android.home(serial, before_dispatch=before)
    elif args.command == "back":
        action = {"action": "back"}
        execute = lambda before: android.back(serial, before_dispatch=before)
    elif args.command == "app-switcher":
        action = {"action": "app-switcher"}
        execute = lambda before: android.app_switcher(
            serial, before_dispatch=before
        )
    elif args.command == "app" and args.app_command == "open":
        action = {"action": "app-open", "package": args.package}
        execute = lambda before: android.launch_app(
            serial, args.package, before_dispatch=before
        )
    elif args.command == "app" and args.app_command == "open-url":
        action = {"action": "app-open-url"}
        execute = lambda before: deeplinks.open_url(
            serial, args.url, before_dispatch=before
        )
    else:
        raise MobileSkillError("unknown_command", f"unknown action: {args.command}")

    outcome = _execute_device_action(session["id"], action, execute)

    if args.command == "type":
        action["method"] = outcome
    elif args.command == "app" and args.app_command == "open":
        action["package"] = outcome
    elif args.command == "app" and args.app_command == "open-url":
        action.update(outcome)
    return _complete_action(session, serial, action, request=request)


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "version":
        return _ok(name="mobile-skill", version=__version__)
    if args.command == "doctor":
        return _ok(**diagnostics.doctor(args.agent))
    if args.command == "devices":
        return _ok(devices=android.list_devices())
    if args.command == "onboard":
        return _ok(
            **onboard.onboard(
                device=args.device, timeout_s=args.timeout_s, retries=args.retries
            )
        )
    if args.command == "setup-ime":
        return _ok(**ime_setup.setup_ime(args.device, apk_path=args.apk))
    if args.command == "install":
        if args.list_harnesses:
            return _ok(harnesses=installer.registered_harnesses())
        if args.home:
            return _ok(**installer.install_to_home(Path(args.home), args.name))
        if not args.agent:
            raise MobileSkillError(
                "install_target_missing",
                "specify a harness name, --home <dir>, or --list",
                "run `msk install --list` to see registered harnesses",
            )
        return _ok(**installer.install(args.agent))
    if args.command == "cleanup":
        return _ok(
            cleanup=state.cleanup(
                older_than_days=args.older_than_days,
                dry_run=args.dry_run,
            )
        )
    if args.command == "request-help":
        return _request_help(args)
    if args.command == "session":
        if args.session_command == "start":
            serial = android.require_device(args.device)
            cleanup_result = state.cleanup()
            return _ok(session=state.create_session(serial), cleanup=cleanup_result)
        if args.session_command == "list":
            return _ok(sessions=state.list_sessions())
        if args.session_command == "status":
            return _ok(session=state.get_session(args.session_id))
        if args.session_command == "stop":
            return _ok(session=state.stop_session(args.session_id))
        if args.session_command == "pause":
            return _ok(session=state.pause_session(args.session_id))
        if args.session_command == "resume":
            return _ok(session=state.resume_session(args.session_id))
    if args.command == "apps":
        if args.apps_command == "list":
            serial = android.require_device(args.device)
            return _ok(
                device_id=serial,
                user_visible=args.user_visible,
                apps=android.list_packages(serial, user_visible=args.user_visible),
            )
    if args.command == "app" and args.app_command == "schemes":
        serial = android.require_device(args.device)
        return _ok(**deeplinks.parse_schemes(serial, args.package))
    if args.command == "app" and args.app_command == "registry":
        forget = getattr(args, "forget", None)
        reset_learned = getattr(args, "reset_learned", False)
        if forget and reset_learned:
            raise MobileSkillError(
                "conflicting_flags",
                "--forget and --reset-learned are mutually exclusive",
            )
        if reset_learned:
            return _ok(**deeplinks.reset_learned())
        if forget:
            return _ok(**deeplinks.forget_learned_url(forget, package=args.package))
        return _ok(apps=deeplinks.merged_registry(args.package))
    if args.command == "observe":
        return _observe(args)
    if args.command == "sequence":
        return _run_sequence(args)
    if args.command in ("tap", "double-tap", "long-press", "swipe"):
        return _run_action(args)
    return _simple_action(args)


def _hoist_json_flag(argv: list[str]) -> list[str]:
    """Move any --json occurrence to the front so subcommands accept it too."""
    if "--json" not in argv:
        return argv
    remainder = [token for token in argv if token != "--json"]
    return ["--json", *remainder]


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(_hoist_json_flag(sys.argv[1:]))
    try:
        _emit(_dispatch(args), args.json)
    except MobileSkillError as error:
        detail = {"code": error.code, "message": str(error)}
        if error.hint:
            detail["hint"] = error.hint
        detail.update(error.details)
        payload = {"ok": False, "error": detail}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"msk: {error}", file=sys.stderr)
            if error.hint:
                print(f"hint: {error.hint}", file=sys.stderr)
        raise SystemExit(1) from error
    except OSError as error:
        payload = {"ok": False, "error": {"code": "internal_error", "message": str(error)}}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        else:
            print(f"msk: {error}", file=sys.stderr)
        raise SystemExit(1) from error
