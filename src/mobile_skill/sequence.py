"""Validation helpers for bounded device action sequences."""

from __future__ import annotations

import json
from typing import Any

from . import android, deeplinks
from .errors import MobileSkillError


MAX_SEQUENCE_ACTIONS = 5
MAX_SEQUENCE_TEXT_LENGTH = 4096
MAX_SEQUENCE_DURATION_MS = 60_000
TERMINAL_ACTIONS = {
    "swipe",
    "home",
    "back",
    "app-switcher",
    "app-open",
    "open-url",
}
# Keys that reliably navigate/submit and invalidate on-screen coordinates.
# `escape`, `tab`, and `space` are context-dependent (dialog dismiss vs. IME
# vs. focused-button activation) — left as the Agent's judgement call.
_NAVIGATING_PRESS_KEYS = frozenset({"enter", "return"})


def _is_terminal(action: dict[str, Any]) -> bool:
    action_type = action.get("type")
    if action_type in TERMINAL_ACTIONS:
        return True
    if action_type == "press":
        key = action.get("key", "")
        if isinstance(key, str) and key.lower() in _NAVIGATING_PRESS_KEYS:
            return True
    return False


def _terminal_label(action: dict[str, Any]) -> str:
    if action.get("type") == "press":
        return f"press {action.get('key')}"
    return str(action.get("type"))


SUPPORTED_ACTIONS = {
    "tap",
    "double-tap",
    "long-press",
    "swipe",
    "wait",
    "type",
    "press",
    "home",
    "back",
    "app-switcher",
    "app-open",
    "open-url",
}
_LABEL_FIELDS = {"label"}


def _require_mapping(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} must be an object",
        )
    return value


def _require_int(action: dict[str, Any], field: str, index: int) -> int:
    value = action.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} field {field!r} must be an integer",
        )
    return value


def _require_string(action: dict[str, Any], field: str, index: int) -> str:
    value = action.get(field)
    if not isinstance(value, str):
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} field {field!r} must be a string",
        )
    return value


def _validate_coordinates(action: dict[str, Any], fields: tuple[str, ...], index: int) -> None:
    for field in fields:
        value = _require_int(action, field, index)
        if not 0 <= value <= 999:
            raise MobileSkillError(
                "invalid_coordinate",
                f"sequence action {index} field {field!r} must be between 0 and 999",
            )


