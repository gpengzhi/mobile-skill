"""Pure-function tests for deeplinks URL machinery — no filesystem, no ADB."""

from __future__ import annotations

import pytest

from mobile_skill import deeplinks


@pytest.mark.parametrize(
    "url, expected",
    [
        ("bilibili://search?keyword=Minecraft", "bilibili://search?keyword={keyword}"),
        ("bilibili://space/12345678", "bilibili://space/{...}"),
        ("bilibili://video/BV1xx411c7mu", "bilibili://video/{...}"),
        ("bilibili://article/98765", "bilibili://article/{...}"),
        (
            "bilibili://video/BV1xx411c7mu?tab=hot&from=list",
            "bilibili://video/{...}?tab={tab}&from={from}",
        ),
        ("weixin://scanqrcode", "weixin://scanqrcode"),
        ("bilibili://user_center", "bilibili://user_center"),
        (
            "androidamap://viewMap?lat=39.9&lon=116.4&dev=0",
            "androidamap://viewMap?lat={lat}&lon={lon}&dev={dev}",
        ),
        ("app://x#fragment123", "app://x#{...}"),
        (
            "alipays://platformapi/startapp?appId=10000007",
            "alipays://platformapi/startapp?appId={appId}",
        ),
    ],
)
def test_normalize_to_template(url: str, expected: str) -> None:
    assert deeplinks.normalize_to_template(url) == expected


@pytest.mark.parametrize(
    "template, valid",
    [
        ("bilibili://search?keyword={keyword}", True),
        ("bilibili://space/{...}", True),
        ("weixin://scanqrcode", True),
        ("bilibili://space/12345678", False),  # numeric segment is dynamic
        ("bilibili://video/BV1xx", False),  # BV-shaped segment is dynamic
        ("zhihu://search?q=Minecraft", False),  # concrete query value
        ("app://x#literal", False),  # concrete fragment
    ],
)
def test_passes_template_invariant(template: str, valid: bool) -> None:
    assert deeplinks.passes_template_invariant(template) is valid


@pytest.mark.parametrize(
    "concrete, template, matches",
    [
        ("bilibili://search?keyword=Minecraft", "bilibili://search?keyword={keyword}", True),
        ("bilibili://space/12345678", "bilibili://space/{...}", True),
        (
            "bilibili://space/12345678",
            "bilibili://video/{...}",
            False,
        ),
        ("weixin://scanqrcode", "weixin://scanqrcode", True),
        ("weixin://scanqr", "weixin://scanqrcode", False),
    ],
)
def test_url_matches_template(concrete: str, template: str, matches: bool) -> None:
    assert deeplinks.url_matches_template(concrete, template) is matches


def test_canonical_shape_collapses_placeholder_names() -> None:
    a = deeplinks._canonical_shape("bilibili://space/{...}")
    b = deeplinks._canonical_shape("bilibili://space/{mid}")
    assert a == b


@pytest.mark.parametrize(
    "segment, id_like",
    [
        ("12345", True),
        ("BV1xx411c7mu", True),
        ("av42", True),
        ("AV42", True),
        ("deadbeefcafebabe", True),  # 16 hex chars
        ("user123abc456", True),  # opaque with digits
        ("search", False),
        ("scanqrcode", False),
        ("", False),
        ("short", False),
    ],
)
def test_looks_like_id(segment: str, id_like: bool) -> None:
    assert deeplinks._looks_like_id(segment) is id_like


@pytest.mark.parametrize(
    "expected, actual, outcome",
    [
        ("com.pkg/.Main", "com.pkg/.Other", "verified"),
        ("com.pkg/.A", "com.other/.A", "hijacked"),
        ("com.pkg/.A", None, "unknown"),
        (None, "com.pkg/.A", "unknown"),
        (None, None, "unknown"),
    ],
)
def test_classify_outcome(expected: str | None, actual: str | None, outcome: str) -> None:
    assert deeplinks.classify_outcome(expected, actual) == outcome


@pytest.mark.parametrize(
    "url, sensitive",
    [
        ("weixin://pay?...", True),
        ("app://transfer/1", True),
        ("wechat://send?to=x", True),
        ("weibo://publish", True),
        ("x://share", True),
        ("alipays://platformapi/startapp?appId=10000007", True),  # matches "pay"
        ("bilibili://search?keyword=x", False),
        ("zhihu://feed", False),
    ],
)
def test_is_sensitive_url(url: str, sensitive: bool) -> None:
    assert deeplinks.is_sensitive_url(url) is sensitive


@pytest.mark.parametrize(
    "activity, package",
    [
        ("com.example/.MainActivity", "com.example"),
        ("com.example/com.example.MainActivity", "com.example"),
        ("no-slash", ""),
        ("", ""),
    ],
)
def test_package_of_activity(activity: str, package: str) -> None:
    assert deeplinks._package_of_activity(activity) == package
