# Slice B1 — Daemon Core: Build Notes

**Date:** 2026-04-21
**Author:** Claude Code (Opus 4.7, 1M context)
**Scope:** Phase 1 MVP, Slice B1 (asyncio supervisor + session runners + budget tracker;
no Telegram, no systemd unit, no full error taxonomy, no `submit`/`reply`/`logs`).
**Spec:** `docs/claude-code-prompts/slice-b1-prompt.md`.
**Reviewed against:** ADR-0001, ADR-0002, ADR-0003, and the Slice A build notes.

## Summary

Shipped the async core of the Huragok orchestrator daemon:

- `orchestrator/session/` — stream-json parser (dataclass events), subprocess runner with
  SIGTERM→SIGKILL timeout escalation, and a queue-based event bus for the budget tracker.
- `orchestrator/budget/` — pricing-table loader, rate-limit log with 7-day truncation,
  and the `BudgetTracker` coroutine with optional Cost API reconciliation.
- `orchestrator/notifications/` — interface-only. `NotificationDispatcher` abstract base
  plus a `LoggingDispatcher` that logs + audits instead of sending over a network. No
  Telegram code exists in B1.
- `orchestrator/supervisor/` — asyncio event loop, signal handlers, request-file ingestion,
  role→state mapping per ADR-0003 D1, and a stdlib-only `sd_notify` stub.
- `orchestrator/pricing.yaml` — shipped with the three current model lines.
- `orchestrator/state/schemas.py` — new `ModelPricing` + `PricingTable` Pydantic models
  (the one Slice-A-foundation exception explicitly permitted in the prompt).
- CLI: `huragok run` / `stop` / `halt` promoted to real implementations; `submit`, `reply`,
  `logs`, `start` remain stubs.
- `tests/fixtures/fake-claude.sh` — deterministic stream-json emitter with five modes
  (`clean`, `crash`, `hang`, `malformed`, plus `--version` handling including an
  `old-version` escape hatch for the version-check test).
- Tests: **168 passing in ~6 s**, 85 new on top of Slice A's 83. Ruff lint + format clean.

## Module-by-module notes

### `orchestrator/session/stream.py`

Chose a **typed-dataclass hierarchy** over a dict-based dispatch:
`SystemEvent | AssistantEvent | UserEvent | ResultEvent | UnknownEvent`, all
frozen and `slots=True`, plus a `UsageBlock` leaf with `from_dict()` that tolerates
missing keys. `StreamEvent` is a `|`-union so consumers can pattern-match with
`match` / `isinstance`. The raw dict is kept on each event for audit / diagnostics.

The parser has a single entrypoint `parse_event(line: str | bytes)` that dispatches on
`type` and raises `StreamParseError` on (a) non-JSON input, (b) non-object top-level JSON,
and (c) empty/whitespace-only input. Unknown `type` values return `UnknownEvent` so the
format can evolve. Usage blocks are extracted from either the nested
`message.usage` (assistant events) or the flat `usage` (result events).

**Potential micro-ADR (flagged for review, not written):** whether to keep the
dataclass hierarchy or switch to a dict-based-with-typed-accessors model. Dataclasses
won on (i) exhaustive pattern matching in the budget tracker, (ii) downstream testability,
and (iii) readable `repr` in logs. The cost is that adding a new `type` requires a new
dataclass; given Claude Code's format stability, that's an acceptable trade.

### `orchestrator/session/runner.py`

- `run_session(...)` matches the contract from the prompt. Emits `BudgetEvent` items onto
  the tracker's queue (lifecycle markers `session-started` / `session-ended` plus one
  `stream-event` per parsed line).
- **Env scrubbing**: a small allowlist (`PATH`, `HOME`, locale vars, `TMPDIR`, `TZ`, the
  various `XDG_*`, plus `CLAUDE_CONFIG_DIR`) is copied from the parent; everything else
  is dropped. `CLAUDE_CODE_SUBAGENT_MODEL` is pinned. `ANTHROPIC_API_KEY` is forwarded
  only if the parent has it. `env=` kwarg lets callers add test markers (used by the
  supervisor integration tests for `FAKE_CLAUDE_MODE`).
