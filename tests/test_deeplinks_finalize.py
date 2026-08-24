"""finalize_open_url: landing verification + learned-registry recording."""

from __future__ import annotations

import json
import threading

import pytest

from mobile_skill import deeplinks


def _learned(msk_home) -> dict:
    return json.loads(deeplinks.learned_registry_path().read_text())


def test_verified_writes_learned_entry(fake_adb, msk_home) -> None:
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 tv.danmaku.bili/.MainActivity\n",
    )
    result = deeplinks.finalize_open_url(
        "emu-1",
        "bilibili://space/12345678",
        expected_activity="tv.danmaku.bili/.IntentHandlerActivity",
    )
    assert result["outcome"] == "verified"
    assert result["recorded"] is True
    # curated has bilibili://space/{mid}; finalize adopts that named form
    assert result["template"] == "bilibili://space/{mid}"

    entry = _learned(msk_home)["apps"]["tv.danmaku.bili"]["entries"][0]
    assert entry["url"] == "bilibili://space/{mid}"
    assert entry["invocations"] == 1
    assert entry["verified"] == 1
    assert entry["hijacked"] == 0


def test_hijacked_counter(fake_adb, msk_home) -> None:
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 com.other.pkg/.Main\n",
    )
    result = deeplinks.finalize_open_url(
        "emu-1",
        "bilibili://space/12345678",
        expected_activity="tv.danmaku.bili/.Main",
    )
    assert result["outcome"] == "hijacked"
    entry = _learned(msk_home)["apps"]["tv.danmaku.bili"]["entries"][0]
    assert entry["hijacked"] == 1
    assert entry["verified"] == 0


def test_unknown_when_no_foreground(fake_adb, msk_home) -> None:
    fake_adb.when("shell", "dumpsys", "activity", "activities", returns="\n")
    result = deeplinks.finalize_open_url(
        "emu-1", "bilibili://space/12345678", expected_activity="tv.danmaku.bili/.Main"
    )
    assert result["outcome"] == "unknown"
    entry = _learned(msk_home)["apps"]["tv.danmaku.bili"]["entries"][0]
    assert entry["unknown"] == 1


def test_adopts_curated_named_placeholders(fake_adb, msk_home) -> None:
    """When curated has {keyword} for the same shape, learned adopts that
    named form instead of the generic {keyword} produced by normalize."""
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 tv.danmaku.bili/.SearchActivity\n",
    )
    deeplinks.finalize_open_url(
        "emu-1",
        "bilibili://search?keyword=Minecraft",
        expected_activity="tv.danmaku.bili/.SearchActivity",
    )
    entry = _learned(msk_home)["apps"]["tv.danmaku.bili"]["entries"][0]
    assert entry["url"] == "bilibili://search?keyword={keyword}"  # curated form


def test_sensitive_non_curated_not_recorded(fake_adb, msk_home) -> None:
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 com.example/.M\n",
    )
    result = deeplinks.finalize_open_url(
        "emu-1", "custom://pay/12345", expected_activity="com.example/.M"
    )
    assert result["recorded"] is False
    assert not deeplinks.learned_registry_path().exists()


def test_alipay_curated_gets_recorded(fake_adb, msk_home) -> None:
    """Alipay's URL contains `pay` but matches curated → learned records it."""
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 com.eg.android.AlipayGphone/.SLA\n",
    )
    result = deeplinks.finalize_open_url(
        "emu-1",
        "alipays://platformapi/startapp?appId=10000007",
        expected_activity="com.eg.android.AlipayGphone/.SLA",
    )
    assert result["recorded"] is True


def test_finalize_never_raises_on_write_failure(fake_adb, msk_home, monkeypatch) -> None:
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 tv.danmaku.bili/.M\n",
    )

    def boom(_data):
        raise OSError("disk full")

    monkeypatch.setattr(deeplinks, "_write_learned", boom)
    result = deeplinks.finalize_open_url(
        "emu-1", "bilibili://space/1", expected_activity="tv.danmaku.bili/.M"
    )
    assert result["recorded"] is False
    assert "disk full" in result["error"]


def test_concurrent_writes_serialize(fake_adb, msk_home) -> None:
    """Two threads recording simultaneously must both land counter increments.

    fcntl.flock in finalize_open_url makes the read-check-write atomic; we
    verify by pointing dumpsys at the same activity twice and asserting the
    final invocations counter equals the number of concurrent callers.
    """
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="topResumedActivity=Token{x} u0 tv.danmaku.bili/.M\n",
    )

    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        deeplinks.finalize_open_url(
            "emu-1", "bilibili://space/999", expected_activity="tv.danmaku.bili/.M"
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entry = _learned(msk_home)["apps"]["tv.danmaku.bili"]["entries"][0]
    assert entry["invocations"] == 2
    assert entry["verified"] == 2
