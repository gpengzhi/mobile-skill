"""Local installation helpers for Agent skills."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .errors import MobileSkillError


SKILL_DIR_NAME = "mobile-skill"

# Skill install paths per harness. Layout is <default_home>/skills/<SKILL_DIR_NAME>/;
# when `home_env` is set and non-empty, its value overrides `default_home`.
# Codex reads from ~/.agents/skills (not ~/.codex/skills) — verified against
# BrowserSkill's harness table at Tencent/BrowserSkill:crates/bsk-cli/src/skill_install/harness.rs.
HARNESSES: dict[str, dict[str, str | None]] = {
    "claude-code": {
        "cli": "claude",
        "home_env": "CLAUDE_CONFIG_DIR",
        "default_home": "~/.claude",
        "image_tool": "Read",
    },
    "codex": {
        "cli": "codex",
        "home_env": None,
        "default_home": "~/.agents",
        "image_tool": "view_image",
    },
    "cursor": {
        "cli": "cursor",
        "home_env": None,
        "default_home": "~/.cursor",
        "image_tool": None,
    },
    "openclaw": {
        "cli": "openclaw",
        "home_env": None,
        "default_home": "~/.openclaw",
        "image_tool": None,
    },
    "codebuddy": {
        "cli": "codebuddy",
        "home_env": None,
        "default_home": "~/.codebuddy",
        "image_tool": None,
    },
    "workbuddy": {
        "cli": "workbuddy",
        "home_env": None,
        "default_home": "~/.workbuddy",
        "image_tool": None,
    },
    "pi": {
        "cli": "pi",
        "home_env": None,
        "default_home": "~/.pi/agent",
        "image_tool": None,
    },
    "hermes": {
        "cli": "hermes",
        "home_env": "HERMES_HOME",
        "default_home": "~/.hermes",
        "image_tool": None,
    },
    "kimi-code": {
        "cli": "kimi",
        "home_env": "KIMI_CODE_HOME",
        "default_home": "~/.kimi-code",
        "image_tool": None,
    },
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def skill_source(root: Path | None = None) -> Path:
    source = (root or project_root()) / "skill"
    if source.is_dir():
        return source
    raise MobileSkillError(
        "install_source_missing",
        f"cannot locate Agent Skill directory: {source}",
        "run msk from a complete mobile-skill source checkout",
    )


def launcher_source(root: Path | None = None) -> Path:
    source = (root or project_root()) / "msk"
    if source.is_file():
        return source
    raise MobileSkillError(
        "install_source_missing",
        f"cannot locate msk launcher: {source}",
        "run msk from a complete mobile-skill source checkout",
    )


def harness_home(name: str) -> Path:
    entry = HARNESSES[name]
    env_name = entry["home_env"]
    if env_name and os.environ.get(env_name):
        return Path(os.environ[env_name]).expanduser()
    return Path(str(entry["default_home"])).expanduser()


def _link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        if destination.resolve() == source.resolve():
            return
        destination.unlink()
    elif destination.exists():
        if destination.resolve() == source.resolve():
            return
        raise MobileSkillError(
            "install_conflict",
            f"cannot replace existing non-symlink path: {destination}",
            "move or remove that path, then retry",
        )
    destination.symlink_to(source)


def _do_install(label: str, home: Path, cli: str | None) -> dict[str, Any]:
    root = project_root()
    launcher = launcher_source(root)
    source = skill_source(root)

    cli_link = Path.home() / ".local" / "bin" / "msk"
    skill_link = home / "skills" / SKILL_DIR_NAME
    _link(launcher, cli_link)
    _link(source, skill_link)

    cli_missing = cli is not None and shutil.which(cli) is None
    if cli_missing:
        next_action = (
            f"install the {cli} CLI, then run `msk doctor --agent {label}`"
        )
    elif cli:
        next_action = f"restart {cli}, then run `msk doctor --agent {label}`"
    else:
        next_action = (
            f"restart the target agent and load {skill_link}, then run `msk doctor`"
        )
    return {
        "agent": label,
        "cli": str(cli_link),
        "skill": str(skill_link),
        "harness_cli_present": None if cli is None else not cli_missing,
        "next_action": next_action,
    }


def install(name: str) -> dict[str, Any]:
    if name not in HARNESSES:
        listing = ", ".join(sorted(HARNESSES))
        raise MobileSkillError(
            "unknown_harness",
            f"unknown harness: {name}",
            (
                f"run `msk install --list` (registered: {listing}) or use "
                "`msk install --home <dir>` for a manual install"
            ),
        )
    entry = HARNESSES[name]
    return _do_install(name, harness_home(name), entry["cli"])


def install_to_home(home: Path, label: str | None = None) -> dict[str, Any]:
    resolved = Path(home).expanduser().resolve()
    if not resolved.parent.exists():
        raise MobileSkillError(
            "install_home_missing",
            f"parent directory does not exist: {resolved.parent}",
            "create the parent directory or point --home at an existing one",
        )
    display = label or resolved.name or "generic"
    return _do_install(display, resolved, None)


def registered_harnesses() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name, spec in HARNESSES.items():
        home = harness_home(name)
        entries.append(
            {
                "name": name,
                "cli": spec["cli"],
                "home_env": spec["home_env"],
                "default_home": spec["default_home"],
                "home": str(home),
                "skill_path": str(home / "skills" / SKILL_DIR_NAME),
                "image_tool": spec["image_tool"],
            }
        )
    return entries
