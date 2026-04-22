---
task_id: task-0002
author_agent: implementer
written_at: 2026-04-22T20:00:00Z
session_id: 069e9256-dafc-7d72-9fc2-4a3d7c122c2a
---

# Implementation: Add farewell() function to goodbye module, mirroring hello's structure

## Summary

Created `goodbye.py` at the project root with a single `farewell(name: str) -> str` function and `test_goodbye.py` with three pytest test functions mirroring the structure of `test_hello.py`. The implementation is a direct structural mirror of `hello.py` / `test_hello.py`, differing only in the function name (`farewell` vs `greet`), greeting word (`Goodbye` vs `Hello`), and docstring noun (`farewell` vs `greeting`). Running `pytest` from the project root collects and passes all six tests with zero warnings.

## Files touched

- `goodbye.py` — new file (+3 lines)
- `test_goodbye.py` — new file (+13 lines)

## Approach notes

- Read `hello.py` (3 lines) and `test_hello.py` (13 lines) as canonical templates before writing anything.
- `goodbye.py` is exactly 3 lines matching `hello.py`: `def` line, single-line docstring, `return` with f-string.
- `test_goodbye.py` uses `from goodbye import farewell` module-level import matching `test_hello.py`'s `from hello import greet` style.
- Ran `pytest test_hello.py test_goodbye.py -v` and confirmed `6 passed in 0.01s` with no warnings.

## Deviations from spec

*(none)*

## Caveats and known limitations

*(none)*
