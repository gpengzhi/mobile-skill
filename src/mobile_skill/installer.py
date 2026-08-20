"""Local installation helpers for Agent skills."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .errors import MobileSkillError


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


def _install(agent: str, command: str, skill_home: Path) -> dict[str, Any]:
    if shutil.which(command) is None:
        raise MobileSkillError(
            f"{agent.replace('-', '_')}_not_found",
            f"{command} CLI is not installed",
            f"install {command}, then rerun `msk install {agent}`",
        )

    root = project_root()
    launcher = launcher_source(root)
    source = skill_source(root)

    cli_link = Path.home() / ".local" / "bin" / "msk"
    skill_link = skill_home / "skills" / "mobile-skill"
    _link(launcher, cli_link)
    _link(source, skill_link)
    return {
        "agent": agent,
        "cli": str(cli_link),
        "skill": str(skill_link),
        "next_action": f"restart {command}, then run `msk doctor --agent {agent}`",
    }


def install_codex() -> dict[str, Any]:
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return _install("codex", "codex", home)


def install_claude_code() -> dict[str, Any]:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return _install("claude-code", "claude", home)
