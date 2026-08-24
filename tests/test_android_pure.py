"""Pure-function tests for android helpers — no subprocess, no filesystem."""

from __future__ import annotations

import struct

import pytest

from mobile_skill import android
from mobile_skill.android import AndroidError


def _fake_png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\x0dIHDR"
        + struct.pack(">II", width, height)
        + b"\x00" * 100
    )


def test_png_size_parses_dimensions() -> None:
    assert android.png_size(_fake_png(1080, 2400)) == (1080, 2400)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not a png",
        b"\x89PNG\r\n\x1a\n" + b"XXXX" + b"\x00" * 20,  # magic ok, IHDR missing
    ],
)
def test_png_size_rejects_bad_input(payload: bytes) -> None:
    with pytest.raises(AndroidError):
        android.png_size(payload)


@pytest.mark.parametrize(
    "raw, quoted",
    [
        ("plain", "'plain'"),
        ("with space", "'with space'"),
        ("it's fine", "'it'\\''s fine'"),
        ("", "''"),
        ("a'b'c", "'a'\\''b'\\''c'"),
    ],
)
def test_shell_quote(raw: str, quoted: str) -> None:
    assert android.shell_quote(raw) == quoted


def test_validate_point_accepts_bounds() -> None:
    android.validate_point(0, 0, 100, 200)
    android.validate_point(99, 199, 100, 200)


@pytest.mark.parametrize("x, y", [(-1, 0), (0, -1), (100, 0), (0, 200)])
def test_validate_point_rejects_out_of_bounds(x: int, y: int) -> None:
    with pytest.raises(AndroidError):
        android.validate_point(x, y, 100, 200)


@pytest.mark.parametrize(
    "text, needs",
    [
        ("hello world", False),
        ("abc123", False),
        ("!@#$%^&*()", False),
        ("has\ttab", True),  # control char
        ("has%sliteral", True),
        ("中文", True),
        ("emoji😀", True),
        ("café", True),
        ("\x7f", True),  # DEL
        ("", False),
    ],
)
def test_needs_ime(text: str, needs: bool) -> None:
    assert android._needs_ime(text) is needs


def test_keys_covers_common_aliases() -> None:
    assert android.KEYS["enter"] == "ENTER"
    assert android.KEYS["return"] == "ENTER"
    assert android.KEYS["recents"] == "APP_SWITCH"
    assert android.KEYS["backspace"] == "DEL"
    assert android.KEYS["delete"] == "DEL"
