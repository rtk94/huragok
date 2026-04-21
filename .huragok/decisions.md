# Huragok Agent Decisions — Append-Only Log

This file captures architectural and implementation decisions made by Huragok agents during batch execution. Each entry is a timestamped block. **Entries are never edited or deleted** — superseded decisions are followed by new entries that reference the old ones.

This is supplementary to `docs/adr/` in the repo root. ADRs are deliberate, human-reviewed architectural decisions; this log captures smaller decisions agents make autonomously during work (e.g. "chose library X over Y because...", "named this parameter Z because..."). Think of it as institutional memory for the agent team.

## Format

```
## YYYY-MM-DD HH:MM:SS  <agent-role>  <batch-id>/<task-id>

<decision text — what was decided, why, what was rejected>

Tags: <comma-separated-tags>
```

## Entries

<!-- No entries yet. First entries will be added by agents during Phase 1 MVP runs. -->
