"""Deep-link discovery, registry, invocation, and learning.

Discovery has two channels:

* `parse_schemes(serial, package)` — parses `dumpsys package <pkg>` for the
  URI schemes the app declares in its manifest.

* `load_curated_registry()` + `load_learned_registry()` — the mobile-skill
  registry: curated URL templates shipped with the project, plus a
  learned-registry file that accumulates via successful invocations.

Invocation goes through `open_url(serial, url)`, which pre-checks with
`pm resolve-activity` and blocks sensitive URLs (containing `pay`,
`transfer`, `send`, `publish`, `share`) unless the exact URL matches a
curated template.

Phase 2 self-evolution: after `open_url` succeeds and cli's settle
completes, `finalize_open_url` reads the actual foreground activity via
`dumpsys activity`, classifies the outcome (verified/fallback/hijacked),
normalizes the concrete URL to a structural template
(e.g. `bilibili://space/12345678` → `bilibili://space/{...}`), and records
per-template counters into `learned_deeplinks.json`. Concrete URL values
are NEVER stored — the learned file only holds generalized templates
plus aggregate statistics.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import android, state
from .errors import MobileSkillError


SENSITIVE_KEYWORDS = ("pay", "transfer", "send", "publish", "share")
KNOWN_OUTCOMES = ("verified", "fallback", "hijacked", "unknown")

_ACTIVITY_LINE = re.compile(r"^[\w.]+/[\w.$]+$")
_SCHEME_PATTERN = re.compile(r"Scheme:\s*\"([^\"]+)\"")
_AUTHORITY_PATTERN = re.compile(r"Authority:\s*\"([^\"]+):")
_RESUMED_PATTERN = re.compile(
    r"(?:top)?[Rr]esumedActivity[=:\s][^\n]*?\bu\d+\s+([\w.$]+/[\w.$]+)"
)

# Path-segment ID heuristics. If a segment matches any of these, we treat it
# as a variable and replace with the placeholder token.
_ID_NUMERIC = re.compile(r"^\d+$")
_ID_BV = re.compile(r"^BV[A-Za-z0-9]+$")
_ID_AV = re.compile(r"^[Aa][Vv]\d+$")
_ID_HEX = re.compile(r"^[a-fA-F0-9]{16,}$")
_ID_OPAQUE = re.compile(r"^[A-Za-z0-9_\-]{8,}$")

_PLACEHOLDER = "{...}"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def curated_registry_path() -> Path:
    return _project_root() / "registry" / "deeplinks.json"


def learned_registry_path() -> Path:
    return state.home() / "learned_deeplinks.json"


def _learned_lock_path() -> Path:
    return state.home() / "learned_deeplinks.lock"


def load_curated_registry() -> dict[str, Any]:
    path = curated_registry_path()
    if not path.is_file():
        return {"apps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MobileSkillError(
            "deeplink_registry_invalid",
            f"cannot read curated registry {path}: {error}",
        ) from error
    if not isinstance(data, dict) or not isinstance(data.get("apps"), dict):
        raise MobileSkillError(
            "deeplink_registry_invalid", f"invalid registry file: {path}"
        )
    return data


def load_learned_registry() -> dict[str, Any]:
    """Load the learned registry, or empty structure if none exists yet.

    Corrupt content is silently ignored so a broken learned registry does
    not block usage of the curated one.
    """
    path = learned_registry_path()
    if not path.is_file():
        return {"apps": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"apps": {}}
    if not isinstance(data, dict) or not isinstance(data.get("apps"), dict):
        return {"apps": {}}
    return data


# ---------------------------------------------------------------------------
# URL normalization: concrete URL → structural template
# ---------------------------------------------------------------------------


def _looks_like_id(segment: str) -> bool:
    """Path-segment heuristic: does this look like a dynamic identifier?"""
    if not segment:
        return False
    if _ID_NUMERIC.match(segment):
        return True
    if _ID_BV.match(segment):
        return True
    if _ID_AV.match(segment):
        return True
    if _ID_HEX.match(segment):
        return True
    if _ID_OPAQUE.match(segment):
        # opaque long strings that also contain digits look ID-ish;
        # long strings of pure letters are more likely route names.
        return any(character.isdigit() for character in segment)
    return False


def normalize_to_template(url: str) -> str:
    """Convert a concrete URL to a structural template.

    Path segments matching ID heuristics become `{...}`.
    Query values are replaced with `{<key>}`, keys preserved.
    Fragment values are replaced with `{...}`.
    Scheme, host, route-name path segments, and query keys are preserved.

    Examples:
      bilibili://search?keyword=Minecraft      → bilibili://search?keyword={keyword}
      bilibili://space/12345678                → bilibili://space/{...}
      bilibili://video/BV1xx411c7mu?tab=hot    → bilibili://video/{...}?tab={tab}
      weixin://scanqrcode                      → weixin://scanqrcode  (no variables)
    """
    parsed = urlparse(url)
    scheme = parsed.scheme
    netloc = parsed.netloc

    # Path segments
    if parsed.path:
        segments = parsed.path.split("/")
        segments = [
            _PLACEHOLDER if _looks_like_id(seg) else seg for seg in segments
        ]
        new_path = "/".join(segments)
    else:
        new_path = parsed.path

    # Query — replace values with {key}, preserve keys
    if parsed.query:
        pairs = []
        for pair in parsed.query.split("&"):
            if "=" in pair:
                key, _value = pair.split("=", 1)
                pairs.append(f"{key}={{{key}}}")
            else:
                pairs.append(pair)
        new_query = "&".join(pairs)
    else:
        new_query = ""

    new_fragment = _PLACEHOLDER if parsed.fragment else ""

    result = f"{scheme}://{netloc}{new_path}"
    if new_query:
        result += f"?{new_query}"
    if new_fragment:
        result += f"#{new_fragment}"
    return result


def passes_template_invariant(template: str) -> bool:
    """Guard: a learned entry must contain no dynamic-looking concrete values.

    Rules:
      - No path segment may match ID heuristics (should already be {...}).
      - No query value may be non-empty and non-placeholder.
      - No fragment value may be non-empty and non-placeholder.
    """
    parsed = urlparse(template)
    # Path
    if parsed.path:
        for segment in parsed.path.split("/"):
            if _looks_like_id(segment):
                return False
    # Query
    if parsed.query:
        for pair in parsed.query.split("&"):
            if "=" in pair:
                _key, value = pair.split("=", 1)
                if value and not (value.startswith("{") and value.endswith("}")):
                    return False
    # Fragment
    if parsed.fragment:
        if not (
            parsed.fragment.startswith("{") and parsed.fragment.endswith("}")
        ):
            return False
    return True


def url_matches_template(concrete_url: str, template: str) -> bool:
    """True if concrete_url is an instance of template.

    Placeholders in template (`{name}` or `{...}`) match any non-empty value
    in the same position. Everything else must match literally.
    """
    if concrete_url == template:
        return True
    # Turn the template into a regex, replacing {...} groups with wildcards.
    escaped = re.escape(template)
    pattern = re.sub(r"\\\{[^}]*\\\}", r"[^/?&#]+", escaped)
    return re.fullmatch(pattern, concrete_url) is not None


def _canonical_shape(template: str) -> str:
    """Collapse any placeholder (`{...}`, `{keyword}`, `{mid}`) to a single
    marker so that structurally identical templates compare equal.
    """
    return re.sub(r"\{[^}]*\}", "{}", template)


# ---------------------------------------------------------------------------
# Merged registry query (Phase 1 shape refined to unified entries list)
# ---------------------------------------------------------------------------


def _find_template_stats(
    learned_apps: dict[str, Any], package: str, template: str
) -> dict[str, Any] | None:
    target_shape = _canonical_shape(template)
    entries = learned_apps.get(package, {}).get("entries", [])
    for entry in entries:
        if _canonical_shape(entry.get("url", "")) == target_shape:
            return entry
    return None


def merged_registry(package: str | None = None) -> list[dict[str, Any]]:
    """Return per-app entries with `source` tag and any accumulated counters.

    Curated entries are always listed first (with any stats overlaid from
    the learned file, keyed by URL template). Learned-only entries whose
    template does not match any curated URL follow.
    """
    curated_apps = load_curated_registry().get("apps", {})
    learned_apps = load_learned_registry().get("apps", {})
    packages = set(curated_apps) | set(learned_apps)
    if package is not None:
        packages = {package} if package in packages else {package}

    _COUNTER_FIELDS = (
        "invocations",
        "verified",
        "fallback",
        "hijacked",
        "unknown",
        "first_seen",
        "last_seen",
        "resolved_activity",
    )
    result: list[dict[str, Any]] = []
    for pkg in sorted(packages):
        curated_spec = curated_apps.get(pkg, {})
        learned_spec = learned_apps.get(pkg, {})
        curated_entries = curated_spec.get("entries", [])
        learned_entries = learned_spec.get("entries", [])

        merged_entries: list[dict[str, Any]] = []
        curated_shapes: set[str] = set()

        for entry in curated_entries:
            out = {"source": "curated", **entry}
            stats = _find_template_stats(learned_apps, pkg, entry.get("url", ""))
            if stats is not None:
                for field in _COUNTER_FIELDS:
                    if field in stats:
                        out[field] = stats[field]
            curated_shapes.add(_canonical_shape(entry.get("url", "")))
            merged_entries.append(out)

        for entry in learned_entries:
            if _canonical_shape(entry.get("url", "")) in curated_shapes:
                continue  # shape-equivalent to a curated entry, already overlaid
            merged_entries.append({"source": "learned", **entry})

        result.append(
            {
                "package": pkg,
                "display_name": curated_spec.get("display_name")
                or learned_spec.get("display_name"),
                "entries": merged_entries,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Discovery + invocation
# ---------------------------------------------------------------------------


def parse_schemes(serial: str, package: str) -> dict[str, Any]:
    android.require_installed_app(serial, package)
    output = str(android.run_adb("shell", "dumpsys", "package", package, serial=serial))
    schemes = sorted({m.group(1) for m in _SCHEME_PATTERN.finditer(output)})
    hosts = sorted({m.group(1) for m in _AUTHORITY_PATTERN.finditer(output)})
    return {"package": package, "schemes": schemes, "https_hosts": hosts}


def resolve_url(serial: str, url: str) -> str | None:
    output = str(
        android.run_adb(
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            android.shell_quote(url),
            serial=serial,
        )
    )
    for line in output.splitlines():
        stripped = line.strip()
        if _ACTIVITY_LINE.match(stripped):
            return stripped
    return None


def resolve_current_foreground_activity(serial: str) -> str | None:
    """Return the currently-resumed activity as `pkg/activity`, or None."""
    try:
        output = str(
            android.run_adb("shell", "dumpsys", "activity", "activities", serial=serial)
        )
    except MobileSkillError:
        return None
    match = _RESUMED_PATTERN.search(output)
    return match.group(1) if match else None


def _url_matches_curated_template(url: str) -> bool:
    curated = load_curated_registry().get("apps", {})
    for spec in curated.values():
        for entry in spec.get("entries", []):
            template = entry.get("url", "")
            if template and url_matches_template(url, template):
                return True
    return False


def is_sensitive_url(url: str) -> bool:
    lowered = url.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def open_url(serial: str, url: str) -> dict[str, Any]:
    """Invoke a deep link. Raises on sensitive-URL block or unresolvable URL."""
    if not url or url.strip() != url:
        raise MobileSkillError("invalid_url", "URL must be a non-empty trimmed string")
    if is_sensitive_url(url) and not _url_matches_curated_template(url):
        raise MobileSkillError(
            "deeplink_requires_human",
            f"URL contains a sensitive keyword and is not in the curated registry: {url}",
            "route this action through `msk request-help` for the user to complete manually",
        )
    resolved = resolve_url(serial, url)
    if resolved is None:
        raise MobileSkillError(
            "deeplink_unresolvable",
            f"no activity handles this URL on the device: {url}",
            "verify the app's declared schemes with `msk app schemes <package>`",
        )
    android.run_adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        android.shell_quote(url),
        serial=serial,
    )
    return {"url": url, "resolved_activity": resolved}


# ---------------------------------------------------------------------------
# Landing verification + learned-registry recording (Phase 2)
# ---------------------------------------------------------------------------


def _package_of_activity(activity: str) -> str:
    return activity.split("/", 1)[0] if activity and "/" in activity else ""


def classify_outcome(expected_activity: str | None, actual_activity: str | None) -> str:
    """Classify what happened after `open_url` invocation.

    - verified: URL landed in the expected app (same package). Apps commonly
      route their VIEW intents through a dispatch activity (Bilibili's
      IntentHandlerActivity, Alipay's SchemeLauncherActivity) that then
      forwards to the real target — treating same-package as verified is
      the right coarse signal for "did the URL work".
    - hijacked: URL landed in a different package (captured by a competing
      handler, or the target app was not the resolved activity).
    - unknown:  actual is not observable (dumpsys returned nothing).
    """
    if not actual_activity or not expected_activity:
        return "unknown"
    if _package_of_activity(actual_activity) == _package_of_activity(expected_activity):
        return "verified"
    return "hijacked"


@contextmanager
def _learned_locked():
    path = _learned_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _write_learned(data: dict[str, Any]) -> None:
    path = learned_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="learned-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def finalize_open_url(
    serial: str, url: str, expected_activity: str | None
) -> dict[str, Any]:
    """Landing check + record the outcome.

    Called from cli._complete_action AFTER the settle delay so the target
    activity has had a chance to resume. Never raises — recording failures
    are surfaced as {"error": "..."} in the return value so open_url's
    success remains observable.
    """
    actual = resolve_current_foreground_activity(serial)
    outcome = classify_outcome(expected_activity, actual)
    template = normalize_to_template(url)

    # Belt-and-braces: mirror the check in open_url. Sensitive URLs are
    # permitted only when their concrete form matches a curated template
    # (e.g. `alipays://platformapi/startapp?appId=10000007` — the URL
    # contains "pay" because the scheme is `alipays`, not because the
    # operation is a payment).
    if (is_sensitive_url(url) or is_sensitive_url(template)) and not _url_matches_curated_template(url):
        return {"actual_activity": actual, "outcome": outcome, "recorded": False}

    if not passes_template_invariant(template):
        return {
            "actual_activity": actual,
            "outcome": outcome,
            "recorded": False,
            "error": f"normalized template failed invariant: {template}",
        }

    package = _package_of_activity(expected_activity or actual or "")
    if not package:
        return {
            "actual_activity": actual,
            "outcome": outcome,
            "recorded": False,
            "error": "cannot determine package",
        }

    # If curated has a structurally-equivalent template, adopt its URL as
    # the storage key so the counter overlays cleanly on the curated entry
    # (and named placeholders like `{mid}` are preserved instead of `{...}`).
    curated_apps = load_curated_registry().get("apps", {})
    target_shape = _canonical_shape(template)
    for entry in curated_apps.get(package, {}).get("entries", []):
        if _canonical_shape(entry.get("url", "")) == target_shape:
            template = entry["url"]
            break

    try:
        with _learned_locked():
            data = load_learned_registry()
            apps = data.setdefault("apps", {})
            spec = apps.setdefault(package, {"entries": []})
            entries = spec.setdefault("entries", [])
            entry: dict[str, Any] | None = None
            template_shape = _canonical_shape(template)
            for candidate in entries:
                if _canonical_shape(candidate.get("url", "")) == template_shape:
                    entry = candidate
                    break
            now = _now_iso()
            if entry is None:
                entry = {
                    "url": template,
                    "invocations": 0,
                    "verified": 0,
                    "fallback": 0,
                    "hijacked": 0,
                    "unknown": 0,
                    "first_seen": now,
                    "last_seen": now,
                }
                entries.append(entry)
            entry["invocations"] = int(entry.get("invocations", 0)) + 1
            entry[outcome] = int(entry.get(outcome, 0)) + 1
            entry["last_seen"] = now
            if expected_activity:
                entry["resolved_activity"] = expected_activity
            data.setdefault("version", 1)
            _write_learned(data)
    except Exception as error:
        return {
            "actual_activity": actual,
            "outcome": outcome,
            "recorded": False,
            "error": str(error),
        }
    return {
        "actual_activity": actual,
        "outcome": outcome,
        "template": template,
        "recorded": True,
    }


# ---------------------------------------------------------------------------
# Learned registry mutations (Phase 2 UX)
# ---------------------------------------------------------------------------


def forget_learned_url(url: str, package: str | None = None) -> dict[str, Any]:
    """Remove a specific learned entry by exact URL match.

    If `package` is given, restrict the search to that app; otherwise scan
    every app in the learned file. Curated entries are never touched.
    Returns which package(s)/URL(s) were removed.
    """
    if not url or url.strip() != url:
        raise MobileSkillError("invalid_url", "URL must be a non-empty trimmed string")
    with _learned_locked():
        data = load_learned_registry()
        apps = data.get("apps", {})
        forgotten: list[dict[str, str]] = []
        empty_pkgs: list[str] = []
        packages = [package] if package is not None else list(apps)
        for pkg in packages:
            spec = apps.get(pkg)
            if not spec:
                continue
            before = spec.get("entries", [])
            after = [entry for entry in before if entry.get("url") != url]
            if len(after) != len(before):
                forgotten.append({"package": pkg, "url": url})
                spec["entries"] = after
            if not spec.get("entries"):
                empty_pkgs.append(pkg)
        for pkg in empty_pkgs:
            del apps[pkg]
        if forgotten:
            _write_learned(data)
        return {"forgotten": forgotten}


def reset_learned() -> dict[str, Any]:
    """Wipe the entire learned registry. Curated is untouched."""
    with _learned_locked():
        data = load_learned_registry()
        apps = data.get("apps", {})
        cleared_apps = len(apps)
        cleared_entries = sum(len(spec.get("entries", [])) for spec in apps.values())
        _write_learned({"version": 1, "apps": {}})
        return {"cleared_apps": cleared_apps, "cleared_entries": cleared_entries}
