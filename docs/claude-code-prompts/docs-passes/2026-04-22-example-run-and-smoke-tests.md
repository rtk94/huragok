# Huragok — Docs pass: example-run and smoke-test methodology

**Dated:** 2026-04-22
**Scope:** create two new user/operator-facing docs and update existing docs to reference them. Smoke-test artifacts from a real end-to-end run are pre-staged at `docs/reference/smoke-002-artifacts/`.

---

## Context

The root README was just refreshed to reflect that Phase 1 MVP is complete and has passed two real end-to-end smoke tests. It references two docs that don't exist yet:

- `docs/example-run.md` — a worked example using real output from the smoke-002 run.
- `docs/deployment.md` — already exists, but should be cross-linked from the new docs.

The smoke-002 artifacts have been copied into `docs/reference/smoke-002-artifacts/`. That directory contains:

- `batch.yaml` — the actual submitted batch (two tasks with `depends_on`)
- `task-0001/` — architect's `spec.md`, implementer's `implementation.md`, testwriter's `tests.md`, critic's `review.md`, and `status.yaml` with full transition history
- `task-0002/` — same shape; task 2 depends on task 1 and deliberately mirrors its structure
- `audit.jsonl` — the full audit log of the run (session launches, session ends, task.done, batch.complete)
- `hello.py`, `test_hello.py`, `test_hello_acceptance.py`, `goodbye.py`, `test_goodbye.py`, `test_goodbye_acceptance.py` — the actual code produced by the agents

Read `docs/reference/smoke-002-artifacts/` first. Read every file. Your job is to turn that raw material into reader-facing documentation, not to summarize it from a distance.

Also read:

- `README.md` (just updated — establishes the voice and what the docs should support)
- `docs/README.md` (the docs index)
- `docs/adr/ADR-0001-huragok-orchestration.md` (the system charter — understand how the five-agent pipeline is supposed to work)
- `docs/adr/ADR-0003-agent-roles-prompts.md` (the per-role responsibilities — so you can explain what each agent did and why)
- `docs/notes/slice-b2-build-notes.md` (for the known-limitations context, especially the amendment 2 post-mortem section)

---

## Deliverable 1: `docs/example-run.md`

A reader-facing walkthrough of a real two-task batch. Audience: someone who read the README, is intrigued, and wants to see what a run actually looks like before installing anything.

**Structure:**

1. **Intro (short).** One paragraph: "This is a real run from 2026-04-22, executed against a fresh scratch directory. Two tasks, deliberately trivial. Nine minutes wall clock. Purpose: show the pipeline working end-to-end, not ship real software." Link to the README for context.

2. **The batch.** Show the `batch.yaml` (or excerpt its key sections). Explain:
   - `depends_on: [task-0001]` on task-0002 is what forces ordering and makes task 2's architect read task 1's artifacts.
   - The task 2 acceptance criteria explicitly ask for a structural mirror of task 1 — this is the setup that exercises cross-task coordination.

3. **The run timeline.** Build a table from the audit log showing: session launches, roles, models, durations, end states. Commentary on what's happening between entries. Explicitly call out:
   - Task 1 goes through all four agents (architect → implementer → testwriter → critic), then transitions to `done`.
   - Supervisor picks task 2 without operator intervention.
   - Batch-complete fires on its own when task 2 reaches `done`.
   - Total: 8 sessions, all clean, zero retries, 9 minutes wall clock.

4. **What the architect produced.** Excerpt task 2's `spec.md` — specifically the sections where the architect demonstrates it understood `depends_on` meant "read the upstream task's artifacts":
   - "Read `hello.py` and `test_hello.py` first..."
   - "Do not 'improve' task-0001's choices..."
   - The explicit line-for-line mirror requirement.
   This is the flagship demonstration of cross-task coordination. Spend time on it.

5. **What the critic produced.** Excerpt task 2's `review.md` — specifically:
   - The dual-verification (AC-specified command + broader pytest) showing the critic distinguishes between AC compliance and supplementary quality.
   - The per-criterion walkthrough showing real verification, not rubber-stamp.

6. **What landed on disk.** Show the actual code: `hello.py` (3 lines), `goodbye.py` (3 lines), test files. Point out that `goodbye.py` is a structural sibling of `hello.py`, differing only in the noun. This is what "the architect read task 1's artifacts and instructed the implementer to mirror them" produced in practice.

7. **The budget.** Show the final `huragok status` output with cache sub-lines. Explain:
   - 36.5K real tokens, 7M cache tokens, $15.76 theoretical API cost.
   - On Claude Max, this consumed about 4-6% of the session-window quota — not $15.76 real dollars.
   - The cache-token dominance is a real pattern operators should understand.

8. **What this did NOT test.** Be honest — this was a contrived smoke test. Call out: no UI review gate, no iteration cycles, no rate-limit handling exercised, no real multi-hour batches, no realistic codebase complexity. The example run proves the pipeline works; it does not prove Huragok is ready for production workloads.

9. **Pointer to next steps.** Link to `docs/deployment.md` for setup; link to `docs/smoke-tests.md` for methodology.

**Tone:** Technical but personable. Matches the README. Occasional flavor is fine (the Halo reference is already well-established). No marketing polish, no exclamation-point pile-ons, no "revolutionary" or "game-changing" language. Show, don't sell.

**Length:** Roughly 150-250 lines of prose plus excerpted artifacts. If it runs longer because the excerpts are valuable, that's fine — but don't reproduce entire files where a representative excerpt would do.

