"""Registry loading, merging, forgetting — filesystem only, no ADB."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mobile_skill import deeplinks


def test_curated_registry_matches_readme_counts(project_root: Path) -> None:
    """README advertises 25 templates across 9 apps."""
    registry = deeplinks.load_curated_registry()
    apps = registry["apps"]
    assert len(apps) == 9
    total_entries = sum(len(spec.get("entries", [])) for spec in apps.values())
    assert total_entries == 25


@pytest.mark.parametrize(
    "app_pkg",
    [
        "tv.danmaku.bili",
        "com.taobao.taobao",
        "com.tencent.mm",
        "com.eg.android.AlipayGphone",
        "com.autonavi.minimap",
        "com.sina.weibo",
        "com.zhihu.android",
        "com.smile.gifmaker",
        "com.taobao.idlefish",
    ],
)
def test_curated_registry_has_expected_app(app_pkg: str) -> None:
    apps = deeplinks.load_curated_registry()["apps"]
    assert app_pkg in apps
    assert apps[app_pkg]["display_name"]
    assert apps[app_pkg]["entries"]


def test_curated_registry_paths_have_no_concrete_ids() -> None:
    """Curated path segments must not look like IDs — that's what would make a
    learned entry shape-collide with a curated one on the wrong axis. Query
    values are exempt: some curated entries deliberately pin constants (Alipay's
    `appId=10000007`, Amap's `t=0`)."""
    from urllib.parse import urlparse

    for spec in deeplinks.load_curated_registry()["apps"].values():
        for entry in spec["entries"]:
            path = urlparse(entry["url"]).path
            for segment in path.split("/"):
                assert not deeplinks._looks_like_id(segment), (
                    f"curated path segment {segment!r} looks id-shaped: {entry['url']}"
                )


def test_learned_registry_missing_returns_empty(msk_home: Path) -> None:
    assert deeplinks.load_learned_registry() == {"apps": {}}


def test_learned_registry_corrupt_returns_empty(msk_home: Path) -> None:
    path = deeplinks.learned_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not{json")
    assert deeplinks.load_learned_registry() == {"apps": {}}


def test_learned_registry_wrong_shape_returns_empty(msk_home: Path) -> None:
    path = deeplinks.learned_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"apps": "not-a-dict"}))
    assert deeplinks.load_learned_registry() == {"apps": {}}


def _seed_learned(path: Path, apps: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "apps": apps}))


def test_merged_registry_curated_only(msk_home: Path) -> None:
    result = deeplinks.merged_registry("tv.danmaku.bili")
    assert len(result) == 1
    entry = result[0]
    assert entry["package"] == "tv.danmaku.bili"
    assert all(e["source"] == "curated" for e in entry["entries"])


def test_merged_registry_overlay_counters(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "tv.danmaku.bili": {"entries": [
            {"url": "bilibili://search?keyword={keyword}",
             "invocations": 3, "verified": 2, "hijacked": 1},
        ]},
    })
    result = deeplinks.merged_registry("tv.danmaku.bili")
    search_entry = next(
        e for e in result[0]["entries"] if e["url"] == "bilibili://search?keyword={keyword}"
    )
    assert search_entry["source"] == "curated"
    assert search_entry["invocations"] == 3
    assert search_entry["verified"] == 2
    assert search_entry["hijacked"] == 1


def test_merged_registry_learned_only_package(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.unknown.app": {"entries": [
            {"url": "unknownapp://foo/{...}", "invocations": 1, "verified": 1},
        ]},
    })
    result = deeplinks.merged_registry("com.unknown.app")
    assert len(result) == 1
    assert result[0]["package"] == "com.unknown.app"
    assert result[0]["entries"][0]["source"] == "learned"


def test_merged_registry_filter_missing_package(msk_home: Path) -> None:
    result = deeplinks.merged_registry("does.not.exist")
    assert len(result) == 1
    assert result[0]["package"] == "does.not.exist"
    assert result[0]["entries"] == []
    assert result[0]["display_name"] is None


def test_merged_registry_no_filter_lists_all(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.custom.app": {"entries": [
            {"url": "custom://x/{...}"},
        ]},
    })
    result = deeplinks.merged_registry()
    packages = {entry["package"] for entry in result}
    assert "com.custom.app" in packages
    assert "tv.danmaku.bili" in packages  # curated


def test_forget_specific_url(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.pkg": {"entries": [
            {"url": "pkg://a/{...}", "invocations": 1},
            {"url": "pkg://b/{...}", "invocations": 1},
        ]},
    })
    result = deeplinks.forget_learned_url("pkg://a/{...}")
    assert result["forgotten"] == [{"package": "com.pkg", "url": "pkg://a/{...}"}]
    remaining = deeplinks.load_learned_registry()["apps"]["com.pkg"]["entries"]
    assert [e["url"] for e in remaining] == ["pkg://b/{...}"]


def test_forget_removes_empty_package(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.pkg": {"entries": [{"url": "pkg://only/{...}"}]},
    })
    deeplinks.forget_learned_url("pkg://only/{...}")
    assert "com.pkg" not in deeplinks.load_learned_registry()["apps"]


def test_forget_scoped_to_package(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.pkg.a": {"entries": [{"url": "same://{...}"}]},
        "com.pkg.b": {"entries": [{"url": "same://{...}"}]},
    })
    result = deeplinks.forget_learned_url("same://{...}", package="com.pkg.a")
    assert result["forgotten"] == [{"package": "com.pkg.a", "url": "same://{...}"}]
    apps = deeplinks.load_learned_registry()["apps"]
    assert "com.pkg.a" not in apps  # became empty
    assert "com.pkg.b" in apps


def test_forget_unknown_url_no_op(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.pkg": {"entries": [{"url": "pkg://a"}]},
    })
    result = deeplinks.forget_learned_url("pkg://missing")
    assert result["forgotten"] == []
    apps = deeplinks.load_learned_registry()["apps"]
    assert apps["com.pkg"]["entries"][0]["url"] == "pkg://a"


def test_reset_learned_clears_file(msk_home: Path) -> None:
    _seed_learned(deeplinks.learned_registry_path(), {
        "com.a": {"entries": [{"url": "a://x"}, {"url": "a://y"}]},
        "com.b": {"entries": [{"url": "b://x"}]},
    })
    result = deeplinks.reset_learned()
    assert result == {"cleared_apps": 2, "cleared_entries": 3}
    assert deeplinks.load_learned_registry() == {"version": 1, "apps": {}}


def test_reset_learned_leaves_curated_untouched(msk_home: Path, project_root: Path) -> None:
    curated_before = json.loads(deeplinks.curated_registry_path().read_text())
    deeplinks.reset_learned()
    curated_after = json.loads(deeplinks.curated_registry_path().read_text())
    assert curated_before == curated_after
