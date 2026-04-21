# `.huragok/` — Huragok Runtime State

This directory is managed by [Huragok](../README.md), an autonomous multi-agent development orchestration system built on Claude Code. If you're reading this because you cloned a repo and wondered what this directory is: it holds the state of Huragok's batched work against this codebase.

## What lives here

- **`batch.yaml`** — the currently active batch: a list of tasks Huragok is working on, with acceptance criteria and priorities.
- **`state.yaml`** — the orchestrator's runtime state: current task, session count, consumed budget, last notification.
- **`decisions.md`** — append-only log of architectural decisions made by agents during batch execution. Useful context for reviewers.
- **`retrospectives/`** — end-of-batch and end-of-iteration retros. One file per batch.
- **`work/<task-id>/`** — one folder per task, containing:
  - `spec.md` — the Architect's specification
  - `implementation.md` — the Implementer's notes on what was built
  - `tests.md` — the TestWriter's notes, including mutation-testing survival rate
  - `review.md` — the Critic's pass / fail / block verdict
  - `ui-review.md` — (UI tasks only) screenshots, visual-critic notes, human-gate status
  - `status.yaml` — task state machine position

## Why it's committed

Huragok treats every Claude Code session as ephemeral and state as durable (see ADR-0001 D2). Committing this directory means:

1. Checkpoint and resume work across machines, sessions, and rate-limit pauses.
2. Full audit trail of every agent decision and artifact.
3. Reviewers can see exactly what was asked for, what was built, and what was tested.

## Can I ignore this?

If you're a human collaborator not using Huragok: yes, mostly. Treat `work/` folders as supplemental context if you're reviewing a PR, and skim `decisions.md` if you need to understand why something is the way it is. You don't need to edit anything here manually — Huragok owns it.

## Can I delete this?

If the repo is not currently an active Huragok target, you can delete `work/*/` folders that are marked `done` in their `status.yaml`. Don't delete `batch.yaml` or `state.yaml` while a batch is in flight — you'll lose checkpoint context. When in doubt, leave it alone.
