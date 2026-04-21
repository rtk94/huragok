# Huragok

**Autonomous multi-agent development orchestration for Claude Code.**

Huragok accepts batches of software development work and executes them using a team of specialized Claude Code sub-agents, running mostly autonomously within declared budgets of time, tokens, dollars, and rate-limit windows. It survives session caps and rate limits by persisting all state to disk and treating every Claude Code session as ephemeral.

> Named for the Huragok — the Engineers of the Halo universe. Autonomous, self-organizing constructs built to maintain and repair complex systems.

## Status

**Phase 1 (MVP): in progress.** No runnable code yet. Architecture is being defined across a series of ADRs in [`docs/adr/`](docs/adr/).

See [ADR-0001](docs/adr/ADR-0001-huragok-orchestration.md) for the system charter.

## Concept

Work is organized into **batches**. A batch is a list of tasks with acceptance criteria. The orchestrator assigns tasks to a team of specialist agents:

- **Orchestrator** coordinates the session
- **Architect** writes the spec
- **Implementer(s)** write the code (duplicatable, parallel-capable)
- **TestWriter** writes the tests
- **Critic** runs tests and reviews the work
- **Documenter** updates user-facing docs post-merge

Every artifact — spec, implementation notes, tests, review — is a file on disk under `.huragok/work/<task-id>/`. Sessions end, state survives, the next session resumes from exactly where the last left off.

## Design principles

- **State lives on disk, in the repo.** No in-memory handoffs between agents or sessions.
- **Budgets are enforced.** Wall-clock, tokens, dollars, and rate-limit windows are first-class constraints.
- **Every notification is actionable.** The operator is pinged when their judgment is needed, not to narrate progress.
- **The UI gate catches compounding errors without blocking routine work.** See ADR-0001 D6.
- **Coordination cost is paid deliberately.** Six specialist agents, not more.

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) with an active API key or Max subscription
- Git (for state coordination across machines)

## Getting started

Not yet. Come back after Phase 1 MVP is built. In the meantime, read ADR-0001.

## License

MIT. See [LICENSE](LICENSE).
