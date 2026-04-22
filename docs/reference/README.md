# Reference artifacts

Captured agent output from real Huragok smoke-test runs, preserved
verbatim. **This is not production code. Do not "clean up" files here.**

The point of this directory is that the docs citing it
(`docs/example-run.md`) can quote exactly what the agents produced. If we
edit the artifacts, those excerpts stop being true, and future readers
lose a faithful reference for what a real run actually looks like.

## Why some files would fail lint

The generated Python is written by Claude Code agents during a live run.
Agents don't always conform to this project's style rules, and that's
fine — these files are data, not code we ship. Concretely, the two
supplemental acceptance tests

- `smoke-002-artifacts/test_hello_acceptance.py`
- `smoke-002-artifacts/test_goodbye_acceptance.py`

both use `l` as a list-comprehension bind (ruff `E741`, ambiguous
variable name) and mix an `import module` with a `from module import
name` in a non-isort-ordered block (ruff `I001`). Leave them alone.

This directory is excluded from linting via
`tool.ruff.extend-exclude = ["docs/reference/"]` in `pyproject.toml`.

## Contents

### `smoke-002-artifacts/`

Phase 1 MVP's second end-to-end smoke test (2026-04-22). Two-task batch
with a `depends_on` relationship; eight sessions, all `clean`. Walked
through narratively in [`../example-run.md`](../example-run.md);
referenced as methodology evidence in
[`../smoke-tests.md`](../smoke-tests.md).

- `batch.yaml` — the submitted batch.
- `audit.jsonl` — supervisor audit log for the full run.
- `hello.py`, `test_hello.py`, `goodbye.py`, `test_goodbye.py` —
  generated target-project code (implementer-authored).
- `test_hello_acceptance.py`, `test_goodbye_acceptance.py` —
  supplemental acceptance tests (testwriter-authored; see the quirk
  note above).
- `task-0001/`, `task-0002/` — per-task artifacts: `spec.md`,
  `implementation.md`, `tests.md`, `review.md`, `status.yaml`.
