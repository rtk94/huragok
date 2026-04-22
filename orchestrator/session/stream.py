"""Pure-sync stream-json parser (ADR-0002 D2).

Claude Code's ``--output-format stream-json`` emits one JSON object per
line. The parser dispatches on the ``type`` field to a small hierarchy of
frozen dataclasses so downstream consumers (the budget tracker, the audit
log) get typed events without pulling the full raw dictionary apart every
time.

Unknown ``type`` values are tolerated as :class:`UnknownEvent` so the
format can evolve without breaking the daemon. Malformed JSON lines raise
:class:`StreamParseError`, which the session runner catches and logs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AssistantEvent",
    "ResultEvent",
    "StreamEvent",
    "StreamParseError",
    "SystemEvent",
    "UnknownEvent",
    "UsageBlock",
    "UserEvent",
    "parse_event",
]


class StreamParseError(ValueError):
    """Raised when a stream-json line is not valid JSON or not an object."""


@dataclass(frozen=True, slots=True)
class UsageBlock:
    """Token usage extracted from a stream event's ``usage`` field."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageBlock | None:
        """Build a :class:`UsageBlock` from a ``usage`` dict, or return None."""
        if not isinstance(data, dict):
            return None
        return cls(
            input_tokens=_as_int(data.get("input_tokens")),
            output_tokens=_as_int(data.get("output_tokens")),
            cache_creation_input_tokens=_as_int(data.get("cache_creation_input_tokens")),
            cache_read_input_tokens=_as_int(data.get("cache_read_input_tokens")),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SystemEvent:
    """A ``{"type":"system"}`` line — session init / sanity check."""

    raw: dict[str, Any]
    subtype: str | None = None
    session_id: str | None = None
    model: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantEvent:
    """A ``{"type":"assistant"}`` line — main-model turn with usage."""

    raw: dict[str, Any]
    session_id: str | None = None
    model: str | None = None
    usage: UsageBlock | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UserEvent:
    """A ``{"type":"user"}`` line — tool-result block. ``is_error`` surfaces failures."""

    raw: dict[str, Any]
    session_id: str | None = None
    is_error: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultEvent:
    """The terminal ``{"type":"result"}`` line — authoritative session totals."""

    raw: dict[str, Any]
    subtype: str | None = None
    session_id: str | None = None
    model: str | None = None
    usage: UsageBlock | None = None
    total_cost_usd: float | None = None
    is_error: bool = False
    duration_ms: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UnknownEvent:
    """Any ``type`` the parser does not recognise; logged and ignored by callers."""

    raw: dict[str, Any]
    type_name: str = field(default="")


StreamEvent = SystemEvent | AssistantEvent | UserEvent | ResultEvent | UnknownEvent


# ---------------------------------------------------------------------------
# Parser entry point.
# ---------------------------------------------------------------------------


def parse_event(line: str | bytes) -> StreamEvent:
    """Parse a single stream-json line into a typed :class:`StreamEvent`.

    Empty or whitespace-only input raises :class:`StreamParseError`; the
    runner never feeds us empty lines but we defend against it anyway.
    Unknown ``type`` values return :class:`UnknownEvent` so the format can
    evolve.
    """
    text = line.decode("utf-8") if isinstance(line, bytes) else line
    stripped = text.strip()
    if not stripped:
        raise StreamParseError("empty stream-json line")

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise StreamParseError(f"invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise StreamParseError(f"expected JSON object, got {type(data).__name__}")

    type_field = data.get("type")
    if type_field == "system":
        return _parse_system(data)
    if type_field == "assistant":
        return _parse_assistant(data)
    if type_field == "user":
        return _parse_user(data)
    if type_field == "result":
        return _parse_result(data)
    return UnknownEvent(raw=data, type_name=str(type_field) if type_field is not None else "")


# ---------------------------------------------------------------------------
# Per-type helpers.
# ---------------------------------------------------------------------------


def _parse_system(data: dict[str, Any]) -> SystemEvent:
    return SystemEvent(
        raw=data,
        subtype=_as_str(data.get("subtype")),
        session_id=_as_str(data.get("session_id")),
        model=_as_str(data.get("model")),
    )


def _parse_assistant(data: dict[str, Any]) -> AssistantEvent:
    message = data.get("message")
    if isinstance(message, dict):
        model = _as_str(message.get("model"))
        usage = UsageBlock.from_dict(message.get("usage"))
    else:
        model = _as_str(data.get("model"))
        usage = UsageBlock.from_dict(data.get("usage"))
    return AssistantEvent(
        raw=data,
        session_id=_as_str(data.get("session_id")),
        model=model,
        usage=usage,
    )


def _parse_user(data: dict[str, Any]) -> UserEvent:
    # ``is_error`` on tool-result user events lives under
    # message.content[*].is_error in the real stream-json schema; any true
    # value there surfaces as a subprocess-level failure signal.
    is_error = _extract_user_is_error(data)
    return UserEvent(
        raw=data,
        session_id=_as_str(data.get("session_id")),
        is_error=is_error,
    )


def _parse_result(data: dict[str, Any]) -> ResultEvent:
    return ResultEvent(
        raw=data,
        subtype=_as_str(data.get("subtype")),
        session_id=_as_str(data.get("session_id")),
        model=_as_str(data.get("model")),
        usage=UsageBlock.from_dict(data.get("usage")),
        total_cost_usd=_as_float(data.get("total_cost_usd")),
        is_error=bool(data.get("is_error", False)),
        duration_ms=_as_float(data.get("duration_ms")),
    )


def _extract_user_is_error(data: dict[str, Any]) -> bool:
    message = data.get("message")
    if not isinstance(message, dict):
        return bool(data.get("is_error", False))
    content = message.get("content")
    if not isinstance(content, list):
        return bool(message.get("is_error", False))
    return any(isinstance(block, dict) and block.get("is_error") for block in content)


def _as_int(value: Any) -> int:
    """Coerce an unknown stream-json value to int; defaults to 0."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return int(value)
    return 0


def _as_float(value: Any) -> float | None:
    """Coerce an unknown stream-json value to float; None if missing."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return None


def _as_str(value: Any) -> str | None:
    """Coerce to str; None for non-strings (including missing fields)."""
    if isinstance(value, str):
        return value
    return None
