"""Install and verify the helper IME that enables Unicode (non-ASCII) typing.

The typing flow in `android._type_unicode_with_adb_keyboard` broadcasts text
through the AdbKeyboard input method bundled in openatx's
android-uiautomator-server releases. When that IME is missing the device can
only type ASCII; this module closes the loop by downloading the pinned
release (or accepting a local APK), installing it via `adb install`, and
verifying it shows up in `ime list`.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import android
from .errors import MobileSkillError

DEFAULT_APK_URL = (
    "https://github.com/openatx/android-uiautomator-server/releases/"
    "download/2.4.0/app-uiautomator.apk"
)
APK_SHA256 = "6f85594700ad96de89d012b3767049c2c6988510b68b31b439dd2a6dd93a30c9"
APK_EXPECTED_BYTES = 1_873_729
DOWNLOAD_TIMEOUT_S = 60
# Mirrors of the *same* pinned artifact can be swapped in for restricted
# networks; the sha256 is enforced on every download regardless of source.
IME_URL_ENV = "MOBILE_SKILL_IME_APK_URL"
# An IME can take a moment to register in `ime list` after `adb install`
# reports Success (observed on HyperOS), so verification polls briefly
# instead of trusting a single listing.
VERIFY_TIMEOUT_S = 5.0
VERIFY_POLL_INTERVAL_S = 0.25

_DOWNLOAD_CHUNK_BYTES = 64 * 1024


def download_apk(url: str, destination: Path) -> str:
    """Stream `url` to `destination`, returning the sha256 hex digest."""
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response, (
            destination.open("wb")
        ) as file:
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
                file.write(chunk)
    except (urllib.error.URLError, OSError) as error:
        raise MobileSkillError(
            "ime_download_failed",
            f"failed to download the helper IME APK from {url}: {error}",
            "check network access, or hand-download the APK and rerun "
            "`msk setup-ime --apk <file>`",
            {"url": url},
        ) from error
    return digest.hexdigest()


def _install_apk(serial: str, path: Path) -> None:
    # `adb install` can exit 0 while printing "Failure [...]" on stdout, so
    # judge success by the output text, not the exit code.
    try:
        output = android.run_action_adb("install", "-r", str(path), serial=serial)
    except android.AndroidError as error:
        details = {
            "adb_output": str(error),
            "cause": error.code,
            **error.details,
        }
        raise MobileSkillError(
            "ime_install_failed",
            "installing the helper IME APK failed; the install result is uncertain",
            "check whether the helper IME is present with `msk doctor`, then retry "
            "only if it is still missing",
            details,
        ) from error
    if "Success" not in output:
        raise MobileSkillError(
            "ime_install_failed",
            "installing the helper IME APK failed",
            "check device storage and 'Install via USB' in Developer options, "
            "then rerun `msk setup-ime`",
            {"adb_output": output.strip()},
        )


def _wait_for_ime_registration(serial: str) -> bool:
    deadline = time.monotonic() + VERIFY_TIMEOUT_S
    while True:
        if android.ADB_KEYBOARD_IME in android.installed_imes(serial):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(VERIFY_POLL_INTERVAL_S)


def setup_ime(serial: str | None = None, *, apk_path: str | None = None) -> dict[str, Any]:
    """Install the helper IME on `serial` if missing, and verify it registers.

    Already-installed devices are a no-op (no network, no install). With
    `apk_path` the given local APK is installed as-is, bypassing the pinned
    download and checksum; otherwise the pinned release is downloaded (URL
    overridable via MOBILE_SKILL_IME_APK_URL) and its sha256 is enforced.
    """
    serial = android.require_device(serial)
    if android.ADB_KEYBOARD_IME in android.installed_imes(serial):
        return {
            "device_id": serial,
            "ime": android.ADB_KEYBOARD_IME,
            "installed": False,
            "already_installed": True,
            "verified": True,
            "source": "none",
            "checksum_verified": False,
        }

    source: str
    checksum_verified = False
    if apk_path is not None:
        path = Path(apk_path)
        if not path.is_file():
            raise MobileSkillError(
                "apk_not_found",
                f"APK file not found: {apk_path}",
                "check the path, or rerun `msk setup-ime` without --apk to "
                "download the pinned release",
                {"apk_path": apk_path},
            )
        source = "local"
        _install_apk(serial, path)
    else:
        url = os.environ.get(IME_URL_ENV, DEFAULT_APK_URL)
        with tempfile.TemporaryDirectory(prefix="msk-ime-") as directory:
            apk = Path(directory) / "app-uiautomator.apk"
            digest = download_apk(url, apk)
            if digest != APK_SHA256 or apk.stat().st_size != APK_EXPECTED_BYTES:
                raise MobileSkillError(
                    "ime_checksum_mismatch",
                    "downloaded APK does not match the pinned sha256",
                    "the download was corrupted or the mirror serves a "
                    f"different file; hand-download {DEFAULT_APK_URL} and rerun "
                    "`msk setup-ime --apk <file>`",
                    {
                        "url": url,
                        "expected_sha256": APK_SHA256,
                        "actual_sha256": digest,
                        "expected_bytes": APK_EXPECTED_BYTES,
                        "actual_bytes": apk.stat().st_size,
                    },
                )
            _install_apk(serial, apk)
        source = "download"
        checksum_verified = True

    if not _wait_for_ime_registration(serial):
        raise MobileSkillError(
            "ime_verify_failed",
            "the helper IME did not appear in `adb shell ime list -s -a` "
            "after install",
            "rerun `msk setup-ime`; if it persists, enable 'Install via USB' "
            "in Developer options and retry",
            {"serial": serial},
        )
    return {
        "device_id": serial,
        "ime": android.ADB_KEYBOARD_IME,
        "installed": True,
        "already_installed": False,
        "verified": True,
        "source": source,
        "checksum_verified": checksum_verified,
    }
