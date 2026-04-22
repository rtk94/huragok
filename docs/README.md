# Huragok Documentation

Human-facing documentation for the Huragok orchestrator. For design-level context, start with the ADRs. For project status and build history, start with the notes.

## Contents

### `adr/` — Architectural Decision Records

Authoritative architecture. Each ADR captures a decision, its rationale, and what alternatives were rejected. ADRs are numbered sequentially (`ADR-NNNN-kebab-case-title.md`) and have a `Status:` field — `Proposed`, `Accepted`, or `Superseded by ADR-XXXX`. Read `ADR-0001` first; it's the system charter.

Reconciliation edits to earlier ADRs are recorded in a `Revision history` section at the top of the affected document. Reversals create a new ADR that supersedes the old one.

### `claude-code-prompts/` — Slice Build Prompts

Full-text prompts issued to Claude Code, one per slice, organized by phase (`phase-1/`, etc.). Pair with the corresponding `notes/slice-*-build-notes.md` to see the complete build history for a slice.

Amendment prompts are named `<slice>-prompt-amend-N.md` and declare their target (the prompt they amend) in a header block. The corresponding build notes file gets a new `## Amendment YYYY-MM-DD: <summary>` heading with a `Driven by:` line naming the prompt.

### `notes/` — Build Notes

Retrospective notes produced by Claude Code at the end of each slice. Document what shipped, notable design choices, deviations from the prompt, and known issues. These are work artifacts, not design docs — for architectural rationale, read the ADRs.

### `deployment.md` — Operator Deployment Guide

How to install, configure, and run Huragok. The target reader is someone deploying it, not contributing to it.

### `example-run.md` — Worked Example

A real two-task batch (`smoke-002`) walked end-to-end with annotated agent output. Read this if you want to see what a run actually looks like before installing anything.

### `smoke-tests.md` — Smoke-Test Methodology

How to design, run, and verify an end-to-end smoke test against live Claude Code. The recommended first run after a fresh install, and the methodology by which Phase 1 was validated.

### `reference/` — Captured Artifacts

Raw artifacts from real runs, preserved verbatim. Currently `smoke-002-artifacts/` — the agent outputs, audit log, and generated code from the Phase 1 MVP's second end-to-end smoke test. Walked through narratively in `example-run.md`.
