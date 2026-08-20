"""Android ADB driver."""

from __future__ import annotations

import base64
import os
import re
import struct
import subprocess
import time
from pathlib import Path

from PIL import Image

from .errors import MobileSkillError


class AndroidError(MobileSkillError):
    """An actionable Android/ADB error."""

    def __init__(self, message: str, code: str = "android_error", hint: str | None = None):
        super().__init__(code, message, hint)


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
            )
        if device is not None and device["state"] == "offline":
            raise AndroidError(
                f"Android device is offline: {requested}",
                "device_offline",
                "reconnect the phone or restart ADB, then retry",
            )
        raise AndroidError(f"Android device is not ready: {requested}", "device_disconnected")
    if len(ready) == 1:
        return ready[0]["serial"]
    if not ready:
        if len(devices) == 1 and devices[0]["state"] == "unauthorized":
            raise AndroidError(
                f"Android device is unauthorized: {devices[0]['serial']}",
                "device_unauthorized",
                "authorize USB debugging on the phone, then retry",
            )
        if len(devices) == 1 and devices[0]["state"] == "offline":
            raise AndroidError(
                f"Android device is offline: {devices[0]['serial']}",
                "device_offline",
                "reconnect the phone or restart ADB, then retry",
            )
        states = ", ".join(f"{d['serial']}={d['state']}" for d in devices) or "none"
        raise AndroidError(
            f"no ready Android device; adb sees: {states}",
            "device_not_found",
            "connect and authorize an Android phone, then retry",
        )
    serials = ", ".join(device["serial"] for device in ready)
    raise AndroidError(
        f"multiple Android devices are ready; pass --device: {serials}", "device_ambiguous"
    )


def require_installed_app(serial: str, app_id: str) -> str:
    if not app_id or any(character.isspace() or ord(character) < 32 for character in app_id):
        raise AndroidError("Android app id is invalid", "invalid_app_id")
    installed = {
        line.removeprefix("package:").strip()
        for line in str(
            run_adb("shell", "pm", "list", "packages", app_id, serial=serial)
        ).splitlines()
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
    match = re.search(r"(?:Override|Physical) size:\s*(\d+)x(\d+)", output)
    if not match:
        raise AndroidError(f"cannot determine screen size from: {output.strip()}")
    return int(match.group(1)), int(match.group(2))


def png_size(image: bytes) -> tuple[int, int]:
    if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
        raise AndroidError("screencap did not return a valid PNG")
    return struct.unpack(">II", image[16:24])


def capture(serial: str, output_path: Path) -> tuple[Path, tuple[int, int]]:
    image = run_adb("exec-out", "screencap", "-p", serial=serial, binary=True)
    size = png_size(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image)
    return output_path, size


def compress_for_model(
    input_path: Path,
    output_path: Path,
    target_width: int = 476,
    quality: int = 85,
) -> tuple[Path, tuple[int, int]]:
    if target_width <= 0:
        raise AndroidError("model image width must be positive")
    if not 1 <= quality <= 95:
        raise AndroidError("JPEG quality must be between 1 and 95")

    with Image.open(input_path) as source:
        width, height = source.size
        target_width = min(target_width, width)
        target_height = max(1, round(height * target_width / width))
        target_size = (target_width, target_height)
        image = source.convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, format="JPEG", quality=quality, optimize=True)
    return output_path, target_size


def wait(duration_ms: int) -> None:
    if duration_ms <= 0:
        raise AndroidError("wait duration must be positive")
    if duration_ms > 60_000:
        raise AndroidError("wait duration must be no more than 60000 milliseconds")
    time.sleep(duration_ms / 1000)


def validate_point(x: int, y: int, width: int, height: int) -> None:
    if not 0 <= x < width or not 0 <= y < height:
        raise AndroidError(f"coordinate ({x}, {y}) is outside {width}x{height}")


def tap(serial: str, x: int, y: int, size: tuple[int, int]) -> None:
    ensure_unlocked(serial)
    validate_point(x, y, *size)
    run_adb("shell", "input", "tap", str(x), str(y), serial=serial)


