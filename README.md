# Huragok

**Autonomous multi-agent development orchestration for Claude Code.**

Huragok is a Python daemon that orchestrates [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) through a five-role pipeline — Architect, Implementer, TestWriter, Critic, Documenter — to autonomously execute development tasks described in a YAML batch file. It's designed for well-scoped work you'd otherwise do yourself but would rather delegate overnight, and it's built to survive session caps, rate limits, and interruptions by persisting every piece of state to disk.

> Named for the [Huragok](https://halo.fandom.com/wiki/Huragok) — the Engineers of the Halo universe. Autonomous, self-organizing constructs built to maintain and repair complex systems. The name is a deliberate reminder that autonomy should be bounded and supervised.

## Status

**Phase 1 MVP: complete.** The daemon runs, the pipeline works end-to-end, and two real integration smoke tests have passed against live Claude Code — one single-task, one multi-task with a `depends_on` relationship. 278 tests in the suite, all green.

It's not yet dogfooded against production code and there are [known rough edges](docs/notes/slice-b2-build-notes.md#amendment-2026-04-22-smoke-test-post-mortem-fixes). Phase 2 will add human-in-the-loop UI review, multi-batch orchestration, richer error recovery, and dogfooding against real repositories. Feedback and issues are welcome — this is a project in motion.

See [`docs/README.md`](docs/README.md) for the docs index and [ADR-0001](docs/adr/ADR-0001-huragok-orchestration.md) for the system charter.

## How it works

Work is organized into **batches**. A batch is a YAML file listing tasks with acceptance criteria and optional `depends_on` relationships. The supervisor reads the batch, picks the next non-terminal task, and runs it through five specialist agents in sequence:

- **Architect** reads the task description and upstream task artifacts, then writes a `spec.md` — problem statement, acceptance criteria, scope boundaries, and interface shape.
- **Implementer** reads the spec and writes the actual code, producing an `implementation.md` alongside any source files.
- **TestWriter** writes pytest tests covering the acceptance criteria, producing a `tests.md`.
- **Critic** runs the tests, reviews the implementation against the spec, and produces a `review.md` with an `accept` or `reject` verdict.
- **Documenter** (activated in later pipeline stages) updates user-facing docs after the batch is merged.

Each agent runs as its own [`claude -p`](https://docs.claude.com/en/docs/claude-code/sdk) subprocess with a tailored system prompt. Artifacts land in `.huragok/work/<task-id>/` on disk. Sessions end, state survives, the next session resumes exactly where the last left off.

The supervisor enforces per-batch budgets — wall-clock, tokens, dollars, session timeouts, iteration counts — and sends actionable notifications via Telegram when operator judgment is needed. A systemd unit file ships in `deploy/` for long-running deployments.

## Design principles

- **State lives on disk, in the repo.** No in-memory handoffs between agents or sessions.
- **Budgets are enforced.** Wall-clock, tokens, dollars, and rate-limit windows are first-class constraints.
- **Every notification is actionable.** The operator is pinged when their judgment is needed, not to narrate progress.
- **The UI gate catches compounding errors without blocking routine work.** See [ADR-0001 D6](docs/adr/ADR-0001-huragok-orchestration.md).
- **Coordination cost is paid deliberately.** Five specialist agents, not more.

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) 2.1+ with an active Claude Max subscription or `ANTHROPIC_API_KEY`
- Git
- Optional: a Telegram bot for notifications

## Quickstart

```bash
# Clone and install
git clone git@github.com:rtk94/Huragok.git
cd Huragok
uv sync

# One-time: authenticate Claude Code against your Max subscription
claude login

# In your target project directory, configure Huragok
cp .env.example /path/to/your/project/.env   # edit as needed
# Copy agent definitions into the target project
mkdir -p /path/to/your/project/.claude/agents
cp .claude/agents/*.md /path/to/your/project/.claude/agents/

# Write a batch.yaml describing the tasks you want done
# See docs/example-run.md for a real two-task batch

# Submit and run
cd /path/to/your/project
uv --project /path/to/Huragok run huragok submit ./batch.yaml
uv --project /path/to/Huragok run huragok run
```

The daemon writes structured JSON logs to stdout and a batch-scoped log file under `.huragok/logs/`. Monitor progress with `huragok status` in another terminal. When all tasks reach a terminal state (`done` or `blocked`), the daemon exits cleanly and — if configured — notifies you on Telegram.

For the real setup including authentication, systemd, and Telegram configuration, see [`docs/deployment.md`](docs/deployment.md).

For a worked example of an actual run with annotated agent output, see [`docs/example-run.md`](docs/example-run.md).

## What "Phase 1" means

The [phase roadmap](docs/adr/ADR-0001-huragok-orchestration.md) is:

- **Phase 1 (complete):** single-daemon, sequential batches, five-agent pipeline, budget enforcement, Telegram notifications, systemd deployment.
- **Phase 2:** human-in-the-loop UI review gate, richer retrospective/iteration cycles, dogfooding against Huragok's own ADRs.
- **Phase 3:** Guituner — Android test app, surfaces the Playwright and foundational-UI paths.
- **Phase 4:** Argus — real-world integration against a non-trivial codebase.

## License

MIT. See [LICENSE](LICENSE).
