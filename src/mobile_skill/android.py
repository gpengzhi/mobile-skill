"""Android ADB driver."""

from __future__ import annotations

import base64
import os
import re
import struct
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .errors import MobileSkillError


class AndroidError(MobileSkillError):
    """An actionable Android/ADB error."""

    def __init__(
        self,
        message: str,
        code: str = "android_error",
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(code, message, hint, details)


KEYS = {
    "enter": "ENTER",
    "return": "ENTER",
    "space": "SPACE",
    "backspace": "DEL",
    "delete": "DEL",
    "tab": "TAB",
    "escape": "ESCAPE",
    "home": "HOME",
    "back": "BACK",
    "recents": "APP_SWITCH",
    "volume-up": "VOLUME_UP",
    "volume-down": "VOLUME_DOWN",
}

ADB_KEYBOARD_IME = "com.github.uiautomator/.AdbKeyboard"
ADB_KEYBOARD_INPUT_ACTION = "ADB_KEYBOARD_INPUT_TEXT"
# Empirically-derived delays; err on the side of the original keyboard being
# fully hidden and ADBKeyboard fully bound before broadcasting text.
ADB_KEYBOARD_PRE_SWITCH_DELAY_S = 0.25
ADB_KEYBOARD_POST_SWITCH_DELAY_S = 0.35


def adb_path() -> str:
    return os.environ.get("MOBILE_SKILL_ADB", "adb")


def run_adb(*arguments: str, serial: str | None = None, binary: bool = False) -> str | bytes:
    command = [adb_path()]
    if serial:
        command.extend(["-s", serial])
    command.extend(arguments)
    try:
        result = subprocess.run(command, capture_output=True, timeout=60)
    except FileNotFoundError as error:
        raise AndroidError(
            "adb is not installed",
            "adb_not_found",
            "install Android platform-tools or set MOBILE_SKILL_ADB",
        ) from error
    except subprocess.TimeoutExpired as error:
        raise AndroidError(f"adb command timed out: {' '.join(command)}", "timeout") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode(errors="replace").strip()
        raise AndroidError(
            f"adb {' '.join(arguments)} failed: {detail or 'unknown error'}", "adb_failed"
        )
    return result.stdout if binary else result.stdout.decode(errors="replace")


def run_action_adb(
    *arguments: str,
    serial: str | None = None,
    before_dispatch: Callable[[], None] | None = None,
) -> str:
    """Run a mutating ADB command and mark transport failures as uncertain."""
    if before_dispatch is not None:
        before_dispatch()
    try:
        return str(run_adb(*arguments, serial=serial))
    except AndroidError as error:
        if error.code != "adb_not_found":
            error.details["action_may_have_applied"] = True
        raise


def shell_quote(value: str) -> str:
    """Quote a value for the device shell that interprets `adb shell` commands."""
    return "'" + value.replace("'", "'\\''") + "'"


def list_devices() -> list[dict[str, str]]:
    output = run_adb("devices", "-l")
    devices = []
    for line in str(output).splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        device = {"serial": fields[0], "state": fields[1]}
        for field in fields[2:]:
            if ":" in field:
                key, value = field.split(":", 1)
                device[key] = value
        devices.append(device)
    return devices


def restart_server() -> None:
    run_adb("kill-server")
    run_adb("start-server")


def require_device(serial: str | None = None) -> str:
    requested = serial or os.environ.get("ANDROID_SERIAL")
    devices = list_devices()
    ready = [device for device in devices if device["state"] == "device"]
    if requested:
        device = next((device for device in devices if device["serial"] == requested), None)
        if device is not None and device["state"] == "device":
            return requested
        if device is not None and device["state"] == "unauthorized":
            raise AndroidError(
                f"Android device is unauthorized: {requested}",
                "device_unauthorized",
                "authorize USB debugging on the phone, then retry",
                {"serial": requested},
            )
        if device is not None and device["state"] == "offline":
            raise AndroidError(
                f"Android device is offline: {requested}",
                "device_offline",
                "reconnect the phone or restart ADB, then retry",
                {"serial": requested},
            )
        raise AndroidError(
            f"Android device is not ready: {requested}",
            "device_disconnected",
            None,
            {"serial": requested, "devices": devices},
        )
    if len(ready) == 1:
        return ready[0]["serial"]
    if not ready:
        if len(devices) == 1 and devices[0]["state"] == "unauthorized":
            raise AndroidError(
                f"Android device is unauthorized: {devices[0]['serial']}",
                "device_unauthorized",
                "authorize USB debugging on the phone, then retry",
                {"serial": devices[0]["serial"]},
            )
        if len(devices) == 1 and devices[0]["state"] == "offline":
            raise AndroidError(
                f"Android device is offline: {devices[0]['serial']}",
                "device_offline",
                "reconnect the phone or restart ADB, then retry",
                {"serial": devices[0]["serial"]},
            )
        states = ", ".join(f"{d['serial']}={d['state']}" for d in devices) or "none"
        raise AndroidError(
            f"no ready Android device; adb sees: {states}",
            "device_not_found",
            "connect and authorize an Android phone, then retry",
            {"devices": devices},
        )
    serials = ", ".join(device["serial"] for device in ready)
    raise AndroidError(
        f"multiple Android devices are ready; pass --device: {serials}",
        "device_ambiguous",
        None,
        {"serials": [d["serial"] for d in ready]},
    )


def require_installed_app(serial: str, app_id: str) -> str:
    if not app_id or any(character.isspace() or ord(character) < 32 for character in app_id):
        raise AndroidError("Android app id is invalid", "invalid_app_id")
    output = run_adb(
        "shell", "pm", "list", "packages", shell_quote(app_id), serial=serial
    )
    installed = {
        line.removeprefix("package:").strip()
        for line in str(output).splitlines()
        if line.startswith("package:")
    }
    if app_id not in installed:
        raise AndroidError(
            f"Android package is not installed: {app_id}",
            "app_not_found",
            "pass the exact Android package name",
        )
    return app_id


def ensure_unlocked(serial: str) -> None:
    power = str(run_adb("shell", "dumpsys", "power", serial=serial))
    if "mWakefulness=Awake" not in power and "Wakefulness: Awake" not in power:
        raise AndroidError(
            "the Android phone is asleep",
            "device_locked",
            "wake and unlock the phone, then retry",
        )
    window = str(run_adb("shell", "dumpsys", "window", serial=serial))
    locked_markers = (
        "isKeyguardShowing=true",
        "mShowingLockscreen=true",
        "isStatusBarKeyguard=true",
    )
    if any(marker in window for marker in locked_markers):
        raise AndroidError(
            "the Android phone is locked",
            "device_locked",
            "unlock the phone yourself, then retry; mobile-skill never enters a PIN",
        )


def screen_size(serial: str) -> tuple[int, int]:
    output = str(run_adb("shell", "wm", "size", serial=serial))
    match = re.search(r"Override size:\s*(\d+)x(\d+)", output) or re.search(
        r"Physical size:\s*(\d+)x(\d+)", output
    )
    if not match:
        raise AndroidError(f"cannot determine screen size from: {output.strip()}")
    return int(match.group(1)), int(match.group(2))


def png_size(image: bytes) -> tuple[int, int]:
    if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
        raise AndroidError("screencap did not return a valid PNG")
    return struct.unpack(">II", image[16:24])


def capture(
    serial: str, output_path: Path | None = None
) -> tuple[bytes, tuple[int, int]]:
    image = run_adb("exec-out", "screencap", "-p", serial=serial, binary=True)
    size = png_size(image)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image)
    return image, size