- **Timeout**: `asyncio.wait_for(_await_completion(...), timeout=session_timeout_seconds)`.
  On timeout, SIGTERM → wait 30 s → SIGKILL. The pump tasks are cancelled after the
  process exits.
- **Parent SIGTERM is NOT forwarded to the child** — the subprocess finishes naturally
  and the supervisor simply stops launching new ones. This matches ADR-0002 D1.
- **End-state classification (B1 subset)**: `clean` (exit 0 + `result` without
  `is_error`), `rate-limited` (terminal `result` with `subtype` mentioning "rate"),
  `timeout`, or `dirty`. `subprocess-crash` / `context-overflow` / `transient-network`
  are B2's problem.
- **Spawn failure handling**: `FileNotFoundError` returns a dirty-end `SessionResult`
  and pushes a synthetic `session-ended` onto the queue so the tracker's bookkeeping
  stays consistent.
- `fake-claude.sh`'s hang mode uses `exec sleep 600` so SIGTERM reaches the sleeper
  directly — bash otherwise waits for its child before exiting, which used to inflate
  the timeout tests by ~30 s each.

### `orchestrator/session/events.py`

Thin dataclass wrappers. `SessionContext` carries the session_id/task_id/role/model
plus a `started_at` datetime; `BudgetEvent` is the queue payload with a
`kind: Literal["session-started", "stream-event", "session-ended"]` tag.

### `orchestrator/budget/pricing.py`

- `load_pricing(path=None)` defaults to the shipped `orchestrator/pricing.yaml`.
- `dollars_for_usage(usage, model, table)` raises `PricingMissingModelError` for
  unknown models rather than silently returning $0.
- `ensure_models_priced(table, models)` is called at supervisor startup against the
  five role-to-model values in `MODEL_FOR_ROLE`; refusing to start on a missing model
  matches ADR-0002 D4.
- The `PricingTable.updated` field accepts both `str` and `datetime.date` because
  PyYAML deserializes bare `YYYY-MM-DD` as a `date`. (Found during initial smoke test;
  the alternative — quoting the YAML — felt like a trap waiting for the next editor
  to fall into.)

### `orchestrator/budget/rate_limit.py`

- `RateLimitLog` owns `.huragok/rate-limit-log.yaml`. Constructor takes a
  configurable `window_cap` (default 50) and `warn_threshold` (default 0.8).
- `load()` drops entries older than **7 days** (ADR-0002 D4) and flushes the truncated
  file back through the atomic-write protocol so a crash-between-load-and-first-write
  can't leave stale entries.
- `query(now)` returns a `RateLimitDecision` (`ok` / `warn` / `defer <seconds>`).
  The defer calculation is "age out the oldest entry in the window" — conservative
  but correct.
- Corrupt YAML is treated as an empty log and rewritten. A malformed log file is
  not a reason to refuse to start.

### `orchestrator/budget/tracker.py`

- `BudgetTracker.run(event_queue, stop_event)` is the long-lived coroutine. On each
  iteration it races `queue.get()` against `stop_event.wait()` via
  `asyncio.FIRST_COMPLETED`, processes the event, and loops. Once stop fires it drains
  remaining events non-blockingly and returns.
- **State flush**: the snapshot is written back to `state.yaml` on every
  `session-ended` event through `read_state → mutate → write_state` so we inherit
  the Slice-A atomic-write protocol for free. No direct state-file writes from the
  tracker.
- **Threshold crossings**: emitted via `dispatcher.send(Notification.make(...))`. 80%
  and 100% are each idempotent — the `_notified_80` / `_notified_100` flags on the
  snapshot prevent notification spam when a dimension keeps accumulating past the
  line. `over_budget()` returns `True` after any 100% crossing; the supervisor reads
  this to transition the phase to `halted`.
