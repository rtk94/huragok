# Smoke testing Huragok

Methodology for verifying a Huragok install end-to-end against live
Claude Code. Audience: an operator confirming a fresh install works,
or a contributor wanting to know how Phase 1 was validated. For a
worked example with annotated output, see
[`example-run.md`](example-run.md).

## What "smoke test" means here

The unit and component tests under `tests/` exercise the orchestrator
in isolation. No real `claude -p` subprocesses, no real Telegram, no
real Anthropic billing. They run in ~9 seconds and they prove the
orchestrator is internally consistent.

A smoke test is the complement: end-to-end against the real outside
world. Live Claude Code subprocesses, real model calls, real auth,
real artifacts on disk, real Telegram if configured. The test suite
proves the orchestrator works in a vacuum; a smoke test proves it
integrates with the systems it depends on. You want both.

## The scratch-directory pattern

Smoke tests don't run inside the Huragok repo. They run in a
throwaway directory configured to look like a target project, so the
daemon and CLI are exercised exactly the way an operator would.

```bash
# Anywhere outside the Huragok repo
mkdir ~/huragok-smoke && cd ~/huragok-smoke
git init

# The agent definitions Huragok deploys into target projects
mkdir -p .claude/agents
cp /path/to/Huragok/.claude/agents/*.md .claude/agents/

# Auth + notification config (see deployment.md for variables)
cp /path/to/Huragok/.env.example .env
$EDITOR .env

# Author the batch
$EDITOR batch.yaml

# Submit and run
uv --project /path/to/Huragok run huragok submit ./batch.yaml
uv --project /path/to/Huragok run huragok run
```

Artifacts and code land under `.huragok/work/<task-id>/` and at the
scratch root. The whole directory is discardable; preserve only what
you want as artifacts of interest. (For example, the `smoke-002`
artifacts under `docs/reference/smoke-002-artifacts/` were copied out
of the scratch directory after the run.)

