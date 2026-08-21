"""mobile-skill command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from . import android, diagnostics, installer, observations, state
from . import __version__
from .errors import MobileSkillError


DEFAULT_SETTLE_MS = {
    "tap": 300,
    "double-tap": 300,
    "long-press": 300,
    "swipe": 400,
    "wait": 0,
    "type": 150,
    "press": 600,
    "home": 600,
    "back": 600,
    "app-switcher": 600,
    "app": 1000,
}
MAX_SETTLE_MS = 60_000
NORMALIZED_COORDINATE_MAX = observations.NORMALIZED_COORDINATE_MAX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msk", description="Control a real Android phone")
    parser.add_argument("--json", action="store_true", help="print structured JSON output")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("version")

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--agent", choices=("codex", "claude-code"))
    commands.add_parser("devices")

    install = commands.add_parser("install")
    install.add_argument("agent", choices=("codex", "claude-code"))

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


def _driver(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    session = _active_session(args)
    serial = android.require_device(session["device_id"])
    return session, serial


def _check_observation(session: dict[str, Any], observation_id: str) -> dict[str, Any]:
    current = session.get("last_observation")
    if current is None or current["id"] != observation_id:
        raise MobileSkillError(
            "stale_observation",
            f"observation {observation_id} is not current",
            f"run `msk observe --session {session['id']}`",
        )
    return current


def _invalidate_observation(session_id: str) -> None:
    state.update_session(session_id, last_observation=None)


def _settle_request(args: argparse.Namespace) -> tuple[int, str] | None:
    observe_after = getattr(args, "observe_after", False)
    settle_ms = getattr(args, "settle_ms", None)
    if settle_ms is not None and not observe_after:
        raise MobileSkillError(
            "settle_requires_observe_after",
            "--settle-ms requires --observe-after",
        )
    if not observe_after:
        return None
    requested_ms = DEFAULT_SETTLE_MS[args.command] if settle_ms is None else settle_ms
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
    args: argparse.Namespace,
    session: dict[str, Any],
    serial: str,
    action: dict[str, Any],
    *,
    observation_id: str | None = None,
) -> dict[str, Any]:
    result = _ok(session_id=session["id"], device_id=serial, **action)
    if observation_id is not None:
        result["observation_id"] = observation_id

    request = _settle_request(args)
    _invalidate_observation(session["id"])
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
    return result


def _request_help(args: argparse.Namespace) -> dict[str, Any]:
    session = state.request_help(args.session, args.reason, args.message)
    return _ok(
        session_id=session["id"],
        device_id=session["device_id"],
        status="waiting_for_user",
        help_request=session["help_request"],
        next_action=f"after the user finishes, run `msk session resume {session['id']}`",
    )


def _observe(args: argparse.Namespace) -> dict[str, Any]:
    return observations.capture(args.session, full=args.full, model_width=args.model_width)


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
    _settle_request(args)
    session, serial = _driver(args)
    observation = _check_observation(session, args.observation)
    size = _device_size(observation)
    if args.command == "tap":
        x, y = _device_point(observation, args.x, args.y)
        android.tap(serial, x, y, size)
        action = {"action": "tap", "x": args.x, "y": args.y}
    elif args.command == "double-tap":
        x, y = _device_point(observation, args.x, args.y)
        android.double_tap(serial, x, y, args.interval_ms, size)
        action = {
            "action": "double-tap",
            "x": args.x,
            "y": args.y,
            "interval_ms": args.interval_ms,
        }
    elif args.command == "long-press":
        x, y = _device_point(observation, args.x, args.y)
        android.long_press(serial, x, y, args.duration_ms, size)
        action = {
            "action": "long-press",
            "x": args.x,
            "y": args.y,
            "duration_ms": args.duration_ms,
        }
    else:
        x1, y1 = _device_point(observation, args.x1, args.y1)
        x2, y2 = _device_point(observation, args.x2, args.y2)
        android.swipe(serial, x1, y1, x2, y2, args.duration_ms, size)
        action = {
            "action": "swipe",
            "x1": args.x1,
            "y1": args.y1,
            "x2": args.x2,
            "y2": args.y2,
            "duration_ms": args.duration_ms,
        }
    return _complete_action(
        args,
        session,
        serial,
        action,
        observation_id=args.observation,
    )


def _simple_action(args: argparse.Namespace) -> dict[str, Any]:
    _settle_request(args)
    session, serial = _driver(args)
    if args.command == "wait":
        android.wait(args.duration_ms)
        action = {"action": "wait", "duration_ms": args.duration_ms}
    elif args.command == "type":
        method = android.type_text(serial, args.text)
        action = {"action": "type", "text_length": len(args.text), "method": method}
    elif args.command == "press":
        android.press(serial, args.key)
        action = {"action": "press", "key": args.key}
    elif args.command == "home":
        android.home(serial)
        action = {"action": "home"}
    elif args.command == "back":
        android.back(serial)
        action = {"action": "back"}
    elif args.command == "app-switcher":
        android.app_switcher(serial)
        action = {"action": "app-switcher"}
    elif args.command == "app":
        package = android.launch_app(serial, args.package)
        action = {"action": "app-open", "package": package}
    else:
        raise MobileSkillError("unknown_command", f"unknown action: {args.command}")
    return _complete_action(args, session, serial, action)


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "version":
        return _ok(name="mobile-skill", version=__version__)
    if args.command == "doctor":
        return _ok(**diagnostics.doctor(args.agent))
    if args.command == "devices":
        return _ok(devices=android.list_devices())
    if args.command == "install":
        install_agent = (
            installer.install_codex if args.agent == "codex" else installer.install_claude_code
        )
        return _ok(**install_agent())
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
    if args.command == "observe":
        return _observe(args)
    if args.command in ("tap", "double-tap", "long-press", "swipe"):
        return _run_action(args)
    return _simple_action(args)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
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