def _validate_action(action: dict[str, Any], index: int) -> None:
    action_type = action.get("type")
    if not isinstance(action_type, str) or action_type not in SUPPORTED_ACTIONS:
        supported = ", ".join(sorted(SUPPORTED_ACTIONS))
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} has unsupported type {action_type!r}; supported: {supported}",
        )

    allowed_fields = {"type", *_LABEL_FIELDS}
    if "label" in action and not isinstance(action["label"], str):
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} field 'label' must be a string",
        )
    if action_type in {"tap", "double-tap", "long-press"}:
        allowed_fields.update({"x", "y"})
        _validate_coordinates(action, ("x", "y"), index)
        if action_type == "double-tap":
            allowed_fields.add("interval_ms")
            interval_ms = _require_int(action, "interval_ms", index)
            if not 0 < interval_ms <= MAX_SEQUENCE_DURATION_MS:
                raise MobileSkillError(
                    "invalid_sequence_action",
                    f"sequence action {index} interval_ms must be between 1 and {MAX_SEQUENCE_DURATION_MS}",
                )
        if action_type == "long-press":
            allowed_fields.add("duration_ms")
            duration_ms = _require_int(action, "duration_ms", index)
            if not 0 < duration_ms <= MAX_SEQUENCE_DURATION_MS:
                raise MobileSkillError(
                    "invalid_sequence_action",
                    f"sequence action {index} duration_ms must be between 1 and {MAX_SEQUENCE_DURATION_MS}",
                )
    elif action_type == "swipe":
        allowed_fields.update({"x1", "y1", "x2", "y2", "duration_ms"})
        _validate_coordinates(action, ("x1", "y1", "x2", "y2"), index)
        duration_ms = _require_int(action, "duration_ms", index)
        if not 0 < duration_ms <= MAX_SEQUENCE_DURATION_MS:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} duration_ms must be between 1 and {MAX_SEQUENCE_DURATION_MS}",
            )
    elif action_type == "wait":
        allowed_fields.add("duration_ms")
        duration_ms = _require_int(action, "duration_ms", index)
        if not 0 <= duration_ms <= MAX_SEQUENCE_DURATION_MS:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} duration_ms must be between 0 and {MAX_SEQUENCE_DURATION_MS}",
            )
    elif action_type == "type":
        allowed_fields.add("text")
        text = _require_string(action, "text", index)
        if not text:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} text must not be empty",
            )
        if len(text) > MAX_SEQUENCE_TEXT_LENGTH:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} text must not exceed {MAX_SEQUENCE_TEXT_LENGTH} characters",
            )
    elif action_type == "press":
        allowed_fields.add("key")
        key = _require_string(action, "key", index)
        if not key:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} key must not be empty",
            )
        try:
            android.key_code(key)
        except MobileSkillError as error:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} has an unsupported key: {key!r}",
                details={"cause": error.code},
            ) from error
    elif action_type == "app-open":
        allowed_fields.add("package")
        package = _require_string(action, "package", index)
        if not package or any(character.isspace() or ord(character) < 32 for character in package):
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} package must be a valid Android package name",
            )
    elif action_type == "open-url":
        allowed_fields.add("url")
        url = _require_string(action, "url", index)
        if not url or url.strip() != url:
            raise MobileSkillError(
                "invalid_sequence_action",
                f"sequence action {index} url must be a non-empty trimmed string",
            )
        if deeplinks.blocks_sensitive_url(url):
            raise MobileSkillError(
                "deeplink_requires_human",
                f"sequence action {index} URL contains a sensitive keyword and is not in the curated registry: {url}",
                "route this action through `msk request-help` for the user to complete manually",
            )

    unknown_fields = set(action) - allowed_fields
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise MobileSkillError(
            "invalid_sequence_action",
            f"sequence action {index} has unsupported fields: {names}",
        )


def parse_actions(raw: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise MobileSkillError(
            "invalid_sequence_json", f"cannot parse sequence actions: {error.msg}"
        ) from error
    if not isinstance(value, list):
        raise MobileSkillError("invalid_sequence", "sequence actions must be a JSON array")
    if not value:
        raise MobileSkillError("invalid_sequence", "sequence must contain at least one action")
    if len(value) > MAX_SEQUENCE_ACTIONS:
        raise MobileSkillError(
            "sequence_too_long",
            f"sequence cannot contain more than {MAX_SEQUENCE_ACTIONS} actions",
        )

    actions = [_require_mapping(item, index) for index, item in enumerate(value)]
    for index, action in enumerate(actions):
        _validate_action(action, index)
        if index and _is_terminal(actions[index - 1]):
            terminal_types = ", ".join(sorted(TERMINAL_ACTIONS))
            navigating_keys = ", ".join(sorted(_NAVIGATING_PRESS_KEYS))
            raise MobileSkillError(
                "invalid_sequence_order",
                f"sequence action {index - 1} ({_terminal_label(actions[index - 1])}) must be the final action",
                (
                    f"terminal actions must appear only as the last step: "
                    f"{terminal_types}, or `press` with {navigating_keys}"
                ),
            )
    return actions


def action_summary(action: dict[str, Any]) -> dict[str, Any]:
    """Return a safe result representation without exposing typed text."""
    action_type = action["type"]
    summary: dict[str, Any] = {"type": action_type}
    if "label" in action:
        summary["label"] = action["label"]
    if action_type == "type":
        summary["text_length"] = len(action["text"])
    else:
        for field in (
            "x",
            "y",
            "x1",
            "y1",
            "x2",
            "y2",
            "interval_ms",
            "duration_ms",
            "key",
            "package",
        ):
            if field in action:
                summary[field] = action[field]
    return summary
