"""ADB-facing android module — subprocess replaced by FakeAdb fixture."""

from __future__ import annotations

import pytest

from mobile_skill import android
from mobile_skill.android import AndroidError


# -- device discovery ---------------------------------------------------------


def test_list_devices_parses_output(fake_adb) -> None:
    fake_adb.when(
        "devices", "-l",
        returns=(
            "List of devices attached\n"
            "emu-5554 device product:sdk model:Pixel_6\n"
            "1234abcd unauthorized\n"
        ),
    )
    devices = android.list_devices()
    assert devices == [
        {"serial": "emu-5554", "state": "device", "product": "sdk", "model": "Pixel_6"},
        {"serial": "1234abcd", "state": "unauthorized"},
    ]


def test_list_devices_empty(fake_adb) -> None:
    fake_adb.when("devices", "-l", returns="List of devices attached\n")
    assert android.list_devices() == []


def test_require_device_single_ready(fake_adb) -> None:
    fake_adb.when("devices", "-l", returns="List of devices attached\nemu-1 device\n")
    assert android.require_device() == "emu-1"


def test_require_device_unauthorized(fake_adb) -> None:
    fake_adb.when("devices", "-l", returns="List of devices attached\nX unauthorized\n")
    with pytest.raises(AndroidError) as excinfo:
        android.require_device()
    assert excinfo.value.code == "device_unauthorized"


def test_require_device_offline(fake_adb) -> None:
    fake_adb.when("devices", "-l", returns="List of devices attached\nX offline\n")
    with pytest.raises(AndroidError) as excinfo:
        android.require_device()
    assert excinfo.value.code == "device_offline"


def test_require_device_missing(fake_adb) -> None:
    fake_adb.when("devices", "-l", returns="List of devices attached\n")
    with pytest.raises(AndroidError) as excinfo:
        android.require_device()
    assert excinfo.value.code == "device_not_found"


def test_require_device_ambiguous(fake_adb) -> None:
    fake_adb.when(
        "devices", "-l",
        returns="List of devices attached\nA device\nB device\n",
    )
    with pytest.raises(AndroidError) as excinfo:
        android.require_device()
    assert excinfo.value.code == "device_ambiguous"


def test_require_device_specific_serial_disconnected(fake_adb) -> None:
    fake_adb.when(
        "devices", "-l",
        returns="List of devices attached\nother device\n",
    )
    with pytest.raises(AndroidError) as excinfo:
        android.require_device("wanted")
    assert excinfo.value.code == "device_disconnected"


# -- installed apps -----------------------------------------------------------


def test_require_installed_app_found(fake_adb) -> None:
    fake_adb.when(
        "shell", "pm", "list", "packages",
        returns="package:com.example\npackage:com.other\n",
    )
    assert android.require_installed_app("emu-1", "com.example") == "com.example"


def test_require_installed_app_missing(fake_adb) -> None:
    fake_adb.when("shell", "pm", "list", "packages", returns="")
    with pytest.raises(AndroidError) as excinfo:
        android.require_installed_app("emu-1", "com.example")
    assert excinfo.value.code == "app_not_found"


@pytest.mark.parametrize("bad", ["", "with space", "tab\there"])
def test_require_installed_app_invalid_id(fake_adb, bad: str) -> None:
    with pytest.raises(AndroidError) as excinfo:
        android.require_installed_app("emu-1", bad)
    assert excinfo.value.code == "invalid_app_id"


# -- unlock check -------------------------------------------------------------


def test_ensure_unlocked_ok(fake_adb) -> None:
    fake_adb.when("shell", "dumpsys", "power", returns="  mWakefulness=Awake\n")
    fake_adb.when("shell", "dumpsys", "window", returns="mDreamingLockscreen=false\n")
    android.ensure_unlocked("emu-1")


def test_ensure_unlocked_asleep(fake_adb) -> None:
    fake_adb.when("shell", "dumpsys", "power", returns="mWakefulness=Asleep")
    with pytest.raises(AndroidError) as excinfo:
        android.ensure_unlocked("emu-1")
    assert excinfo.value.code == "device_locked"


