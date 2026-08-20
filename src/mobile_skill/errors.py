"""Public, stable errors returned by the mobile-skill CLI."""

from __future__ import annotations

from typing import Any


class MobileSkillError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.details = details or {}
