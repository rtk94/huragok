"""Persistent rate-limit log (ADR-0002 D4).

The log records every session launch. On daemon startup we drop entries
older than seven days (the longest window any rate-limit logic cares
about), then the Supervisor queries :meth:`RateLimitLog.query` before
each session launch and handles the returned :class:`RateLimitDecision`.

This counter is approximate — Anthropic's actual limits are
authoritative — but it lets the daemon back off *before* hitting a hard
429 in the middle of a session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import yaml

from orchestrator.paths import rate_limit_log
from orchestrator.state.io import _atomic_write_yaml

__all__ = [
    "DEFAULT_WARN_THRESHOLD",
    "DEFAULT_WINDOW_CAP",
    "LOG_RETENTION_DAYS",
    "RATE_LIMIT_WINDOW_HOURS",
    "RateLimitDecision",
    "RateLimitLog",
]


RATE_LIMIT_WINDOW_HOURS: int = 5
LOG_RETENTION_DAYS: int = 7
# Heuristic caps: Anthropic publishes per-plan session caps, but the
# daemon's purpose is to back off *before* they hit. Values here are
# configurable at construction time; defaults match a generous single-
# seat Max plan's per-5h ceiling with 20% headroom.
DEFAULT_WINDOW_CAP: int = 50
DEFAULT_WARN_THRESHOLD: float = 0.8


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Result of asking the log whether it's safe to launch a session now.

    ``status`` is one of ``"ok"``, ``"warn"``, or ``"defer"``. On
    ``"defer"``, :attr:`defer_seconds` holds the number of seconds the
    caller should sleep before retrying the query.
    """

    status: Literal["ok", "warn", "defer"]
    count_in_window: int
    window_cap: int
    defer_seconds: int = 0


class RateLimitLog:
    """Persistent counter of session launches within a rolling window.

    The on-disk form is a small YAML file at
    ``.huragok/rate-limit-log.yaml`` with a single list of timestamped
    entries. :meth:`record_launch` appends; :meth:`load` truncates
    older-than-seven-day entries on daemon start; :meth:`query` returns a
    decision given the current window state.
    """

    def __init__(
        self,
        root: Path,
        *,
        window_hours: int = RATE_LIMIT_WINDOW_HOURS,
        window_cap: int = DEFAULT_WINDOW_CAP,
        warn_threshold: float = DEFAULT_WARN_THRESHOLD,
    ) -> None:
        self._path = rate_limit_log(root)
        self._window = timedelta(hours=window_hours)
        self._cap = window_cap
        self._warn_threshold = warn_threshold
        self._entries: list[datetime] = []

    @property
    def path(self) -> Path:
        """Return the on-disk path of the rate-limit log."""
        return self._path

    @property
    def entries(self) -> list[datetime]:
        """Return a copy of the in-memory entries for inspection/tests."""
        return list(self._entries)

    def load(self, *, now: datetime | None = None) -> None:
        """Read the log from disk; drop entries older than the retention cutoff.

        Silently handles missing-file and empty-file cases. Truncation
        writes back to disk via the atomic-rename protocol so a SIGKILL
        between load and first write leaves a consistent file behind.
        """
        now = now if now is not None else datetime.now(UTC)
        cutoff = now - timedelta(days=LOG_RETENTION_DAYS)

        try:
            with open(self._path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
        except FileNotFoundError:
            self._entries = []
            return
        except yaml.YAMLError:
            # A corrupt rate-limit log is not a reason to refuse to
            # start; reset it and log-warn when Slice B wires the logger.
            self._entries = []
            self._flush()
            return

        entries: list[datetime] = []
        if isinstance(data, dict):
            raw_entries = data.get("entries", [])
            if isinstance(raw_entries, list):
                for item in raw_entries:
                    parsed = _parse_entry(item)
                    if parsed is not None and parsed >= cutoff:
                        entries.append(parsed)
        self._entries = sorted(entries)
        self._flush()

    def record_launch(self, at: datetime | None = None) -> None:
        """Append one session-launch timestamp; flush to disk atomically."""
        when = at if at is not None else datetime.now(UTC)
        self._entries.append(when)
        self._flush()

    def query(self, now: datetime | None = None) -> RateLimitDecision:
        """Return the launch decision for the current moment.

        - ``ok``: the window has plenty of headroom.
        - ``warn``: the caller should proceed but also notify the operator.
        - ``defer``: the caller must sleep ``defer_seconds`` and re-query.
        """
        now = now if now is not None else datetime.now(UTC)
        window_start = now - self._window
        in_window = [ts for ts in self._entries if ts >= window_start]
        count = len(in_window)

        if count < int(self._cap * self._warn_threshold):
            return RateLimitDecision(status="ok", count_in_window=count, window_cap=self._cap)
        if count < self._cap:
            return RateLimitDecision(status="warn", count_in_window=count, window_cap=self._cap)

        # Over the cap: defer until the oldest in-window entry ages out.
        oldest = min(in_window)
        wait_until = oldest + self._window
        defer_seconds = max(1, int((wait_until - now).total_seconds()))
        return RateLimitDecision(
            status="defer",
            count_in_window=count,
            window_cap=self._cap,
            defer_seconds=defer_seconds,
        )

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    def _flush(self) -> None:
        """Persist the current in-memory entries via the atomic-write protocol."""
        payload = {
            "version": 1,
            "entries": [ts.isoformat() for ts in self._entries],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_yaml(self._path, payload)


def _parse_entry(item: object) -> datetime | None:
    """Parse one on-disk entry. Accepts ISO-8601 strings and datetimes."""
    if isinstance(item, datetime):
        return item if item.tzinfo is not None else item.replace(tzinfo=UTC)
    if isinstance(item, str):
        try:
            parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    if isinstance(item, dict):
        raw = item.get("at") or item.get("timestamp")
        return _parse_entry(raw) if raw is not None else None
    return None