- **Cost API reconciliation**: `CostReconciler(admin_api_key=...)` is a thin async
  HTTPX client. Only constructed when `ANTHROPIC_ADMIN_API_KEY` is present. The
  reconciler is called at session-ended from inside the tracker's event handler —
  empty or error responses log-warn and leave the local estimate in place. The
  response-parsing helper `_extract_total_usd` sums USD buckets and ignores non-USD
  entries; tests exercise happy-path, empty-payload, and malformed-payload cases via
  a `FakeReconciler` subclass.

### `orchestrator/notifications/base.py`

`Notification` is a frozen dataclass with `id` (UUIDv7 via `uuid_v7.base.uuid7`),
`kind`, `summary`, `created_at`, `artifact_path`, `reply_verbs`, `metadata`. The
`Notification.make()` classmethod builds one with `id` and `created_at` filled in and
defensively copies the `reply_verbs` / `metadata` arguments.

`NotificationDispatcher.start(stop_event)` has a default implementation that just
awaits the stop event, so subclasses only need to override it when they actually
have long-running work (which in B1 they don't; B2's `TelegramDispatcher` will).

### `orchestrator/notifications/logging.py`

`LoggingDispatcher(root=None, batch_id=None)` logs every `send()` at INFO and, if both
`root` and `batch_id` are provided, appends a `notification-sent` audit event via
`append_audit`. A `_sent: set[str]` dedupes repeats — the same notification can be
re-sent without duplicate audit entries, which matters because the supervisor may
issue the same rate-limit warning multiple times as it retries.

### `orchestrator/supervisor/loop.py`

The single biggest module in B1. Shape:

- `run(root, settings) -> int` is the top-level entry the CLI calls. Does the
  startup order: version check → pricing load + model validation → stale-tmp sweep →
  pid-file write → delegate to `run_supervisor`. On exit it cleans up the pid file,
  calls `sd_notify("STOPPING=1")`, and logs.
- `run_supervisor(...)` is split out so tests can exercise the loop without doing
  the startup bookkeeping (especially the version check and pid-file write).
- `SupervisorContext` bundles all the long-lived references and is passed into the
  inner helpers. `session_env_overrides` and `rate_limit_window_cap` are test hooks
  exposed on `run_supervisor` so integration tests can inject `FAKE_CLAUDE_MODE`
  without relaxing the production env-scrub allowlist.
- **Role selection**: `ROLE_FOR_STATE` maps the task's `status.yaml.state` to a role
  per ADR-0003 D1. Terminal states resolve to `None` (no session launch); the loop
  handles those by either marking the task done (for `software-complete` on non-UI
  tasks) or idling.
- **Retry cap**: an in-memory `attempts: dict[str, SessionAttempt]` counts consecutive
  dirty ends per task. Two dirty ends in a row → the task's `status.yaml` is
  rewritten with `state: blocked`, a `history` entry, a blocker message, and a
  `blocker` notification is dispatched. A clean end resets the counter. This is the
  B1 minimum; the full ADR-0002 D7 seven-category taxonomy is B2.
- **Halt / shutdown**: the loop checks the shutdown event at the top of every
  iteration and after `process_request_files`. It also checks `halt_after_session`
  and `tracker.over_budget()` before picking the next task; both transition the
  state to `halted` via `_transition_to_halted` and break.
- **First-task bootstrap**: if a task in `batch.yaml` has no `status.yaml` on disk,
  the supervisor creates the task directory and writes a pending status before
  selecting it. Keeps the state machine honest from the first tick.

### `orchestrator/supervisor/signals.py`

- `install_signal_handlers(loop, state)` wires SIGTERM/SIGINT → `_handle_term` and
  SIGUSR1 → `_handle_usr1`. A second SIGTERM within the same process calls
  `os._exit(128 + SIGTERM)` to bypass the graceful path, matching ADR-0002 D1's
  "second SIGTERM is SIGKILL" escalation.
