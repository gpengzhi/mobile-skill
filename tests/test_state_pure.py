"""Environment-variable parsing for state and observation helpers."""

from __future__ import annotations

import pytest

from mobile_skill import observations, state
from mobile_skill.errors import MobileSkillError


@pytest.mark.parametrize(
    "getter, env, default_value",
    [
        (state.retention_days, "MOBILE_SKILL_RETENTION_DAYS", state.DEFAULT_RETENTION_DAYS),
        (
            state.idle_session_ttl_s,
            "MOBILE_SKILL_IDLE_SESSION_TTL_S",
            state.DEFAULT_IDLE_SESSION_TTL_S,
        ),
        (observations.unlock_ttl_s, "MOBILE_SKILL_UNLOCK_TTL_S", observations.UNLOCK_TTL_S_DEFAULT),
    ],
)
def test_defaults_used_when_env_unset(getter, env: str, default_value, monkeypatch) -> None:
    monkeypatch.delenv(env, raising=False)
    assert getter() == default_value


def test_retention_days_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_RETENTION_DAYS", "3")
    assert state.retention_days() == 3


def test_idle_session_ttl_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_IDLE_SESSION_TTL_S", "600")
    assert state.idle_session_ttl_s() == 600


def test_unlock_ttl_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_UNLOCK_TTL_S", "12.5")
    assert observations.unlock_ttl_s() == pytest.approx(12.5)


@pytest.mark.parametrize("bad", ["-1", "abc", ""])
def test_retention_days_rejects_invalid(bad: str, monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_RETENTION_DAYS", bad)
    with pytest.raises(MobileSkillError) as excinfo:
        state.retention_days()
    assert excinfo.value.code == "invalid_retention_days"


@pytest.mark.parametrize("bad", ["-1", "abc"])
def test_idle_ttl_rejects_invalid(bad: str, monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_IDLE_SESSION_TTL_S", bad)
    with pytest.raises(MobileSkillError) as excinfo:
        state.idle_session_ttl_s()
    assert excinfo.value.code == "invalid_idle_session_ttl"


@pytest.mark.parametrize("bad", ["-0.5", "not-a-number"])
def test_unlock_ttl_rejects_invalid(bad: str, monkeypatch) -> None:
    monkeypatch.setenv("MOBILE_SKILL_UNLOCK_TTL_S", bad)
    with pytest.raises(MobileSkillError) as excinfo:
        observations.unlock_ttl_s()
    assert excinfo.value.code == "invalid_unlock_ttl"