def compress_for_model(
    source: Path | bytes,
    output_path: Path,
    target_width: int = 476,
    quality: int = 85,
) -> tuple[Path, tuple[int, int]]:
    if target_width <= 0:
        raise AndroidError("model image width must be positive")
    if not 1 <= quality <= 95:
        raise AndroidError("JPEG quality must be between 1 and 95")
    try:
        from PIL import Image
    except ImportError as error:
        raise AndroidError(
            "Pillow is not installed", "pillow_not_found", "pip install Pillow"
        ) from error

    if isinstance(source, bytes):
        from io import BytesIO

        opener = BytesIO(source)
    else:
        opener = source

    with Image.open(opener) as image_obj:
        width, height = image_obj.size
        target_width = min(target_width, width)
        target_height = max(1, round(height * target_width / width))
        target_size = (target_width, target_height)
        image = image_obj.convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=quality, optimize=True)
    return output_path, target_size


def wait(duration_ms: int) -> None:
    if duration_ms < 0:
        raise AndroidError("wait duration must not be negative")
    if duration_ms > 60_000:
        raise AndroidError("wait duration must be no more than 60000 milliseconds")
    time.sleep(duration_ms / 1000)


def validate_point(x: int, y: int, width: int, height: int) -> None:
    if not 0 <= x < width or not 0 <= y < height:
        raise AndroidError(f"coordinate ({x}, {y}) is outside {width}x{height}")


