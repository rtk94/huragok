---
task_id: task-0001
author_agent: architect
written_at: 2026-04-22T19:40:30Z
session_id: 069e9241-6d8b-7c0e-8db6-7d126a5e9d4f
---

# Add greet() function to hello module

## Problem statement

This task seeds the repository's first production module and its test file as
part of the Huragok `smoke-002` end-to-end run. It establishes a minimal,
flat-file Python layout that a sibling task (`task-0002`) will later mirror,
so the shape chosen here sets the precedent for the batch.

## Acceptance criteria

- A Python module exists at `hello.py` in the project root.
- `hello.py` exports a callable `greet` with signature `greet(name: str) -> str`.
- `greet('World')` returns exactly `'Hello, World!'`.
- `greet('')` returns exactly `'Hello, !'`.
- `greet('  Alice  ')` returns exactly `'Hello,   Alice  !'` (input whitespace preserved verbatim).
- `greet` carries both the `name: str` parameter annotation and the `-> str` return annotation.
- `greet` has a one-line docstring (single triple-quoted string, no blank lines).
- A pytest-compatible test module exists at `test_hello.py` in the project root.
- `test_hello.py` contains at least three distinct test functions covering: (a) a normal name, (b) the empty string, (c) a whitespace-padded name; each asserts the exact expected return string.
- Running `pytest` from the project root passes all tests and emits zero warnings.

## Scope

**In scope:**
- Create `hello.py` at the project root with the `greet` function.
- Create `test_hello.py` at the project root with the three pytest test functions.
- Ensure the final `pytest` run is warning-free (no deprecation, collection, or config warnings).

**Out of scope:**
- Package layout (no `src/`, no `__init__.py`, no `pyproject.toml` packaging). Decisions log for task-0001 locks the flat layout.
- Goodbye / farewell module — that is `task-0002`'s responsibility.
- CI configuration, pre-commit hooks, linters, formatters.
- Type-checker configuration (`mypy`, `pyright`) — annotations are required but no type-checker run is gated.
- Input validation, error handling, or rejecting non-`str` arguments at runtime. The signature's annotation is the contract.

## Interface / API shape

**Module:** `hello` (file: `hello.py` at repo root)

**Function:**

```python
def greet(name: str) -> str:
    """Return a greeting addressed to name."""
    return f"Hello, {name}!"
```

Notes on the locked implementation (see `.huragok/decisions.md`):

- The body **must** be `return f"Hello, {name}!"`. This is the only single-expression formulation that passes all three whitespace cases simultaneously — any `.strip()`, `.format()` variant, or concatenation with extra spacing will fail at least one acceptance case.
- The docstring must be a single line. Acceptable forms: `"""Return a greeting addressed to name."""` or any short equivalent. It must not span multiple lines (keeps the mirror with `farewell` tight in task-0002).
- No module-level side effects (no `print`, no top-level code beyond the `def`).

**Test module:** `test_hello` (file: `test_hello.py` at repo root)

Required test functions (names may vary, but each assertion must be present):

```python
def test_greet_normal_name():
    from hello import greet
    assert greet('World') == 'Hello, World!'

def test_greet_empty_string():
    from hello import greet
    assert greet('') == 'Hello, !'

def test_greet_whitespace_padded():
    from hello import greet
    assert greet('  Alice  ') == 'Hello,   Alice  !'
```

Equivalent structures are fine (module-level `from hello import greet`,
parametrized tests, etc.) **provided** all three exact-string assertions
remain individually identifiable in the final test output and `pytest -v`
still shows at least three distinct test items.

## Dependencies

- **Depends on tasks:** none
- **New libraries:** `pytest` (runtime/test dependency). No version pin required; install via the interpreter's available package manager. Do not add it to a `requirements.txt` unless one already exists.
- **Environment:** Python 3.9+ (for `f"{var}"` and modern annotations — any currently supported CPython suffices). No environment variables, services, or network access required.

## Approach notes

- **Zero-warning requirement is load-bearing.** Before declaring done, run `pytest -W error` (or confirm `pytest` output contains `== N passed in ... ==` with no `warnings` line). A stray `PytestCollectionWarning` or `PytestUnknownMarkWarning` fails acceptance.
- **Do not add `conftest.py`** unless required to silence a warning; there is no known reason one would be needed for this scope.
- **Keep the file short.** `hello.py` should be the function definition and nothing else (no `if __name__ == "__main__":` block, no logger setup).
- **Mirror readiness.** Task-0002 will structurally clone this module. Keep naming, docstring form, and test layout boring and consistent so the mirror is a mechanical translation.

## Open questions

*(none — all ambiguities resolved in Scope and Approach notes.)*
