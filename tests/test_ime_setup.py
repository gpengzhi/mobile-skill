"""setup-ime — helper IME download/install/verify flow.

FakeAdb covers the ADB side; the network seam is `ime_setup.download_apk`
itself (monkeypatched to write a local blob and return a digest).
"""

from __future__ import annotations

import hashlib

import pytest

from mobile_skill import android, ime_setup
from mobile_skill.errors import MobileSkillError

IME_PRESENT = f"com.other/.SomeIME\n{android.ADB_KEYBOARD_IME}\n"
IME_ABSENT = "com.other/.SomeIME\n"


@pytest.fixture
def one_device(fake_adb):
    fake_adb.when("devices", "-l", returns="List of devices attached\nemu-1 device\n")


@pytest.fixture
def ime_appears_after_install(fake_adb):
    """IME list lacks AdbKeyboard before install, includes it afterwards."""
    calls = {"n": 0}

    def reply(args, serial, binary):
        calls["n"] += 1
        return IME_ABSENT if calls["n"] == 1 else IME_PRESENT

    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=reply)


@pytest.fixture
def fake_download(monkeypatch):
    """download_apk writes a fixed blob; the pinned checksum matches it."""
    payload = b"fake-apk-bytes"
    monkeypatch.setattr(ime_setup, "APK_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(ime_setup, "APK_EXPECTED_BYTES", len(payload))

    def download(url, destination):
        destination.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(ime_setup, "download_apk", download)
    return download


def test_setup_ime_already_installed_is_noop(one_device, fake_adb, monkeypatch):
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=IME_PRESENT)

    def fail(url, destination):  # pragma: no cover - must not be reached
        raise AssertionError("download_apk must not run when the IME exists")

    monkeypatch.setattr(ime_setup, "download_apk", fail)
    report = ime_setup.setup_ime("emu-1")
    assert report == {
        "device_id": "emu-1",
        "ime": android.ADB_KEYBOARD_IME,
        "installed": False,
        "already_installed": True,
        "verified": True,
        "source": "none",
        "checksum_verified": False,
    }
    assert not any(argv[:1] == ("install",) for argv in fake_adb.argvs())


def test_setup_ime_downloads_installs_verifies(
    one_device, fake_adb, ime_appears_after_install, fake_download
):
    fake_adb.when("install", returns="Success\n")
    report = ime_setup.setup_ime("emu-1")
    assert report["installed"] is True
    assert report["already_installed"] is False
    assert report["verified"] is True
    assert report["source"] == "download"
    assert report["checksum_verified"] is True
    # install ran with the downloaded temp file
    install_argv = next(argv for argv in fake_adb.argvs() if argv[:1] == ("install",))
    assert install_argv[1] == "-r"


def test_setup_ime_local_apk_skips_download(
    one_device, fake_adb, ime_appears_after_install, tmp_path, monkeypatch
):
    fake_adb.when("install", returns="Success\n")
    apk = tmp_path / "app-uiautomator.apk"
    apk.write_bytes(b"local-apk")

    def fail(url, destination):  # pragma: no cover - must not be reached
        raise AssertionError("--apk must bypass the download entirely")

    monkeypatch.setattr(ime_setup, "download_apk", fail)
    report = ime_setup.setup_ime("emu-1", apk_path=str(apk))
    assert report["source"] == "local"
    assert report["checksum_verified"] is False
    assert report["verified"] is True


def test_setup_ime_local_apk_missing(one_device, fake_adb):
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=IME_ABSENT)
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1", apk_path="/nonexistent/app.apk")
    assert excinfo.value.code == "apk_not_found"
    assert not any(argv[:1] == ("install",) for argv in fake_adb.argvs())