def test_ensure_unlocked_keyguard(fake_adb) -> None:
    fake_adb.when("shell", "dumpsys", "power", returns="mWakefulness=Awake")
    fake_adb.when("shell", "dumpsys", "window", returns="isKeyguardShowing=true")
    with pytest.raises(AndroidError) as excinfo:
        android.ensure_unlocked("emu-1")
    assert excinfo.value.code == "device_locked"


# -- screen size --------------------------------------------------------------


def test_screen_size_override_beats_physical(fake_adb) -> None:
    fake_adb.when(
        "shell", "wm", "size",
        returns="Physical size: 1440x3200\nOverride size: 1080x2400\n",
    )
    assert android.screen_size("emu-1") == (1080, 2400)


def test_screen_size_physical_only(fake_adb) -> None:
    fake_adb.when("shell", "wm", "size", returns="Physical size: 1080x2400\n")
    assert android.screen_size("emu-1") == (1080, 2400)


def test_screen_size_missing_raises(fake_adb) -> None:
    fake_adb.when("shell", "wm", "size", returns="unknown output")
    with pytest.raises(AndroidError):
        android.screen_size("emu-1")


# -- coordinate actions -------------------------------------------------------


def test_tap_emits_input_tap(fake_adb) -> None:
    android.tap("emu-1", 100, 200, (1080, 2400))
    assert fake_adb.calls[-1]["args"] == ("shell", "input", "tap", "100", "200")
    assert fake_adb.calls[-1]["serial"] == "emu-1"


def test_double_tap_two_taps_with_sleep(fake_adb) -> None:
    android.double_tap("emu-1", 50, 60, 150, (1080, 2400))
    taps = [c for c in fake_adb.calls if c["args"][:3] == ("shell", "input", "tap")]
    assert len(taps) == 2
    assert 0.14 <= fake_adb.sleeps[0] <= 0.16


def test_double_tap_rejects_bad_interval(fake_adb) -> None:
    with pytest.raises(AndroidError):
        android.double_tap("emu-1", 50, 60, 0, (1080, 2400))


def test_long_press_emits_swipe_self(fake_adb) -> None:
    android.long_press("emu-1", 100, 200, 800, (1080, 2400))
    assert fake_adb.calls[-1]["args"] == (
        "shell", "input", "swipe", "100", "200", "100", "200", "800",
    )


def test_swipe_emits_all_args(fake_adb) -> None:
    android.swipe("emu-1", 10, 20, 30, 40, 500, (1080, 2400))
    assert fake_adb.calls[-1]["args"] == (
        "shell", "input", "swipe", "10", "20", "30", "40", "500",
    )


def test_swipe_rejects_out_of_bounds(fake_adb) -> None:
    with pytest.raises(AndroidError):
        android.swipe("emu-1", 0, 0, 2000, 0, 300, (1080, 2400))


# -- press/home/back/app-switcher --------------------------------------------


def test_press_enter(fake_adb) -> None:
    android.press("emu-1", "enter")
    assert fake_adb.calls[-1]["args"] == ("shell", "input", "keyevent", "KEYCODE_ENTER")


def test_press_return_maps_to_enter(fake_adb) -> None:
    android.press("emu-1", "return")
    assert fake_adb.calls[-1]["args"] == ("shell", "input", "keyevent", "KEYCODE_ENTER")


def test_press_single_alpha_uppercases(fake_adb) -> None:
    android.press("emu-1", "a")
    assert fake_adb.calls[-1]["args"] == ("shell", "input", "keyevent", "KEYCODE_A")


def test_press_unknown_key(fake_adb) -> None:
    with pytest.raises(AndroidError) as excinfo:
        android.press("emu-1", "unknownkey")
    assert "supported keys" in str(excinfo.value)


def test_home_back_switcher(fake_adb) -> None:
    android.home("emu-1")
    android.back("emu-1")
    android.app_switcher("emu-1")
    codes = [call["args"][-1] for call in fake_adb.calls]
    assert "KEYCODE_HOME" in codes
    assert "KEYCODE_BACK" in codes
    assert "KEYCODE_APP_SWITCH" in codes


