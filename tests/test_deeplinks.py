"""Unit tests for the deep-link normalizer, template invariant, and matcher.

No external test framework. Run with:
    PYTHONPATH=src python3 tests/test_deeplinks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mobile_skill.deeplinks import (  # noqa: E402
    classify_outcome,
    normalize_to_template,
    passes_template_invariant,
    url_matches_template,
)


def _assert_eq(actual, expected, label):
    if actual != expected:
        print(f"FAIL  {label}")
        print(f"  expected: {expected!r}")
        print(f"  actual:   {actual!r}")
        return False
    print(f"ok    {label}")
    return True


def _assert_true(cond, label):
    if not cond:
        print(f"FAIL  {label}")
        return False
    print(f"ok    {label}")
    return True


passed = 0
failed = 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1


# --- normalize_to_template ---

check(
    _assert_eq(
        normalize_to_template("bilibili://search?keyword=Minecraft"),
        "bilibili://search?keyword={keyword}",
        "search query value → placeholder",
    ),
    "normalize_search",
)

check(
    _assert_eq(
        normalize_to_template("bilibili://space/12345678"),
        "bilibili://space/{...}",
        "numeric path segment → placeholder",
    ),
    "normalize_space",
)

check(
    _assert_eq(
        normalize_to_template("bilibili://video/BV1xx411c7mu"),
        "bilibili://video/{...}",
        "BV id path segment → placeholder",
    ),
    "normalize_video_bv",
)

check(
    _assert_eq(
        normalize_to_template("bilibili://video/BV1xx411c7mu?tab=hot"),
        "bilibili://video/{...}?tab={tab}",
        "BV path + tab query value",
    ),
    "normalize_video_with_tab",
)

check(
    _assert_eq(
        normalize_to_template("weixin://scanqrcode"),
        "weixin://scanqrcode",
        "no variables → identity",
    ),
    "normalize_no_vars",
)

check(
    _assert_eq(
        normalize_to_template("alipays://platformapi/startapp?appId=10000007"),
        "alipays://platformapi/startapp?appId={appId}",
        "alipay appId query value → placeholder (known false-positive)",
    ),
    "normalize_alipay_appid",
)

check(
    _assert_eq(
        normalize_to_template("bilibili://live/12345"),
        "bilibili://live/{...}",
        "short numeric path → placeholder",
    ),
    "normalize_live",
)

check(
    _assert_eq(
        normalize_to_template("myapp://user/user123abc/settings"),
        "myapp://user/{...}/settings",
        "opaque long path segment with digit → placeholder; route names preserved",
    ),
    "normalize_opaque_id",
)

check(
    _assert_eq(
        normalize_to_template("myapp://foo123bar"),
        "myapp://foo123bar",
        "netloc is NOT normalized (design choice: netloc = capability name)",
    ),
    "normalize_leaves_netloc",
)

check(
    _assert_eq(
        normalize_to_template("myapp://profile"),
        "myapp://profile",
        "single short host → identity",
    ),
    "normalize_short_host",
)


# --- passes_template_invariant ---

check(
    _assert_true(
        passes_template_invariant("bilibili://search?keyword={keyword}"),
        "template with query placeholder passes",
    ),
    "invariant_template_ok",
)

check(
    _assert_true(
        passes_template_invariant("bilibili://space/{...}"),
        "template with path placeholder passes",
    ),
    "invariant_placeholder_ok",
)

check(
    _assert_true(
        passes_template_invariant("weixin://scanqrcode"),
        "template with no variables passes",
    ),
    "invariant_novar_ok",
)

check(
    _assert_true(
        not passes_template_invariant("bilibili://space/12345678"),
        "concrete numeric ID fails invariant",
    ),
    "invariant_concrete_numeric_rejected",
)

check(
    _assert_true(
        not passes_template_invariant("bilibili://video/BV1xx411c7mu"),
        "concrete BV id fails invariant",
    ),
    "invariant_concrete_bv_rejected",
)

check(
    _assert_true(
        not passes_template_invariant("bilibili://search?keyword=Minecraft"),
        "concrete query value fails invariant",
    ),
    "invariant_concrete_query_rejected",
)


# --- url_matches_template ---

check(
    _assert_true(
        url_matches_template(
            "bilibili://search?keyword=Minecraft",
            "bilibili://search?keyword={keyword}",
        ),
        "query template matches concrete",
    ),
    "matches_query_template",
)

check(
    _assert_true(
        url_matches_template(
            "bilibili://space/12345678",
            "bilibili://space/{...}",
        ),
        "path template matches concrete",
    ),
    "matches_path_template",
)

check(
    _assert_true(
        not url_matches_template(
            "bilibili://space/12345678",
            "bilibili://search?keyword={keyword}",
        ),
        "different structure does not match",
    ),
    "no_match_different_structure",
)

check(
    _assert_true(
        url_matches_template(
            "bilibili://search?keyword={keyword}",
            "bilibili://search?keyword={keyword}",
        ),
        "template matches itself",
    ),
    "matches_self",
)

check(
    _assert_true(
        url_matches_template(
            "alipays://platformapi/startapp?appId=10000007",
            "alipays://platformapi/startapp?appId=10000007",
        ),
        "exact-literal curated URL matches itself",
    ),
    "matches_literal_curated",
)

check(
    _assert_true(
        not url_matches_template(
            "alipays://platformapi/startapp?appId=20000067",
            "alipays://platformapi/startapp?appId=10000007",
        ),
        "different appId does not match literal curated",
    ),
    "no_match_different_appid",
)


# --- classify_outcome ---

check(
    _assert_eq(
        classify_outcome(
            "tv.danmaku.bili/.ui.intent.IntentHandlerActivity",
            "tv.danmaku.bili/.ui.intent.IntentHandlerActivity",
        ),
        "verified",
        "exact activity match → verified",
    ),
    "outcome_verified",
)

check(
    _assert_eq(
        classify_outcome(
            "tv.danmaku.bili/.ui.intent.IntentHandlerActivity",
            "tv.danmaku.bili/com.bilibili.search2.main.BiliMainSearchActivity",
        ),
        "verified",
        "same package but different activity → verified (VIEW routed through dispatcher)",
    ),
    "outcome_router_forward",
)

check(
    _assert_eq(
        classify_outcome(
            "tv.danmaku.bili/.ui.intent.IntentHandlerActivity",
            "com.miui.home/.launcher.Launcher",
        ),
        "hijacked",
        "different package → hijacked",
    ),
    "outcome_hijacked",
)

check(
    _assert_eq(
        classify_outcome("tv.danmaku.bili/.foo", None),
        "unknown",
        "actual missing → unknown",
    ),
    "outcome_unknown",
)


# --- forget / reset_learned (uses MOBILE_SKILL_HOME isolation) ---

import os
import tempfile
import importlib


with tempfile.TemporaryDirectory() as tmp_home:
    os.environ["MOBILE_SKILL_HOME"] = tmp_home
    # Reload deeplinks to pick up the new home
    import mobile_skill.deeplinks as dl  # noqa: E402
    importlib.reload(dl)

    # Seed a fake learned file
    Path(tmp_home).mkdir(parents=True, exist_ok=True)
    seed = {
        "version": 1,
        "apps": {
            "tv.danmaku.bili": {
                "entries": [
                    {"url": "bilibili://search?keyword={keyword}", "invocations": 3, "verified": 3},
                    {"url": "bilibili://space/{mid}", "invocations": 1, "verified": 1},
                ],
            },
            "com.other.app": {
                "entries": [{"url": "other://feed", "invocations": 5, "verified": 5}],
            },
        },
    }
    dl._write_learned(seed)

    # forget a specific URL
    r = dl.forget_learned_url("bilibili://space/{mid}")
    check(_assert_eq(len(r["forgotten"]), 1, "forget removes one entry"), "forget_one")
    after = dl.load_learned_registry()
    check(
        _assert_eq(
            len(after["apps"]["tv.danmaku.bili"]["entries"]), 1, "bilibili has 1 entry left"
        ),
        "forget_leaves_one",
    )

    # forget nonexistent URL
    r = dl.forget_learned_url("does-not-exist://foo")
    check(_assert_eq(r["forgotten"], [], "forget missing URL is no-op"), "forget_missing")

    # reset wipes everything
    r = dl.reset_learned()
    check(_assert_eq(r["cleared_apps"], 2, "reset reports 2 apps cleared"), "reset_cleared_apps")
    after = dl.load_learned_registry()
    check(_assert_eq(after, {"version": 1, "apps": {}}, "learned empty after reset"), "reset_wipes")

    # forget on empty file is safe
    r = dl.forget_learned_url("anything://foo")
    check(_assert_eq(r["forgotten"], [], "forget on empty is no-op"), "forget_on_empty")

    del os.environ["MOBILE_SKILL_HOME"]


print()
print(f"{passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