**Excerpts:** Use fenced code blocks. When excerpting from an artifact, cite the source file at the start of the excerpt: `From docs/reference/smoke-002-artifacts/task-0002/spec.md:`. Don't reproduce the frontmatter blocks (those are machine-oriented, not reader-oriented).

**Factual fidelity:** Every claim about the run — timing, session count, tokens, dollars, outcomes — must match what's in `audit.jsonl`, `status.yaml`, and the artifacts. No made-up numbers. If you don't find a number in the artifacts, don't include it.

---

## Deliverable 2: `docs/smoke-tests.md`

An operator-focused methodology doc. Audience: someone setting up their own Huragok instance who wants to understand how to verify it's working, or a future contributor who wants to understand how Phase 1 was validated.

**Structure:**

1. **Purpose.** What smoke tests mean for Huragok specifically, vs. unit tests: end-to-end verification against live Claude Code, not mocked subprocesses. The test suite covers correctness of individual components; smoke tests cover integration with the real outside world.

2. **The scratch-directory pattern.** Explain:
   - Set up a throwaway git-init'd directory somewhere outside the Huragok repo.
   - Copy in the agent definitions (`.claude/agents/`), `.env`, and a custom `batch.yaml`.
   - Run `huragok submit` then `huragok run` from there.
   - Inspect artifacts and code under `.huragok/work/` and the target repo root.
   - The scratch dir is discardable; nothing there needs to be preserved except as artifacts-of-interest.

3. **Batch design for smoke tests.** Principles:
   - Trivial deliverables that exercise the pipeline without producing meaningful code. The goal is to test orchestration, not shipping software.
   - Acceptance criteria should be deterministic, mechanically verifiable (exact string equality, file existence, line counts).
   - Include at least one task with `depends_on` to exercise inter-task coordination. The second task's acceptance criteria should reference the first task's artifacts, forcing the architect to read upstream work.
   - Budget ceilings should be generous — a smoke test is not where you want budget halts to surprise you. Set `max_dollars` 5-10x higher than you'd set for realistic batches; on Max this is theoretical anyway.

4. **What smoke-001 and smoke-002 actually covered.** Brief inventory. For each:
   - What batch shape
   - What it exercised that prior tests didn't
   - What it surfaced that went into a follow-up amendment
   Reference `docs/reference/smoke-002-artifacts/` for the actual data.

5. **Known quirks and what to watch for.** Observations from real runs:
   - Cache tokens dominate real-token usage for small tasks. Watch the cache sub-lines in `huragok status`.
   - Agent-generated timestamps in `status.yaml.history` are confabulated (the agents don't have wallclock access). Pipeline semantics are correct regardless.
   - TestWriter's decision to add structural/acceptance tests is non-deterministic across runs — smoke-001 declined, smoke-002 produced a `test_*_acceptance.py` file with `inspect`-based checks. Both defensible.
   - Interrupted batches leave state.yaml in `phase: running` until amendment-2's clean-exit path is used. A `huragok reset`-style recovery command is on the polish to-do list; for now, manual state.yaml editing unblocks a new submit. (See `docs/notes/slice-b2-build-notes.md` for the full amendment history.)

6. **Verifying a successful run.** Checklist:
   - All agents ended `clean` (check `audit.jsonl` for `end_state`).
   - Every task transitioned to `done` or `blocked` (check each `work/<task-id>/status.yaml`).
   - `phase: complete` in the final `state.yaml`.
   - If Telegram is configured, a `batch-complete` notification was delivered.
   - Generated code + tests pass whatever linter/test suite the target project uses.

7. **Pointer to the example run** (`docs/example-run.md`) for a concrete instance of all this.

**Tone:** Operator-focused, direct. Less narrative than the example-run doc; more checklist and "here's how to tell if it's working." Still technical-but-personable, not a terse man page.

**Length:** 100-200 lines.

---

## Revisions to existing docs

### `docs/README.md` (docs index)

- Add entries in the appropriate section for `example-run.md` and `smoke-tests.md`.
- Match the existing voice of the index entries.

### `docs/deployment.md`

- Add a small "verifying your install" callout or section pointing at `docs/smoke-tests.md`. "After setup, a smoke test is the recommended way to confirm everything is wired correctly." One paragraph, not a rewrite.

### `docs/notes/slice-b2-build-notes.md`

- Leave alone. It's internal build history, not reader-facing.

### Root `README.md`

- Leave alone. It already references the two new docs at their target paths; creating the files is what closes the loop.

---

## What NOT to do

- Do not modify any code outside `docs/`. This is a docs-only pass.
- Do not invent numbers, durations, or behaviors that aren't in the smoke-002 artifacts.
- Do not fabricate example output that "might" happen. Use the real artifacts we captured.
- Do not produce walls of prose around excerpts. The excerpts speak for themselves; your commentary should be sparing and purposeful.
- Do not editorialize about Anthropic, Claude, or AI agents in general. Stay close to Huragok-the-project.
- Do not commit anything. Leave all changes staged or uncommitted so the operator can review.

---

## Deliverable confirmation

When done, produce a one-page summary with:

- Files created (paths + line counts)
- Files modified (paths + brief description of changes)
- Any deviations from this prompt and why
- Any open questions or items that felt ambiguous

`uv run pytest` should still pass (it was 278 green before this, no reason for it to change in a docs-only pass). Run it once as a final sanity check.