def tap(
    serial: str,
    x: int,
    y: int,
    size: tuple[int, int],
    *,
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    validate_point(x, y, *size)
    run_action_adb(
        "shell",
        "input",
        "tap",
        str(x),
        str(y),
        serial=serial,
        before_dispatch=before_dispatch,
    )


def double_tap(
    serial: str,
    x: int,
    y: int,
    interval_ms: int,
    size: tuple[int, int],
    *,
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    validate_point(x, y, *size)
    if interval_ms <= 0:
        raise AndroidError("interval must be positive")
    run_action_adb(
        "shell",
        "input",
        "tap",
        str(x),
        str(y),
        serial=serial,
        before_dispatch=before_dispatch,
    )
    time.sleep(interval_ms / 1000)
    run_action_adb("shell", "input", "tap", str(x), str(y), serial=serial)


def long_press(
    serial: str,
    x: int,
    y: int,
    duration_ms: int,
    size: tuple[int, int],
    *,
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    validate_point(x, y, *size)
    if duration_ms <= 0:
        raise AndroidError("duration must be positive")
    run_action_adb(
        "shell",
        "input",
        "swipe",
        str(x),
        str(y),
        str(x),
        str(y),
        str(duration_ms),
        serial=serial,
        before_dispatch=before_dispatch,
    )


def swipe(
    serial: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int,
    size: tuple[int, int],
    *,
    before_dispatch: Callable[[], None] | None = None,
) -> None:
    validate_point(x1, y1, *size)
    validate_point(x2, y2, *size)
    if duration_ms <= 0:
        raise AndroidError("duration must be positive")
    run_action_adb(
        "shell",
        "input",
        "swipe",
        str(x1),
        str(y1),
        str(x2),
        str(y2),
        str(duration_ms),
        serial=serial,
        before_dispatch=before_dispatch,
    )


def _ime_list(serial: str, *, include_all: bool) -> list[str]:
    arguments = ["shell", "ime", "list", "-s"]
    if include_all:
        arguments.append("-a")
    output = str(run_adb(*arguments, serial=serial))
    return [line.strip() for line in output.splitlines() if line.strip()]


def _type_unicode_with_adb_keyboard(
    serial: str, text: str, *, before_dispatch: Callable[[], None] | None = None
) -> str:
    installed_imes = _ime_list(serial, include_all=True)
    if ADB_KEYBOARD_IME not in installed_imes:
        raise AndroidError(
            "Unicode input is unavailable on this Android device",
            "unicode_input_unavailable",
            "install and enable a supported helper IME, or use human takeover",
        )

    enabled_imes = _ime_list(serial, include_all=False)
    original_ime = str(
        run_adb("shell", "settings", "get", "secure", "default_input_method", serial=serial)
    ).strip()
    was_enabled = ADB_KEYBOARD_IME in enabled_imes
    try:
        time.sleep(ADB_KEYBOARD_PRE_SWITCH_DELAY_S)
        if not was_enabled:
            run_action_adb(
                "shell",
                "ime",
                "enable",
                ADB_KEYBOARD_IME,
                serial=serial,
                before_dispatch=before_dispatch,
            )
        run_action_adb(
            "shell",
            "ime",
            "set",
            ADB_KEYBOARD_IME,
            serial=serial,
            before_dispatch=before_dispatch,
        )
        time.sleep(ADB_KEYBOARD_POST_SWITCH_DELAY_S)
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")
        output = str(
            run_action_adb(
                "shell",
                "am",
                "broadcast",
                "-a",
                ADB_KEYBOARD_INPUT_ACTION,
                "--es",
                "text",
                encoded,
                serial=serial,
                before_dispatch=before_dispatch,
            )
        )
        if "result=-1" not in output:
            raise AndroidError(
                "the ADBKeyboard broadcast was not delivered",
                "unicode_input_failed",
                "verify the helper IME is enabled and try again",
                {"action_may_have_applied": True},
            )
    finally:
        if original_ime and original_ime != "null":
            run_action_adb("shell", "ime", "set", original_ime, serial=serial)
        if not was_enabled:
            run_action_adb("shell", "ime", "disable", ADB_KEYBOARD_IME, serial=serial)
    # The broadcast reached ADBKeyboard's receiver; that does NOT prove the
    # focused input field received text (or that any field is focused at all).
    # The caller must re-observe and visually confirm the text landed.
    return "adb-keyboard-broadcast"


def type_text(
    serial: str, text: str, *, before_dispatch: Callable[[], None] | None = None
) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" not in normalized:
        return _type_segment(serial, normalized, before_dispatch=before_dispatch)
    segments = normalized.split("\n")
    methods: list[str] = []
    for index, segment in enumerate(segments):
        if index > 0:
            press(serial, "enter", before_dispatch=before_dispatch)
        if segment:
            method = _type_segment(serial, segment, before_dispatch=before_dispatch)
            if method not in methods:
                methods.append(method)
    methods.append("enter")
    return "+".join(methods)


def _type_segment(
    serial: str, text: str, *, before_dispatch: Callable[[], None] | None = None
) -> str:
    if _needs_ime(text):
        return _type_unicode_with_adb_keyboard(
            serial, text, before_dispatch=before_dispatch
        )
    encoded = shell_quote(text.replace(" ", "%s"))
    run_action_adb(
        "shell",
        "input",
        "text",
        encoded,
        serial=serial,
        before_dispatch=before_dispatch,
    )
    return "adb-input-text"


def _needs_ime(text: str) -> bool:
    if "%s" in text:
        return True
    for character in text:
        code = ord(character)
        if code > 127 or code < 32 or code == 127:
            return True
    return False


def input_capabilities(serial: str) -> dict[str, object]:
    default_ime = str(
        run_adb("shell", "settings", "get", "secure", "default_input_method", serial=serial)
    ).strip()
    enabled_imes = _ime_list(serial, include_all=False)
    installed_imes = _ime_list(serial, include_all=True)
    unicode_ready = ADB_KEYBOARD_IME in installed_imes
    return {
        "ascii": {"status": "ready", "method": "adb-input-text"},
        "unicode": {
            "status": "ready" if unicode_ready else "unavailable",
            "method": "adb-keyboard" if unicode_ready else None,
            "temporary_ime_switch": unicode_ready,
            "reason": None if unicode_ready else "no supported helper IME is installed",
            "hint": None
            if unicode_ready
            else "install a supported helper IME, or use human takeover",
        },
        "default_ime": default_ime,
        "enabled_imes": enabled_imes,
        "installed_imes": installed_imes,
    }


def press(
    serial: str, key: str, *, before_dispatch: Callable[[], None] | None = None
) -> None:
    normalized = key.lower()
    code = KEYS.get(normalized)
    if code is None and len(normalized) == 1 and normalized.isalnum():
        code = normalized.upper()
    if code is None:
        supported = ", ".join(sorted(KEYS))
        raise AndroidError(f"unsupported Android key {key!r}; supported keys: {supported}")
    run_action_adb(
        "shell",
        "input",
        "keyevent",
        f"KEYCODE_{code}",
        serial=serial,
        before_dispatch=before_dispatch,
    )


def home(serial: str, *, before_dispatch: Callable[[], None] | None = None) -> None:
    press(serial, "home", before_dispatch=before_dispatch)


def back(serial: str, *, before_dispatch: Callable[[], None] | None = None) -> None:
    press(serial, "back", before_dispatch=before_dispatch)


def app_switcher(
    serial: str, *, before_dispatch: Callable[[], None] | None = None
) -> None:
    press(serial, "recents", before_dispatch=before_dispatch)


def launch_app(
    serial: str,
    package: str,
    *,
    before_dispatch: Callable[[], None] | None = None,
) -> str:
    require_installed_app(serial, package)
    component = _resolve_launcher_component(serial, package)
    run_action_adb(
        "shell",
        "am",
        "start",
        "-n",
        shell_quote(component),
        serial=serial,
        before_dispatch=before_dispatch,
    )
    return package


def list_packages(serial: str, *, user_visible: bool = False) -> list[str]:
    if user_visible:
        output = str(
            run_adb(
                "shell",
                "cmd",
                "package",
                "query-activities",
                "--brief",
                "-a",
                "android.intent.action.MAIN",
                "-c",
                "android.intent.category.LAUNCHER",
                serial=serial,
            )
        )
        packages: set[str] = set()
        for line in output.splitlines():
            candidate = line.strip()
            if "/" in candidate and " " not in candidate:
                packages.add(candidate.split("/", 1)[0])
        return sorted(packages)
    output = str(run_adb("shell", "pm", "list", "packages", "-e", serial=serial))
    packages_list: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("package:"):
            packages_list.append(stripped.removeprefix("package:").strip())
    return sorted(set(packages_list))


_LAUNCHER_INTENT_ARGS = (
    "-a",
    "android.intent.action.MAIN",
    "-c",
    "android.intent.category.LAUNCHER",
)


def _find_launcher_line(output: str, prefix: str) -> str | None:
    for line in output.splitlines():
        candidate = line.strip()
        if candidate.startswith(prefix) and " " not in candidate:
            return candidate
    return None


def _resolve_launcher_component(serial: str, package: str) -> str:
    prefix = package + "/"
    attempts: dict[str, str] = {}
    lookups = (
        ("resolve", ("cmd", "package", "resolve-activity", "--brief", *_LAUNCHER_INTENT_ARGS, shell_quote(package))),
        ("query", ("cmd", "package", "query-activities", "--brief", *_LAUNCHER_INTENT_ARGS)),
    )
    for label, arguments in lookups:
        try:
            output = str(run_adb("shell", *arguments, serial=serial))
        except AndroidError:
            continue
        attempts[label] = output
        found = _find_launcher_line(output, prefix)
        if found is not None:
            return found

    raise AndroidError(
        f"cannot resolve launcher activity for {package}",
        "app_not_launchable",
        "this app may not declare a MAIN/LAUNCHER activity",
        {
            "package": package,
            "resolve_output": attempts.get("resolve", "").strip()[:500],
            "query_output": attempts.get("query", "").strip()[:500],
        },
    )
