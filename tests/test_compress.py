"""android.compress_for_model — exercises Pillow, no ADB."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from mobile_skill import android
from mobile_skill.android import AndroidError


def _real_png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(30, 60, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_compress_downscales_width_and_preserves_ratio(tmp_path: Path) -> None:
    source = _real_png(2000, 4000)
    output = tmp_path / "out.jpg"
    _, size = android.compress_for_model(source, output, target_width=500)
    assert size == (500, 1000)
    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (500, 1000)
        assert image.format == "JPEG"


def test_compress_does_not_upscale(tmp_path: Path) -> None:
    source = _real_png(300, 600)
    output = tmp_path / "out.jpg"
    _, size = android.compress_for_model(source, output, target_width=1000)
    # target_width is clamped to source width
    assert size == (300, 600)


def test_compress_reads_from_disk(tmp_path: Path) -> None:
    input_path = tmp_path / "in.png"
    input_path.write_bytes(_real_png(400, 200))
    output = tmp_path / "out.jpg"
    _, size = android.compress_for_model(input_path, output, target_width=200)
    assert size == (200, 100)


def test_compress_rejects_zero_target_width(tmp_path: Path) -> None:
    with pytest.raises(AndroidError):
        android.compress_for_model(_real_png(100, 100), tmp_path / "x.jpg", target_width=0)


@pytest.mark.parametrize("quality", [0, 96, 200])
def test_compress_rejects_bad_quality(tmp_path: Path, quality: int) -> None:
    with pytest.raises(AndroidError):
        android.compress_for_model(
            _real_png(100, 100), tmp_path / "x.jpg", target_width=50, quality=quality
        )


def test_compress_creates_output_parent(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "dir" / "out.jpg"
    android.compress_for_model(_real_png(200, 200), output, target_width=100)
    assert output.exists()
