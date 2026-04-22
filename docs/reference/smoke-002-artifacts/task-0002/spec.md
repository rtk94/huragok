---
task_id: task-0002
author_agent: architect
written_at: 2026-04-22T19:45:00Z
session_id: 069e9252-2a37-7e96-82b5-4b298ce25b59
---

# Add farewell() function to goodbye module, mirroring hello's structure

## Problem statement

This task adds a sibling module to the `hello.py` seeded by `task-0001` as
part of the Huragok `smoke-002` end-to-end run. The `goodbye` module must
be a structural mirror of `hello` so the two read as a pair — same file
shape, same function shape, same docstring style, same test layout. This
exercises the supervisor's inter-task handoff: the architect must read
the upstream task's completed artifacts and base its spec on them.

## Acceptance criteria

- A Python module exists at `goodbye.py` in the project root.
- `goodbye.py` exports a callable `farewell` with signature `farewell(name: str) -> str`.
- `farewell('World')` returns exactly `'Goodbye, World!'`.
- `farewell('')` returns exactly `'Goodbye, !'`.
- `farewell('  Alice  ')` returns exactly `'Goodbye,   Alice  !'` (input whitespace preserved verbatim, matching `hello.greet`'s behaviour).
- `farewell` carries both the `name: str` parameter annotation and the `-> str` return annotation.
- `farewell` has a one-line docstring (single triple-quoted string, no blank lines), matching the form used in `hello.greet`.
- The structure of `goodbye.py` mirrors `hello.py`: same line count (3 lines), same shape (a single `def` with a single-line docstring and a single `return` statement), no extra imports, no module-level side effects.
- A pytest-compatible test module exists at `test_goodbye.py` in the project root.
- `test_goodbye.py` contains at least three distinct test functions covering: (a) a normal name, (b) the empty string, (c) a whitespace-padded name; each asserts the exact expected return string.
- `test_goodbye.py`'s structure mirrors `test_hello.py` (same import style, same number and ordering of test functions, parallel naming) so the two test files read as siblings side-by-side.
- Running `pytest` from the project root collects and passes all six tests (three from `test_hello.py`, three from `test_goodbye.py`) and emits zero warnings.

## Scope

**In scope:**
- Create `goodbye.py` at the project root with the `farewell` function.
- Create `test_goodbye.py` at the project root with the three pytest test functions.
- Verify that the combined `pytest` run picks up all six tests and is warning-free.

**Out of scope:**
- Modifying `hello.py` or `test_hello.py` in any way (they are frozen by task-0001's accepted artifacts).
- Any refactor that introduces a shared helper, base module, or "greetings" package — the explicit goal is two flat sibling modules, not abstraction.
- Package layout (no `src/`, no `__init__.py`, no `pyproject.toml` packaging) — inherited from task-0001's flat-layout decision.
- CI configuration, pre-commit hooks, linters, formatters.
- Type-checker configuration (`mypy`, `pyright`) — annotations are required but no type-checker run is gated.
- Input validation, error handling, or rejecting non-`str` arguments at runtime. The signature's annotation is the contract.
- Adding a `conftest.py` (none was needed for task-0001 and none should be needed here).

## Interface / API shape

**Module:** `goodbye` (file: `goodbye.py` at repo root)

**Function:**

```python
def farewell(name: str) -> str:
    """Return a farewell addressed to name."""
    return f"Goodbye, {name}!"
```

Notes on the locked implementation:

- The body **must** be `return f"Goodbye, {name}!"`. As with `hello.greet`, this is the only single-expression formulation that passes all three whitespace cases simultaneously — any `.strip()`, `.format()`, or concatenation variant with extra spacing will fail at least one acceptance case.
- The docstring must be a single line, in the same form as `hello.greet`'s `"""Return a greeting addressed to name."""`. The recommended phrasing is `"""Return a farewell addressed to name."""` so the two docstrings differ only in the noun.
- No module-level side effects (no `print`, no top-level code beyond the `def`).
- Final file should be exactly 3 lines: the `def` line, the docstring line, the `return` line — matching `hello.py` line-for-line.

**Test module:** `test_goodbye` (file: `test_goodbye.py` at repo root)

Required test functions (names should mirror `test_hello.py`'s pattern, swapping `greet` → `farewell`):

```python
from goodbye import farewell


def test_farewell_normal_name():
    assert farewell('World') == 'Goodbye, World!'


def test_farewell_empty_string():
    assert farewell('') == 'Goodbye, !'


def test_farewell_whitespace_padded():
    assert farewell('  Alice  ') == 'Goodbye,   Alice  !'
```

Use the same module-level `from goodbye import farewell` import style that `test_hello.py` uses (per task-0001's implementation notes). Keep the same blank-line spacing between functions. The two test files should be diff-able with only the noun and module/function names changing.

## Dependencies

- **Depends on tasks:** task-0001 (must be accepted; `hello.py` and `test_hello.py` exist at the project root and are the structural template for this task).
- **New libraries:** none (`pytest` was added by task-0001).
- **Environment:** Python 3.9+ (inherited from task-0001; the implementer noted Python 3.12 is in use). No environment variables, services, or network access required.

## Approach notes

- **Read `hello.py` and `test_hello.py` first.** Both files are committed by task-0001 and are the canonical template. Open them side-by-side with the new files and confirm the only differences are: filename, module name, function name (`greet` → `farewell`), greeting word (`Hello` → `Goodbye`), and the docstring noun (`greeting` → `farewell`).
- **Zero-warning requirement is load-bearing.** Before declaring done, run `pytest` (or `pytest -W error`) from the project root and confirm output is `== 6 passed in ... ==` with no `warnings` line. A stray `PytestCollectionWarning` or `PytestUnknownMarkWarning` fails acceptance.
- **Do not "improve" task-0001's choices.** If you notice something you would have done differently in `hello.py` / `test_hello.py`, leave it alone — those files are out of scope. The point of this task is the mirror, not a cleanup pass.
- **Keep the file short.** `goodbye.py` should be the function definition and nothing else (no `if __name__ == "__main__":` block, no logger setup, no `__all__`).

## Open questions

*(none — all ambiguities resolved in Scope and Approach notes.)*
