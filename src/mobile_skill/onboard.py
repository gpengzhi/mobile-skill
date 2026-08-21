"""First-run device onboarding: drive a connected phone to ready, then verify."""

from __future__ import annotations

import time
from typing import Any

from . import android, diagnostics
from .errors import MobileSkillError


POLL_INTERVAL_S = 1.0
RESTART_COOLDOWN_S = 15.0
VENDOR_AUTHORIZATION_HINT = (
    "On some vendors (MIUI/HyperOS, ColorOS, OriginOS), USB debugging "
    "authorization also requires the 'USB debugging (security settings)' "
    "toggle in Developer options. Check that if no authorization dialog appears."
)


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
            {"devices": devices},
        )
    serial = target["serial"]
    if target["state"] == "unauthorized":
        return MobileSkillError(
            "device_unauthorized",
            f"authorization for {serial} did not complete within {timeout_s} seconds",
            "unlock the phone, tap Allow on the USB debugging dialog, then retry",
            {"serial": serial, "vendor_hint": VENDOR_AUTHORIZATION_HINT},
        )
    if target["state"] == "offline":
        return MobileSkillError(
            "device_offline",
            f"device {serial} stayed offline for {timeout_s} seconds",
            "reconnect the phone or try another USB cable, then retry",
            {"serial": serial},
        )
    return MobileSkillError(
        "device_not_ready",
        f"device {serial} is {target['state']} after {timeout_s} seconds",
        "replug the phone, then retry",
        {"serial": serial, "state": target["state"]},
    )


def onboard(
    *, device: str | None = None, timeout_s: int = 60, retries: int = 1
) -> dict[str, Any]:
    if timeout_s < 0:
        raise MobileSkillError("invalid_timeout", "onboard timeout must not be negative")
    if not 0 <= retries <= 5:
        raise MobileSkillError(
            "invalid_retries", "onboard retries must be between 0 and 5"
        )
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    restarts_used = 0
    last_restart_at: float | None = None
    vendor_hint_emitted = False
    serial = device

    while True:
        devices = android.list_devices()
        target = _target_device(devices, device)
        if target is not None and target["state"] == "device":
            serial = target["serial"]
            events.append({"step": "device_ready", "serial": serial})
            break
        now = time.monotonic()
        if target is not None and target["state"] == "unauthorized" and not vendor_hint_emitted:
            events.append({"step": "vendor_hint", "message": VENDOR_AUTHORIZATION_HINT})
            vendor_hint_emitted = True
        can_restart = (
            target is not None
            and restarts_used < retries
            and (last_restart_at is None or now - last_restart_at >= RESTART_COOLDOWN_S)
        )
        if can_restart:
            events.append(
                {
                    "step": "restart_adb_server",
                    "reason": target["state"],
                    "attempt": restarts_used + 1,
                }
            )
            android.restart_server()
            restarts_used += 1
            last_restart_at = now
        if now >= deadline:
            raise _incomplete_error(devices, target, timeout_s)
        time.sleep(POLL_INTERVAL_S)

    report = diagnostics.doctor(serial=serial)
    return {"onboarding": events, **report}
