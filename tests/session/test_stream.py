"""Tests for ``orchestrator.session.stream``."""

from __future__ import annotations

import json

import pytest

from orchestrator.session.stream import (
    AssistantEvent,
    ResultEvent,
    StreamParseError,
    SystemEvent,
    UnknownEvent,
    UsageBlock,
    UserEvent,
    parse_event,
)


def test_parse_system_event() -> None:
    line = '{"type":"system","subtype":"init","session_id":"01S","model":"claude-opus-4-7"}'
    event = parse_event(line)
    assert isinstance(event, SystemEvent)
    assert event.subtype == "init"
    assert event.session_id == "01S"
    assert event.model == "claude-opus-4-7"


def test_parse_assistant_event_nested_message() -> None:
    payload = {
        "type": "assistant",
        "session_id": "01S",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 5,
            },
        },
    }
    event = parse_event(json.dumps(payload))
    assert isinstance(event, AssistantEvent)
    assert event.model == "claude-opus-4-7"
    assert event.usage is not None
    assert event.usage.input_tokens == 100
    assert event.usage.output_tokens == 50
    assert event.usage.cache_creation_input_tokens == 10
    assert event.usage.cache_read_input_tokens == 5


def test_parse_assistant_event_flat_usage() -> None:
    payload = {
        "type": "assistant",
        "session_id": "01S",
        "model": "claude-opus-4-7",
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    event = parse_event(json.dumps(payload))
    assert isinstance(event, AssistantEvent)
    assert event.usage is not None
    assert event.usage.input_tokens == 1
    assert event.usage.output_tokens == 2


def test_parse_user_event_no_error() -> None:
    line = '{"type":"user","session_id":"01S","message":{"content":[]}}'
    event = parse_event(line)
    assert isinstance(event, UserEvent)
    assert event.is_error is False


def test_parse_user_event_with_error_block() -> None:
    payload = {
        "type": "user",
        "session_id": "01S",
        "message": {"content": [{"type": "tool_result", "is_error": True}]},
    }
    event = parse_event(json.dumps(payload))
    assert isinstance(event, UserEvent)
    assert event.is_error is True


def test_parse_result_event() -> None:
    payload = {
        "type": "result",
        "subtype": "success",
        "session_id": "01S",
        "model": "claude-opus-4-7",
        "usage": {"input_tokens": 200, "output_tokens": 100},
        "total_cost_usd": 0.042,
        "is_error": False,
        "duration_ms": 15000,
    }
    event = parse_event(json.dumps(payload))
    assert isinstance(event, ResultEvent)
    assert event.subtype == "success"
    assert event.total_cost_usd == 0.042
    assert event.usage is not None
    assert event.usage.input_tokens == 200
    assert event.duration_ms == 15000


def test_parse_unknown_type() -> None:
    line = '{"type":"toolcall","data":"whatever"}'
    event = parse_event(line)
    assert isinstance(event, UnknownEvent)
    assert event.type_name == "toolcall"


def test_parse_event_bytes_input() -> None:
    event = parse_event(b'{"type":"system","subtype":"init"}')
    assert isinstance(event, SystemEvent)
    assert event.subtype == "init"


def test_parse_malformed_line_raises() -> None:
    with pytest.raises(StreamParseError):
        parse_event("not json at all")


def test_parse_non_object_raises() -> None:
    with pytest.raises(StreamParseError):
        parse_event("[1, 2, 3]")


def test_parse_empty_line_raises() -> None:
    with pytest.raises(StreamParseError):
        parse_event("   \n")


def test_parse_result_event_defaults_when_usage_missing() -> None:
    event = parse_event('{"type":"result","subtype":"error","is_error":true}')
    assert isinstance(event, ResultEvent)
    assert event.is_error is True
    assert event.usage is None
    assert event.total_cost_usd is None


def test_usage_block_from_dict_handles_missing_keys() -> None:
    block = UsageBlock.from_dict({"input_tokens": 7})
    assert block is not None
    assert block.input_tokens == 7
    assert block.output_tokens == 0
    assert block.cache_creation_input_tokens == 0


def test_usage_block_from_none_returns_none() -> None:
    assert UsageBlock.from_dict(None) is None
    assert UsageBlock.from_dict("not-a-dict") is None  # type: ignore[arg-type]


def test_parse_unknown_type_when_field_missing() -> None:
    event = parse_event('{"foo":"bar"}')
    assert isinstance(event, UnknownEvent)
    assert event.type_name == ""