# -- type_text ---------------------------------------------------------------


def test_type_ascii_uses_input_text(fake_adb) -> None:
    method = android.type_text("emu-1", "hello world")
    assert method == "adb-input-text"
    last = fake_adb.calls[-1]["args"]
    assert last[:3] == ("shell", "input", "text")
    assert last[3] == "'hello%sworld'"


def test_type_unicode_via_adb_keyboard(fake_adb) -> None:
    fake_adb.when(
        "shell", "ime", "list", "-s", "-a",
        returns=f"{android.ADB_KEYBOARD_IME}\ncom.other/.SomeIME\n",
    )
    fake_adb.when(
        "shell", "ime", "list", "-s",
        returns="com.other/.SomeIME\n",  # keyboard not currently enabled
    )
    fake_adb.when(
        "shell", "settings", "get", "secure", "default_input_method",
        returns="com.other/.SomeIME\n",
    )
    fake_adb.when(
        "shell", "am", "broadcast",
        returns="Broadcast completed: result=-1\n",
    )
    method = android.type_text("emu-1", "你好")
    assert method == "adb-keyboard-broadcast"
    argvs = [call["args"] for call in fake_adb.calls]
    # keyboard was enabled and later disabled
    assert ("shell", "ime", "enable", android.ADB_KEYBOARD_IME) in argvs
    assert ("shell", "ime", "disable", android.ADB_KEYBOARD_IME) in argvs
    # original ime restored
    assert ("shell", "ime", "set", "com.other/.SomeIME") in argvs


def test_type_unicode_missing_keyboard(fake_adb) -> None:
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns="com.other/.SomeIME\n")
    with pytest.raises(AndroidError) as excinfo:
        android.type_text("emu-1", "你好")
    assert excinfo.value.code == "unicode_input_unavailable"


def test_type_broadcast_failure(fake_adb) -> None:
    fake_adb.when(
        "shell", "ime", "list", "-s", "-a",
        returns=f"{android.ADB_KEYBOARD_IME}\n",
    )
    fake_adb.when("shell", "ime", "list", "-s", returns=f"{android.ADB_KEYBOARD_IME}\n")
    fake_adb.when(
        "shell", "settings", "get", "secure", "default_input_method",
        returns="null\n",
    )
    fake_adb.when("shell", "am", "broadcast", returns="Broadcast completed: result=0\n")
    with pytest.raises(AndroidError) as excinfo:
        android.type_text("emu-1", "你好")
    assert excinfo.value.code == "unicode_input_failed"


def test_type_splits_newlines(fake_adb) -> None:
    method = android.type_text("emu-1", "hello\nworld")
    assert method == "adb-input-text+enter"
    input_texts = [c for c in fake_adb.calls if c["args"][:3] == ("shell", "input", "text")]
    assert len(input_texts) == 2
    enter_events = [
        c for c in fake_adb.calls
        if c["args"][:3] == ("shell", "input", "keyevent") and c["args"][3] == "KEYCODE_ENTER"
    ]
    assert len(enter_events) == 1


def test_type_empty_string(fake_adb) -> None:
    # Empty string doesn't go through _type_segment; caller (cli) guards it.
    method = android.type_text("emu-1", "")
    assert method == "adb-input-text"


# -- input_capabilities -------------------------------------------------------


def test_input_capabilities_ready(fake_adb) -> None:
    fake_adb.when(
        "shell", "settings", "get", "secure", "default_input_method",
        returns="com.example/.IME\n",
    )
    fake_adb.when(
        "shell", "ime", "list", "-s", "-a",
        returns=f"{android.ADB_KEYBOARD_IME}\ncom.example/.IME\n",
    )
    fake_adb.when(
        "shell", "ime", "list", "-s",
        returns=f"{android.ADB_KEYBOARD_IME}\ncom.example/.IME\n",
    )
    caps = android.input_capabilities("emu-1")
    assert caps["ascii"]["status"] == "ready"
    assert caps["unicode"]["status"] == "ready"


