"""Installer symlink behavior — no CLI actually called."""

from __future__ import annotations

from pathlib import Path

import pytest

from mobile_skill import installer
from mobile_skill.errors import MobileSkillError


@pytest.fixture
def fake_local_bin(tmp_path, monkeypatch):
    """Redirect ~/.local/bin/msk into a tmpdir so we don't pollute the real HOME."""
    fake_home = tmp_path / "userhome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Path.home() honors $HOME on POSIX
    return fake_home


def test_registered_harnesses_covers_advertised_set(fake_local_bin) -> None:
    names = {h["name"] for h in installer.registered_harnesses()}
    assert names == {
        "claude-code", "codex", "cursor", "openclaw", "codebuddy",
        "workbuddy", "pi", "hermes", "kimi-code",
    }
    for entry in installer.registered_harnesses():
        assert entry["cli"]
        assert entry["skill_path"].endswith("/skills/mobile-skill")


def test_install_to_home_creates_symlinks(fake_local_bin, tmp_path) -> None:
    target = tmp_path / "custom-agent"
    target.mkdir()
    result = installer.install_to_home(target)
    launcher_link = fake_local_bin / ".local/bin/msk"
    skill_link = target / "skills/mobile-skill"
    assert launcher_link.is_symlink()
    assert skill_link.is_symlink()
    assert launcher_link.resolve() == installer.launcher_source().resolve()
    assert skill_link.resolve() == installer.skill_source().resolve()
    assert result["agent"] == "custom-agent"
    assert result["harness_cli_present"] is None


def test_install_to_home_idempotent(fake_local_bin, tmp_path) -> None:
    target = tmp_path / "agent"
    target.mkdir()
    installer.install_to_home(target)
    installer.install_to_home(target)  # second call must not raise
    assert (target / "skills/mobile-skill").is_symlink()


def test_install_to_home_conflict_non_symlink(fake_local_bin, tmp_path) -> None:
    target = tmp_path / "agent"
    (target / "skills/mobile-skill").mkdir(parents=True)
    # Existing non-symlink directory at destination → conflict
    with pytest.raises(MobileSkillError) as excinfo:
        installer.install_to_home(target)
    assert excinfo.value.code == "install_conflict"


def test_install_to_home_rejects_missing_parent(fake_local_bin, tmp_path) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        installer.install_to_home(tmp_path / "does" / "not" / "exist")
    assert excinfo.value.code == "install_home_missing"


def test_install_unknown_harness(fake_local_bin) -> None:
    with pytest.raises(MobileSkillError) as excinfo:
        installer.install("not-real")
    assert excinfo.value.code == "unknown_harness"


def test_install_to_home_uses_label(fake_local_bin, tmp_path) -> None:
    target = tmp_path / "generic-agent"
    target.mkdir()
    result = installer.install_to_home(target, label="my-thing")
    assert result["agent"] == "my-thing"
