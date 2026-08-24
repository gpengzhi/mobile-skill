"""Deep-link discovery, registry, and invocation.

Discovery has two channels:

* `parse_schemes(serial, package)` — parses `dumpsys package <pkg>` for the
  URI schemes and https hosts the app declares in its manifest. This is the
  authoritative "what schemes does the app claim to handle" answer.

* `load_curated_registry()` / `load_learned_registry()` — the mobile-skill
  registry: curated URL templates shipped with the project, plus a
  learned-registry file that Phase 2 will populate. Phase 1 loads both; the
  learned side is expected to be empty.

Invocation goes through `open_url(serial, url)`, which pre-checks with
`pm resolve-activity` and blocks obviously sensitive URLs (containing
`pay`, `transfer`, `send`, `publish`, `share`) unless the exact template is
in the curated registry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import android, state
from .errors import MobileSkillError


SENSITIVE_KEYWORDS = ("pay", "transfer", "send", "publish", "share")

_ACTIVITY_LINE = re.compile(r"^[\w.]+/[\w.$]+$")
_SCHEME_PATTERN = re.compile(r"Scheme:\s*\"([^\"]+)\"")
_AUTHORITY_PATTERN = re.compile(r"Authority:\s*\"([^\"]+):")


def _project_root() -> Path:
    # avoid importing installer to sidestep any future import cycle
    return Path(__file__).resolve().parents[2]


def curated_registry_path() -> Path:
    return _project_root() / "registry" / "deeplinks.json"


def learned_registry_path() -> Path:
    return state.home() / "learned_deeplinks.json"


def load_curated_registry() -> dict[str, Any]:
    """Load the shipped registry. Returns {"apps": {...}} or {} if missing."""
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

    Phase 1 does not write to this file. Corrupt content is silently ignored
    so a broken learned registry does not block usage of the curated one.
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


def merged_registry(package: str | None = None) -> list[dict[str, Any]]:
    """Return per-app entries as `[{package, display_name, curated, learned}, …]`.

    When `package` is provided, the returned list has at most one element even
    if the app has no entries in either source.
    """
    curated = load_curated_registry().get("apps", {})
    learned = load_learned_registry().get("apps", {})
    packages = set(curated) | set(learned)
    if package is not None:
        packages = {package} if package in packages else {package}
    result: list[dict[str, Any]] = []
    for pkg in sorted(packages):
        curated_spec = curated.get(pkg, {})
        learned_spec = learned.get(pkg, {})
        result.append(
            {
                "package": pkg,
                "display_name": curated_spec.get("display_name")
                or learned_spec.get("display_name"),
                "curated": curated_spec.get("entries", []),
                "learned": learned_spec.get("entries", []),
            }
        )
    return result


def parse_schemes(serial: str, package: str) -> dict[str, Any]:
    """Extract URI schemes and https hosts the package declares."""
    android.require_installed_app(serial, package)
    output = str(android.run_adb("shell", "dumpsys", "package", package, serial=serial))
    schemes = sorted({m.group(1) for m in _SCHEME_PATTERN.finditer(output)})
    hosts = sorted({m.group(1) for m in _AUTHORITY_PATTERN.finditer(output)})
    return {
        "package": package,
        "schemes": schemes,
        "https_hosts": hosts,
    }


def resolve_url(serial: str, url: str) -> str | None:
    """Return the `pkg/activity` string that handles url, or None if unresolvable."""
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


def _url_matches_curated_template(url: str) -> bool:
    """True if url matches any curated template (with {var} expanded to wildcards)."""
    curated = load_curated_registry().get("apps", {})
    for spec in curated.values():
        for entry in spec.get("entries", []):
            template = entry.get("url", "")
            if not template:
                continue
            pattern = re.escape(template)
            pattern = re.sub(r"\\\{[^}]+\\\}", ".*", pattern)
            if re.fullmatch(pattern, url):
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