- `process_request_files(root, state)` drains `.huragok/requests/` each tick:
  `stop` → `shutting_down.set()`; `halt` → `halt_after_session.set()`;
  `reply-*.yaml` → parsed and returned in the drained-requests list for the
  supervisor to forward to the dispatcher (which it doesn't do yet in B1 —
  that's the B2 reply-ingestion path).
- `sleep_or_shutdown(state, seconds)` is a small helper that makes the main loop's
  poll responsive to shutdown within a single `wait_for` call instead of a polled
  loop.

### `orchestrator/supervisor/sd_notify.py`

Stdlib-only. `sd_notify("READY=1")` writes to the `NOTIFY_SOCKET` UNIX datagram
socket if set, otherwise no-ops. Abstract-namespace sockets (`@/…`) are supported
via the canonical leading-NUL convention. Socket errors are swallowed and logged
at WARN — the daemon must not crash because systemd's notify channel is
unreachable.

### `orchestrator/cli.py` (updates)

- `run` is real: discovers the repo root, configures logging, loads settings, and
  calls `asyncio.run(supervisor.loop.run(root, settings))`. Exits with whatever the
  loop returned.
- `stop` reads `.huragok/daemon.pid`, writes a `stop` request marker as a
  belt-and-suspenders signal, and sends SIGTERM. Missing pid / stale pid / missing
  daemon all exit 0 with a friendly message — "nothing to stop" is not an error.
- `halt` writes `.huragok/requests/halt` and sends SIGUSR1 to the pid (if live).
  Returns 0 even with no daemon running.
- The CLI's `run` command reads `HURAGOK_CLAUDE_BINARY` from the environment and
  passes it through to the supervisor so tests (and operators testing against a
  dev fork of Claude Code) can override it without touching code.

### `tests/fixtures/fake-claude.sh`

Bash script with a case-per-`FAKE_CLAUDE_MODE`:

- `clean` — system + two assistants (with usage) + result; exits 0.
- `crash` — system + one assistant, writes to stderr, exits 1.
- `hang` — `exec sleep 600` so SIGTERM reaches the sleeper.
- `malformed` — emits one unparseable line between valid ones; still exits 0 with
  a valid result event so the runner's malformed-line-tolerance path is exercised.
- `--version` handling is always available and returns `2.1.91 (fake)` by default
  or `2.0.99 (fake)` when `FAKE_CLAUDE_MODE=old-version` — the second variant is
  the version-too-old test's stimulus.

The fixture is tested manually once during development and wired into the asyncio
runner tests via `claude_binary=str(FAKE_CLAUDE)` plus `env={"FAKE_CLAUDE_MODE": ...}`.

## Tests

**168 passed, 0 failed, 0 skipped, ~6 seconds.**

| Module                                    | Tests |
| ----------------------------------------- | ----- |
| tests/session/test_stream.py              | 15    |
| tests/session/test_runner.py              | 12    |
| tests/budget/test_pricing.py              | 9     |
| tests/budget/test_rate_limit.py           | 10    |
| tests/budget/test_tracker.py              | 12    |
| tests/notifications/test_base.py          | 3     |
| tests/notifications/test_logging.py       | 4     |
| tests/supervisor/test_signals.py          | 8     |
| tests/supervisor/test_sd_notify.py        | 3     |
| tests/supervisor/test_version_check.py    | 3     |
| tests/supervisor/test_loop.py             | 3     |
| tests/supervisor/test_cli_lifecycle.py    | 3     |
| (Slice A, carried forward)                | 83    |
| **Total**                                 | **168** |

Specific coverage against the prompt's "Tests" checklist:

- **Stream parser** — known types, unknown types, malformed lines, empty input,
  bytes input, nested vs. flat usage, user-is-error extraction. ✓
- **Budget tracker** — per-event updates, 80% + 100% threshold crossings (with
  idempotency), flush-to-state-yaml, `reconcile()` with a mocked Cost API,
  missing-admin-key path. ✓
- **Pricing table** — loads cleanly, rejects unknown models, refuses missing-model
  sets. ✓
- **Rate-limit log** — truncates old entries, returns `ok`/`warn`/`defer`, persists
  across reload, tolerates corrupt / malformed entries. ✓
- **Session runner** — clean / dirty / timeout / malformed-line handling; env scrub
  confirms `ANTHROPIC_API_KEY` is forwarded when present and a marker env var is
  dropped; spawn-failure dirty-end path. ✓
- **Supervisor loop** — one-iteration clean session (state + audit updated), stop
  with no pending work, two-dirty-ends-block-task flow. ✓
- **CLI lifecycle** — real-subprocess run → stop, real-subprocess run → halt,
  `stop` without daemon, `halt` without daemon, stale-pid cleanup. ✓
- **Version check** — accepts 2.1.91, rejects 2.0.99, reports missing-binary. ✓
- **sd_notify** — no-op without socket, writes with socket, swallows socket errors. ✓

### Not skipped, but worth flagging

- The two timeout-path runner tests take ~1–2 s each because the session timeout is
  deliberately tight. Total wall-clock stays under 3 seconds for the runner module.
- The CLI lifecycle tests spawn a real `huragok` subprocess; they skip cleanly if the
  venv-installed console script is not on `PATH`, so they should work in any
  `uv sync`-ed environment but degrade gracefully elsewhere.

### No tests hit external services

No test exercises the real Anthropic Cost API or Telegram. Reconciliation is tested
via a `FakeReconciler` subclass; the runner never invokes a real `claude` binary;
the dispatcher never sends a real message.

## Deviations from the prompt

1. **`status.yaml` file creation on first boot** — the prompt describes the
   supervisor reading per-task `status.yaml`s. In practice the first tick on a
   fresh repo has no status files; rather than treat that as an error, the
   supervisor creates the task directory and writes an initial `pending`
   status file. No deviation from the intent; adding it as an explicit note because
   the prompt didn't say so directly.
2. **`run_supervisor` test hooks** — `session_env_overrides` and
   `rate_limit_window_cap` are kwargs added purely so tests can inject behaviour
   that would otherwise require relaxing the production env-scrub allowlist. They
   default to `None` and have no effect in production, but they are part of the
   module's public surface so they're called out here.
3. **`DIRTY_END_CAP = 2`** is a hard constant, not a `batch.yaml` knob. The prompt
   says "a task that hits two dirty-ends in a row transitions to blocked" without
   making it configurable; B2 will replace this with the full D7 taxonomy anyway.
4. **`sd_notify` is stdlib-only** — ADR-0002 D8 says "leaning raw socket"; I went
   with that. No `systemd-python` dependency.
5. **Audit-log source of truth for `session-launched` and `session-ended`** — I
   emit these from the supervisor (after write_state / after run_session returns)
   rather than from the tracker. Keeps the audit events colocated with the state
   transitions that produced them. The tracker emits `cost-reconciliation`,
   `budget-threshold`, and (via the dispatcher) `notification-sent`.
6. **`huragok stop` writes a `stop` marker AND sends SIGTERM** — belt-and-suspenders
   so the daemon picks up the stop on the next tick even if signal delivery is
   unusual. No harm in the redundancy.

## Known issues and B2-boundary notes

### B2 plumbs in

- **Telegram dispatcher** — a `TelegramDispatcher(NotificationDispatcher)` subclass
  that implements `send()` via `httpx` and runs `getUpdates` long-polling in
  `start()`. All the interface is already in place; B2 is a subclass + `__init__`
  wiring in the supervisor.
- **`huragok reply <verb>` / `huragok submit` / `huragok logs`** — the CLI stubs
  still exit 1. The request-file parser already handles `reply-<id>.yaml`; B2
  wires that through to the dispatcher.
- **Full D7 error taxonomy** — currently B1 classifies only clean / dirty /
  timeout / rate-limited (stubbed). The `context-overflow`, `subprocess-crash`,
  `transient-network`, and `unknown` categories remain to be classified. The
  retry policy beyond the two-dirty-ends cap also lands in B2.
- **systemd unit** — `scripts/systemd/huragok.service` is B2's deliverable.
- **`huragok status` sessions breakdown** — the line still reads "N launched"
  in B1. B2 will parse the per-batch audit file to render
  "N launched, M clean, K retry".
- **`huragok status --json` extension** — B1 emits the state.yaml as-is; B2
  will add a tracker-snapshot projection for programmatic consumers.

### Sharp edges

- **`_peek_batch_id(root)` is called once at supervisor startup and never re-read**.
  If the batch changes mid-run (operator `submit`-replacing), the tracker and
  dispatcher would keep the old `batch_id`. Phase 1 isn't designed for mid-batch
  swaps, so this is a limitation-by-design, not a bug.
- **The in-memory retry counter is not durable**. A daemon restart loses the
  "how many dirty ends has this task had in a row" count. B2 will move this into
  `status.yaml.history` for persistence — the ADR-0002 D7 retry policy calls this
  out explicitly.
- **No batch-start detection on first launch**. If `state.yaml.started_at` is
  unset, the tracker's wall-clock will start from the first event rather than the
  batch's intended start. Acceptable for B1 because `submit` doesn't land until
  B2 writes the authoritative started_at.
- **`asyncio.subprocess.Process` warnings at test teardown** — occasionally
  asyncio logs an "Event loop is closed" resource warning when a subprocess
  transport finalizes after pytest closes the loop. Not an error, but visible in
  very-verbose output. Fixable by wrapping tests in an explicit loop fixture;
  deferred because the warnings don't affect correctness.

### Micro-ADR candidates flagged for review

Per the prompt's closing prompt:

1. **Stream-json parser shape** — I chose a typed-dataclass hierarchy
   (`SystemEvent | AssistantEvent | …`). The alternatives (dict-based dispatch,
   a single state-machine class) were considered and rejected for the reasons in
   the `stream.py` notes above. The choice was non-obvious, so this is worth
   either a short ADR-0008 or a one-paragraph entry in the eventual Phase-1 design
   writeup.
2. **Pricing-table update policy** — the shipped `orchestrator/pricing.yaml`
   is operator-edited. ADR-0002 D4 says the Cost API reconciles authoritatively
   when enabled, so stale table data only affects operators who don't provision
   an Admin key. My current position is "operator-edits-the-file is enough for
   Phase 1"; a micro-ADR could codify that (plus a bump-on-operator-report cadence)
   if we want to make it explicit before B2 or Phase 2.

Neither is written yet — both are ready for a quick review discussion and an
"ADR it or skip it" decision before commit.

## Conventions & tooling

- `uv run ruff check .` → **All checks passed!**
- `uv run ruff format --check .` → **48 files already formatted**
- `uv sync` completes with no warnings.
- Type hints on every public function / class / dataclass. No `Any` without an
  inline rationale comment (`root: Any  # Path — kept ``Any`` to avoid…`).
- No `# type: ignore`.
- No TODOs in code. Deferred work either raises `NotImplementedError` or is
  explicitly annotated "B2" in a comment referencing this build-notes file.

## What's next for B2

The boundaries are clean:

- `orchestrator/notifications/telegram.py` subclasses `NotificationDispatcher`;
  the supervisor's `LoggingDispatcher` construction swaps in
  `TelegramDispatcher` when a bot token is configured.
- `orchestrator/session/errors.py` (or similar) hosts the full D7 taxonomy and
  the per-category retry policy. The supervisor's `_post_session` helper is the
  one place those classifications apply.
- `orchestrator/cli.py`'s `submit`, `reply`, and `logs` become real; the first
  writes a validated `batch.yaml`, the second writes a `reply-<id>.yaml` and
  sends SIGUSR1, the third tails `logs/batch-<id>.jsonl` with optional
  filtering.
- `scripts/systemd/huragok.service` lands with the `Type=notify` contract
  already exercised by `sd_notify`.
- The `huragok status` sessions breakdown reads the audit log and counts by
  `end_state`.

None of those require reshaping the B1 module tree. The interfaces hold.