def double_tap(
    serial: str, x: int, y: int, interval_ms: int, size: tuple[int, int]
) -> None:
    ensure_unlocked(serial)
    validate_point(x, y, *size)
    if interval_ms <= 0:
        raise AndroidError("interval must be positive")
    run_adb("shell", "input", "tap", str(x), str(y), serial=serial)
    time.sleep(interval_ms / 1000)
    run_adb("shell", "input", "tap", str(x), str(y), serial=serial)


def long_press(serial: str, x: int, y: int, duration_ms: int, size: tuple[int, int]) -> None:
    ensure_unlocked(serial)
    validate_point(x, y, *size)
    if duration_ms <= 0:
        raise AndroidError("duration must be positive")
    run_adb(
        "shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms), serial=serial
    )


def swipe(
    serial: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int,
    size: tuple[int, int],
) -> None:
    ensure_unlocked(serial)
    validate_point(x1, y1, *size)
    validate_point(x2, y2, *size)
    if duration_ms <= 0:
        raise AndroidError("duration must be positive")
    run_adb(
        "shell",
        "input",
        "swipe",
        str(x1),
        str(y1),
        str(x2),
        str(y2),
        str(duration_ms),
        serial=serial,
    )


def _ime_list(serial: str, *, include_all: bool) -> list[str]:
    arguments = ["shell", "ime", "list", "-s"]
    if include_all:
        arguments.append("-a")
    output = str(run_adb(*arguments, serial=serial))
    return [line.strip() for line in output.splitlines() if line.strip()]


def _type_unicode_with_adb_keyboard(serial: str, text: str) -> str:
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
        time.sleep(0.25)
        if not was_enabled:
            run_adb("shell", "ime", "enable", ADB_KEYBOARD_IME, serial=serial)
        run_adb("shell", "ime", "set", ADB_KEYBOARD_IME, serial=serial)
        time.sleep(0.35)
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")
        output = str(
            run_adb(
                "shell",
                "am",
                "broadcast",
                "-a",
                ADB_KEYBOARD_INPUT_ACTION,
                "--es",
                "text",
                encoded,
                serial=serial,
            )
        )
        if "result=-1" not in output:
            raise AndroidError(
                "Unicode text was not accepted by the focused input field",
                "unicode_input_failed",
                "wait until the field and keyboard are visibly focused, then try once more",
            )
    finally:
        if original_ime and original_ime != "null":
            run_adb("shell", "ime", "set", original_ime, serial=serial)
        if not was_enabled:
            run_adb("shell", "ime", "disable", ADB_KEYBOARD_IME, serial=serial)
    return "adb-keyboard"


def type_text(serial: str, text: str) -> str:
    ensure_unlocked(serial)
    if any(ord(character) > 127 for character in text):
        return _type_unicode_with_adb_keyboard(serial, text)
    encoded = text.replace(" ", "%s")
    run_adb("shell", "input", "text", encoded, serial=serial)
    return "adb-input-text"


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


def press(serial: str, key: str) -> None:
    ensure_unlocked(serial)
    normalized = key.lower()
    code = KEYS.get(normalized)
    if code is None and len(normalized) == 1 and normalized.isalnum():
        code = normalized.upper()
    if code is None:
        supported = ", ".join(sorted(KEYS))
        raise AndroidError(f"unsupported Android key {key!r}; supported keys: {supported}")
    run_adb("shell", "input", "keyevent", f"KEYCODE_{code}", serial=serial)


def home(serial: str) -> None:
    press(serial, "home")


def back(serial: str) -> None:
    press(serial, "back")


def app_switcher(serial: str) -> None:
    press(serial, "recents")


def launch_app(serial: str, package: str) -> str:
    ensure_unlocked(serial)
    require_installed_app(serial, package)
    run_adb("shell", "monkey", "-p", package, "1", serial=serial)
    return package
