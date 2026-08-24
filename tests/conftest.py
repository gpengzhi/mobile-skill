"""Shared fixtures for mobile-skill tests.

Every test that touches state or ADB pulls from here so real hardware
is never contacted and the on-disk state root is per-test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def msk_home(tmp_path, monkeypatch):
    """Point mobile-skill state at a per-test tmpdir."""
    home = tmp_path / "state"
    monkeypatch.setenv("MOBILE_SKILL_HOME", str(home))
    return home


class FakeAdb:
    """Records `run_adb` calls and returns canned outputs.

    A rule matches on the leading positional arguments. First rule that
    matches wins; unmatched calls return an empty response so tests don't
    have to enumerate every incidental adb invocation.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rules: list[tuple[tuple[str, ...], Any]] = []

    def when(self, *prefix: str, returns: Any = "") -> None:
        """Register a rule keyed on the leading argv."""
        self._rules.append((prefix, returns))

    def __call__(self, *args: str, serial: str | None = None, binary: bool = False):
        self.calls.append({"args": args, "serial": serial, "binary": binary})
        for prefix, value in self._rules:
            if args[: len(prefix)] == prefix:
                if isinstance(value, BaseException):
                    raise value
                if callable(value):
                    value = value(args, serial, binary)
                if binary and isinstance(value, str):
                    return value.encode()
                if not binary and isinstance(value, bytes):
                    return value.decode()
                return value
        return b"" if binary else ""

    def argvs(self) -> list[tuple[str, ...]]:
        return [call["args"] for call in self.calls]


@pytest.fixture
def fake_adb(monkeypatch):
    """Replace `mobile_skill.android.run_adb` with a recording fake.

    Also replaces `time.sleep` inside the android module with a no-op so
    tests exercising delays (double_tap, ADBKeyboard) don't actually wait.
    """
    from mobile_skill import android

    adb = FakeAdb()
    monkeypatch.setattr(android, "run_adb", adb)
    sleeps: list[float] = []
    monkeypatch.setattr(android.time, "sleep", lambda seconds: sleeps.append(seconds))
    adb.sleeps = sleeps  # type: ignore[attr-defined]
    return adb


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT
