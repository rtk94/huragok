# Huragok — Claude Code Project Instructions

This file is loaded automatically by Claude Code when it starts a session in this repo. It provides project-level context for agents working **on** Huragok (as opposed to agents running inside a Huragok session on a target project — those instructions live in `.claude/agents/*.md`).

## What this project is

Huragok is an autonomous multi-agent development orchestration system. A Python daemon (the **outer orchestrator**) launches Claude Code sessions in headless mode and coordinates them against a batch queue. Inside each session, a team of specialist subagents (the **inner coordinator**) executes individual tasks. All state persists to disk under `.huragok/` so that sessions are ephemeral and progress is durable.

For the full charter, read `docs/adr/ADR-0001-huragok-orchestration.md` first.

## Architecture-first mandate

**No production code without a prior ADR.** This repo follows the same discipline as Argus: architectural decisions are written down before they are implemented. New ADRs go in `docs/adr/ADR-NNNN-kebab-case-title.md`, numbered sequentially, status `Proposed` → `Accepted` (or `Rejected` / `Superseded`).

If a change requires a design decision that isn't already covered by an existing ADR, **stop and propose an ADR first.** Do not infer design intent from code.

## Repository layout

```
huragok/
├── .claude/agents/        # Agent definitions for inner-coordinator roles.
│                          #   NOTE: These describe the agents Huragok deploys
│                          #   INTO target projects. They do not run against
│                          #   this repo under normal development.
├── .huragok/              # Runtime state. Committed. Normally empty during
│                          #   Huragok's own development; populated only when
│                          #   Huragok is dogfooding itself (Phase 2).
├── docs/adr/              # Architectural decision records. Read before coding.
├── orchestrator/          # Python daemon source. Phase 1 MVP target.
├── scripts/               # CLI tooling, notably the `huragok init` scaffold.
├── tests/                 # Test suite for the orchestrator and scaffold.
├── CLAUDE.md              # You are reading it.
├── LICENSE                # MIT.
└── pyproject.toml         # Python packaging. Managed with uv.
```

## Tooling

- **Python 3.12** — pinned in `.python-version`.
- **`uv`** is the package manager. Use `uv add <pkg>` to add dependencies, `uv sync` to install, `uv run <cmd>` to execute in the project environment. Do not mix `pip` or `poetry` into this repo.
- **`ruff`** for linting and formatting (once added).
- **`pytest`** for tests (once added).

## Working style

- **Style:** Honest critique over diplomatic hedging. Peer-level technical engagement. CLI-first workflows.
- **When in doubt, ask.** Don't invent requirements. If a task is ambiguous, surface the ambiguity before writing code.
- **When providing code samples with placeholders** (API keys, paths, credentials), mark them explicitly with comments like `# REPLACE WITH YOUR ACTUAL API KEY` — do not leave bare `"your-key-here"` strings without a callout.
- **Commits:** conventional-commits style preferred but not enforced. Small, focused, with informative messages.

## Phase 1 scope

The current phase is MVP build. Goals:

1. Python orchestrator daemon with systemd unit.
2. Six agent definitions in `.claude/agents/`.
3. Telegram notification integration (reusing OpenClaw patterns where sensible).
4. Tier-1 secret management (`EnvironmentFile=`).
5. Sequential batch execution. **No parallelism yet.**
6. Budget enforcement: wall-clock, tokens, dollars, rate-limit windows.
7. Checkpoint/resume across sessions.

Explicitly **out of Phase 1 scope**: parallel Implementers, worktree orchestration, Playwright MCP integration, the `huragok init` scaffold generator, the retrospective/iteration engine. Each of these has its own ADR coming.

## Do not

- Do not commit secrets. `.env` files and anything under `/etc/huragok/` are gitignored.
- Do not write production code without an ADR covering it.
- Do not bypass the file-based state discipline (ADR-0001 D2) by passing structured data between agents through Task prompts beyond task-folder pointers.
- Do not promote the orchestrator to a centralized LAN service without first updating ADR-0001 D8.
