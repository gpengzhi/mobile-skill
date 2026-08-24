"""Deep-link discovery and invocation — ADB replaced by FakeAdb."""

from __future__ import annotations

import pytest

from mobile_skill import deeplinks
from mobile_skill.errors import MobileSkillError


def test_parse_schemes_extracts_and_sorts(fake_adb) -> None:
    fake_adb.when("shell", "pm", "list", "packages", returns="package:com.example\n")
    fake_adb.when(
        "shell", "dumpsys", "package",
        returns=(
            'Scheme: "bilibili"\n'
            '  Scheme: "http"\n'
            '  Scheme: "https"\n'
            '  Authority: "example.com:"\n'
            '  Authority: "example.com:"\n'
            '  Authority: "www.example.com:"\n'
        ),
    )
    result = deeplinks.parse_schemes("emu-1", "com.example")
    assert result["package"] == "com.example"
    assert result["schemes"] == ["bilibili", "http", "https"]
    assert result["https_hosts"] == ["example.com", "www.example.com"]


def test_resolve_url_returns_activity(fake_adb) -> None:
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="priority=0 preferredOrder=0\ncom.example/.MainActivity\n",
    )
    assert deeplinks.resolve_url("emu-1", "example://foo") == "com.example/.MainActivity"


def test_resolve_url_no_match(fake_adb) -> None:
    fake_adb.when("shell", "cmd", "package", "resolve-activity", returns="No Activity found\n")
    assert deeplinks.resolve_url("emu-1", "example://foo") is None


def test_resolve_current_foreground_activity(fake_adb) -> None:
    fake_adb.when(
        "shell", "dumpsys", "activity", "activities",
        returns="  topResumedActivity=Token{x} u0 com.example/.MainActivity t42\n",
    )
    assert (
        deeplinks.resolve_current_foreground_activity("emu-1") == "com.example/.MainActivity"
    )


def test_resolve_current_foreground_no_match(fake_adb) -> None:
    fake_adb.when("shell", "dumpsys", "activity", "activities", returns="nothing here\n")
    assert deeplinks.resolve_current_foreground_activity("emu-1") is None


def test_open_url_happy_path(fake_adb) -> None:
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="com.example/.MainActivity\n",
    )
    result = deeplinks.open_url("emu-1", "example://foo")
    assert result == {"url": "example://foo", "resolved_activity": "com.example/.MainActivity"}
    starts = [c for c in fake_adb.calls if c["args"][:4] == ("shell", "am", "start", "-a")]
    assert starts and starts[-1]["args"][4] == "android.intent.action.VIEW"


def test_open_url_unresolvable(fake_adb) -> None:
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="No Activity found\n",
    )
    with pytest.raises(MobileSkillError) as excinfo:
        deeplinks.open_url("emu-1", "example://foo")
    assert excinfo.value.code == "deeplink_unresolvable"


def test_open_url_sensitive_non_curated_blocked(fake_adb) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        deeplinks.open_url("emu-1", "example://pay/anything")
    assert excinfo.value.code == "deeplink_requires_human"


def test_open_url_alipay_curated_allowed(fake_adb) -> None:
    """Alipay's `appId=10000007` scheme URL contains `pay` but is curated."""
    fake_adb.when(
        "shell", "cmd", "package", "resolve-activity",
        returns="com.eg.android.AlipayGphone/.SchemeLauncherActivity\n",
    )
    result = deeplinks.open_url(
        "emu-1", "alipays://platformapi/startapp?appId=10000007"
    )
    assert result["url"] == "alipays://platformapi/startapp?appId=10000007"


@pytest.mark.parametrize("bad", ["", " padded ", "\ttab\t"])
def test_open_url_rejects_bad_input(bad: str, fake_adb) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        deeplinks.open_url("emu-1", bad)
    assert excinfo.value.code == "invalid_url"