def test_setup_ime_checksum_mismatch_blocks_install(one_device, fake_adb, monkeypatch):
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=IME_ABSENT)
    fake_adb.when("install", returns="Success\n")

    def tampered_download(url, destination):
        destination.write_bytes(b"tampered-bytes")
        return hashlib.sha256(b"tampered-bytes").hexdigest()

    monkeypatch.setattr(ime_setup, "download_apk", tampered_download)
    monkeypatch.setattr(ime_setup, "APK_EXPECTED_BYTES", len(b"tampered-bytes"))
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1")
    assert excinfo.value.code == "ime_checksum_mismatch"
    details = excinfo.value.details
    assert details["actual_sha256"] == hashlib.sha256(b"tampered-bytes").hexdigest()
    # a corrupted download must never reach the device
    assert not any(argv[:1] == ("install",) for argv in fake_adb.argvs())


def test_setup_ime_download_failure(one_device, fake_adb, monkeypatch):
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=IME_ABSENT)

    def fail(url, destination):
        raise MobileSkillError("ime_download_failed", "network is down", "retry")

    monkeypatch.setattr(ime_setup, "download_apk", fail)
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1")
    assert excinfo.value.code == "ime_download_failed"
    assert not any(argv[:1] == ("install",) for argv in fake_adb.argvs())


def test_download_apk_wraps_network_errors(tmp_path, monkeypatch):
    import urllib.error

    def fail_urlopen(url, timeout):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(ime_setup.urllib.request, "urlopen", fail_urlopen)
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.download_apk("https://example.invalid/x.apk", tmp_path / "x.apk")
    assert excinfo.value.code == "ime_download_failed"
    assert excinfo.value.details["url"] == "https://example.invalid/x.apk"


def test_setup_ime_install_failure(
    one_device, fake_adb, ime_appears_after_install, fake_download
):
    fake_adb.when("install", returns="Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n")
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1")
    assert excinfo.value.code == "ime_install_failed"
    assert "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in excinfo.value.details["adb_output"]


def test_setup_ime_transport_failure_marks_install_uncertain(
    one_device, fake_adb, ime_appears_after_install, fake_download
):
    fake_adb.when(
        "install",
        returns=android.AndroidError("adb disconnected", "adb_failed"),
    )
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1")
    assert excinfo.value.code == "ime_install_failed"
    assert excinfo.value.details["cause"] == "adb_failed"
    assert excinfo.value.details["action_may_have_applied"] is True


def test_setup_ime_verify_failure(one_device, fake_adb, fake_download, monkeypatch):
    # install reports Success but the IME never shows up in the list
    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=IME_ABSENT)
    fake_adb.when("install", returns="Success\n")
    # fast-forward the poll deadline so the test doesn't wait in real time
    ticks = {"n": 0}

    def fake_monotonic() -> float:
        ticks["n"] += 1
        return ticks["n"] * 2.0

    monkeypatch.setattr(ime_setup.time, "monotonic", fake_monotonic)
    with pytest.raises(MobileSkillError) as excinfo:
        ime_setup.setup_ime("emu-1")
    assert excinfo.value.code == "ime_verify_failed"


def test_setup_ime_waits_for_late_ime_registration(one_device, fake_adb, fake_download):
    # the IME registers in `ime list` a couple of polls after install
    fake_adb.when("install", returns="Success\n")
    calls = {"n": 0}

    def late_registration(args, serial, binary):
        calls["n"] += 1
        return IME_ABSENT if calls["n"] < 3 else IME_PRESENT

    fake_adb.when("shell", "ime", "list", "-s", "-a", returns=late_registration)
    report = ime_setup.setup_ime("emu-1")
    assert report["verified"] is True
    assert calls["n"] == 3


def test_setup_ime_env_url_override(
    one_device, fake_adb, ime_appears_after_install, fake_download, monkeypatch
):
    fake_adb.when("install", returns="Success\n")
    seen = {}
    original_download = ime_setup.download_apk

    def record_then_download(url, destination):
        seen["url"] = url
        return original_download(url, destination)

    monkeypatch.setattr(ime_setup, "download_apk", record_then_download)
    monkeypatch.setenv(ime_setup.IME_URL_ENV, "https://mirror.example/x.apk")
    report = ime_setup.setup_ime("emu-1")
    assert seen["url"] == "https://mirror.example/x.apk"
    assert report["source"] == "download"