def test_input_capabilities_no_helper_ime(fake_adb) -> None:
    fake_adb.when(
        "shell", "settings", "get", "secure", "default_input_method",
        returns="com.example/.IME\n",
    )
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns="com.example/.IME\n")
    fake_adb.when("shell", "ime", "list", "-s", returns="com.example/.IME\n")
    caps = android.input_capabilities("emu-1")
    assert caps["unicode"]["status"] == "unavailable"
    assert caps["unicode"]["hint"]


# -- package listing / launcher resolution -----------------------------------


def test_list_packages_default(fake_adb) -> None:
    fake_adb.when(
        "shell", "pm", "list", "packages", "-e",
        returns="package:com.a\npackage:com.b\npackage:com.a\n",  # dedup
    )
    assert android.list_packages("emu-1") == ["com.a", "com.b"]


def test_list_packages_user_visible(fake_adb) -> None:
    fake_adb.when(
        "shell", "cmd", "package", "query-activities",
        returns=(
            "  com.app.a/.Main\n"
            "  com.app.b/.Main  extras here\n"  # space → skipped
            "  com.app.c/.Main\n"
        ),
    )
    result = android.list_packages("emu-1", user_visible=True)
    assert result == ["com.app.a", "com.app.c"]


def test_launch_app_uses_resolved_component(fake_adb) -> None:
    fake_adb.when(
        "shell", "pm", "list", "packages",
        returns="package:com.example\n",
    )
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="com.example/.MainActivity\n",
    )
    android.launch_app("emu-1", "com.example")
    starts = [c for c in fake_adb.calls if c["args"][:4] == ("shell", "am", "start", "-n")]
    assert starts and "com.example/.MainActivity" in starts[-1]["args"][-1]


def test_launch_app_falls_back_to_query_activities(fake_adb) -> None:
    fake_adb.when("shell", "pm", "list", "packages", returns="package:com.example\n")
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="No Activity found\n",
    )
    fake_adb.when(
        "shell", "cmd", "package", "query-activities",
        returns="com.example/.HiddenMain\n",
    )
    android.launch_app("emu-1", "com.example")
    starts = [c for c in fake_adb.calls if c["args"][:4] == ("shell", "am", "start", "-n")]
    assert starts and "com.example/.HiddenMain" in starts[-1]["args"][-1]


def test_launch_app_unlaunchable(fake_adb) -> None:
    fake_adb.when("shell", "pm", "list", "packages", returns="package:com.example\n")
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="No Activity found\n",
    )
    fake_adb.when(
        "shell", "cmd", "package", "query-activities",
        returns="",
    )
    with pytest.raises(AndroidError) as excinfo:
        android.launch_app("emu-1", "com.example")
    assert excinfo.value.code == "app_not_launchable"


# -- wait ---------------------------------------------------------------------


def test_wait_sleeps(fake_adb) -> None:
    android.wait(250)
    assert fake_adb.sleeps[-1] == pytest.approx(0.25)


@pytest.mark.parametrize("bad", [-1, 60_001])
def test_wait_range(bad: int, fake_adb) -> None:
    with pytest.raises(AndroidError):
        android.wait(bad)


# -- capture ------------------------------------------------------------------


def _fake_png_bytes(width: int, height: int) -> bytes:
    import struct
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + struct.pack(">II", width, height)
        + b"\x00" * 100
    )


def test_capture_returns_bytes_and_size(fake_adb, tmp_path) -> None:
    png = _fake_png_bytes(1080, 2400)
    fake_adb.when("exec-out", "screencap", "-p", returns=png)
    image, size = android.capture("emu-1")
    assert image == png
    assert size == (1080, 2400)


def test_capture_writes_optional_file(fake_adb, tmp_path) -> None:
    png = _fake_png_bytes(200, 300)
    fake_adb.when("exec-out", "screencap", "-p", returns=png)
    out = tmp_path / "sub" / "shot.png"
    android.capture("emu-1", out)
    assert out.read_bytes() == png
