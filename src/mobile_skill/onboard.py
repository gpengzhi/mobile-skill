"""First-run device onboarding: drive a connected phone to ready, then verify."""

from __future__ import annotations

import time
from typing import Any

from . import android, diagnostics
from .errors import MobileSkillError


POLL_INTERVAL_S = 1.0


def _target_device(
    devices: list[dict[str, str]], wanted: str | None
) -> dict[str, str] | None:
    if wanted:
        return next((device for device in devices if device["serial"] == wanted), None)
    ready = [device for device in devices if device["state"] == "device"]
    if len(ready) == 1:
        return ready[0]
    if not ready and len(devices) == 1:
        return devices[0]
    if not devices:
        return None
    serials = ", ".join(device["serial"] for device in devices)
    raise MobileSkillError(
        "device_ambiguous",
        f"multiple Android devices are connected; pass --device: {serials}",
    )


def _incomplete_error(
    devices: list[dict[str, str]],
    target: dict[str, str] | None,
    timeout_s: int,
) -> MobileSkillError:
    states = ", ".join(f"{device['serial']}={device['state']}" for device in devices) or "none"
    if target is None:
        return MobileSkillError(
            "device_not_found",
            f"no Android device became ready within {timeout_s} seconds; adb sees: {states}",
            "plug in the phone over USB and enable USB debugging, then retry",
        )
    serial = target["serial"]
    if target["state"] == "unauthorized":
        return MobileSkillError(
            "device_unauthorized",
            f"authorization for {serial} did not complete within {timeout_s} seconds",
            "unlock the phone, tap Allow on the USB debugging dialog, then retry",
        )
    if target["state"] == "offline":
        return MobileSkillError(
            "device_offline",
            f"device {serial} stayed offline for {timeout_s} seconds",
            "reconnect the phone or try another USB cable, then retry",
        )
    return MobileSkillError(
        "device_not_ready",
        f"device {serial} is {target['state']} after {timeout_s} seconds",
        "replug the phone, then retry",
    )


def onboard(*, device: str | None = None, timeout_s: int = 60) -> dict[str, Any]:
    if timeout_s < 0:
        raise MobileSkillError("invalid_timeout", "onboard timeout must not be negative")
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    restarted = False
    serial = device

    while True:
        devices = android.list_devices()
        target = _target_device(devices, device)
        if target is not None and target["state"] == "device":
            serial = target["serial"]
            events.append({"step": "device_ready", "serial": serial})
            break
        if target is not None and not restarted:
            events.append({"step": "restart_adb_server", "reason": target["state"]})
            android.restart_server()
            restarted = True
        if time.monotonic() >= deadline:
            raise _incomplete_error(devices, target, timeout_s)
        time.sleep(POLL_INTERVAL_S)

    report = diagnostics.doctor(serial=serial)
    return {"onboarding": events, **report}