The scratch dir being a real `git init`'d tree matters — several
agent prompts assume they're inside a working tree, and `huragok
submit`'s archive path is easier to reason about when the working
directory is clean.

## Designing a batch for smoke testing

The goal is to exercise orchestration, not to ship software. Design
accordingly:

- **Trivial deliverables.** Code small enough that visual diffing
  takes seconds: three-line Python functions, single-route Flask
  endpoints, a one-paragraph README patch. You want to verify *that*
  the agents produced it, not whether the code is good.

- **Mechanically verifiable acceptance criteria.** Phrase ACs as
  exact string equalities, file existence, line counts, pytest
  collection counts. Avoid "looks reasonable." The smoke-002 ACs
  said things like ``Calling `greet('  Alice  ')` returns exactly the
  string `'Hello,   Alice  !'`  (whitespace preserved)`` — exact
  matches make the critic's verdict load-bearing.

- **At least one `depends_on`.** Single-task batches don't exercise
  inter-task handoff, supervisor task selection, or the cross-task
  artifact-reading path. A two-task batch where task 2 references
  task 1's artifacts is the minimum useful shape — smoke-002 forced
  task 2's `goodbye.py` to be a structural mirror of task 1's
  `hello.py`, which made the architect for task 2 read task 1's spec
  and source as the canonical template.

- **Generous budgets.** A smoke test is not where you want a budget
  halt to surprise you. Set `max_dollars` 5-10× higher than you'd
  set for a real batch (on Max it's theoretical anyway — see
  [`deployment.md`](deployment.md#budget-interpretation-for-max-vs-api)).
  Set `wall_clock_hours` to at least 2× the expected run. Keep
  `max_iterations` small (1 or 2) so a misbehaving agent stops
  re-litigating instead of consuming the wall clock on retries.

## What smoke-001 and smoke-002 actually covered

**smoke-001 (2026-04-22, ~4 minutes).** Single-task batch: add a
one-function Python module with three pytest tests. Four sessions
(Architect → Implementer → TestWriter → Critic), all `clean`. First
real validation of the full pipeline against live Claude Code.

What it surfaced (all closed by amendment 2 in
[`notes/slice-b2-build-notes.md`](notes/slice-b2-build-notes.md#amendment-2026-04-22-smoke-test-post-mortem-fixes)):
no cache-token sub-lines in `huragok status`; no `complete` phase
transition (the daemon would idle-loop after the last task instead
of exiting); a 25-second SIGINT-when-idle delay caused by a wedged
Telegram long-poll; `/start` from a freshly-added bot logging as
`invalid_verb`; `huragok status` raising on a fresh `.huragok/`
without a `state.yaml`; undocumented auth/billing edges around
`CLAUDE_CODE_OAUTH_TOKEN` and Max-vs-API. Nine items total.

**smoke-002 (2026-04-22, ~9 minutes).** Two-task batch with a
`depends_on` relationship. Eight sessions, all `clean`, zero retries.
Exercised what smoke-001 didn't: multi-task supervisor path,
inter-task artifact handoff, autonomous `batch-complete` transition,
the cache-token sub-lines actually rendering. No follow-up amendment
required. Walked through in [`example-run.md`](example-run.md); raw
artifacts under `docs/reference/smoke-002-artifacts/`.

## Known quirks worth knowing about

Things that look weird in a smoke run output but are working as
designed:

- **Cache tokens dominate real-token usage.** On a small task, expect
  cache reads + writes to be one-to-two orders of magnitude larger
  than input + output (smoke-002 hit ~200×). The `huragok status`
  main `Tokens:` percentage uses input + output only, matching the
  budget enforcement aggregate, so the displayed percent will look
  implausibly low until you read the cache sub-lines.

- **Agent-generated timestamps in `status.yaml.history` are
  confabulated.** Agents don't have wall-clock access; the
  timestamps in architect / implementer / testwriter / critic
  history rows are guesses written by the agent. Supervisor-driven
  transitions (e.g. `software-complete → done`, `by: supervisor`,
  `session_id: null`) carry real timestamps. State-machine
  semantics are correct regardless — the supervisor never reads
  agent-supplied timestamps for control flow. For authoritative
  per-session timing, read `audit.jsonl`.

- **TestWriter's choice to add a `test_*_acceptance.py` file is
  non-deterministic.** The role allows it but doesn't require it.
  smoke-001 declined; smoke-002 produced
  `test_hello_acceptance.py` and `test_goodbye_acceptance.py` with
  `inspect`-based checks for annotations, docstring shape, line
  count, and module-level-side-effect absence. Both outcomes are
  defensible — if your ACs are fully covered by the
  implementer-authored tests, expect the testwriter to skip the
  supplemental file; if there are structural ACs the implementer's
  tests don't directly assert, expect it to materialise.

- **SIGKILL leaves `phase: running`.** SIGTERM and SIGINT are
  caught and drain cleanly (amendment 2). SIGKILL and equivalents
  by definition can't be. If a run is killed uncleanly,
  `state.yaml.phase` is not rewound, and `huragok submit` will
  refuse to overwrite the in-flight batch. Unblock by either
  `huragok stop` (if the daemon is somehow still alive) or by
  hand-editing `.huragok/state.yaml` to `phase: idle`. A
  `huragok reset` command is a polish to-do.

## Verifying a successful run

After the daemon exits, walk this checklist. Anything missing means
either the run did not happen, or it did not happen the way you
think:

- [ ] **Every session ended `clean`.** In `audit.jsonl`, every
      `session-ended` record carries `"end_state": "clean"` and
      `"category": "clean-end"`. Anything else means a classifier
      branch fired and the run is not a pure happy-path validation.
- [ ] **Every task is in a terminal state.** Each
      `.huragok/work/<task-id>/status.yaml` has `state: done` or
      `state: blocked`. `done` is the happy path; `blocked` is a
      legitimate terminal state but not what a smoke run should aim
      for.
- [ ] **`state.yaml.phase` is `complete`.** `huragok status` renders
      `Phase: complete`. The supervisor's `_batch_is_complete`
      check fired and the daemon exited.
- [ ] **A `batch-complete` audit event was written.** Last record
      in `audit.jsonl` is `{"kind": "batch-complete", ...}` with
      `session_count` matching the sessions you expected.
- [ ] **If Telegram is configured, a `batch-complete` notification
      arrived.** The dispatcher emits an FYI message (no reply
      verbs, per ADR-0001 D5) when phase flips to `complete`. The
      `telegram.send.ok` record in `.huragok/logs/batch-<id>.jsonl`
      confirms.
- [ ] **The generated code passes the target project's own checks.**
      The previous items prove the daemon did its job; this one
      proves the agents did theirs. For a Python smoke batch,
      `pytest -W error` from the scratch root is usually enough.

If any item fails, the artifacts under `.huragok/work/<task-id>/`,
`.huragok/audit/<batch-id>.jsonl`, and `.huragok/logs/batch-<id>.jsonl`
(or `huragok logs`) are where you start digging.

## See also

- [`example-run.md`](example-run.md) — concrete instance of
  everything in this document.
- [`deployment.md`](deployment.md) — install, auth, billing,
  systemd, troubleshooting.
- [`notes/slice-b2-build-notes.md`](notes/slice-b2-build-notes.md) —
  build history and amendment trail behind the Phase 1 MVP,
  including the smoke-001 post-mortem fixes.
