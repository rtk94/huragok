"""Session subprocess lifecycle and stream-json parsing.

The :mod:`orchestrator.session` package owns everything that spans the
boundary between the Python supervisor and an individual ``claude -p``
invocation: the stream-json line parser, the subprocess runner, and the
event dataclasses that feed the budget tracker. See ADR-0002 D2.
"""

from orchestrator.session.events import (
    BudgetEvent,
    BudgetEventKind,
    SessionContext,
)
from orchestrator.session.runner import (
    DEFAULT_SESSION_PROMPT,
    SESSION_END_STATES,
    SessionResult,
    default_session_env,
    run_session,
)
from orchestrator.session.stream import (
    AssistantEvent,
    ResultEvent,
    StreamEvent,
    StreamParseError,
    SystemEvent,
    UnknownEvent,
    UsageBlock,
    UserEvent,
    parse_event,
)

__all__ = [
    "DEFAULT_SESSION_PROMPT",
    "SESSION_END_STATES",
    "AssistantEvent",
    "BudgetEvent",
    "BudgetEventKind",
    "ResultEvent",
    "SessionContext",
    "SessionResult",
    "StreamEvent",
    "StreamParseError",
    "SystemEvent",
    "UnknownEvent",
    "UsageBlock",
    "UserEvent",
    "default_session_env",
    "parse_event",
    "run_session",
]
