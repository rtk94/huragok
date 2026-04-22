---
task_id: task-0002
author_agent: testwriter
written_at: 2026-04-22T20:10:00Z
session_id: 069e925a-017c-703e-88af-9a5d64f298b1
---

# Tests: Add farewell() function to goodbye module, mirroring hello's structure

## Test inventory

Implementer-authored (in scope, counted toward coverage):
- `test_goodbye.py::test_farewell_normal_name` — covers AC-3 (normal name)
- `test_goodbye.py::test_farewell_empty_string` — covers AC-4 (empty string)
- `test_goodbye.py::test_farewell_whitespace_padded` — covers AC-5 (whitespace preserved)

Testwriter-authored (`test_goodbye_acceptance.py`):
- `test_goodbye_acceptance.py::test_module_exists_and_exports_farewell` — covers AC-1, AC-2 (module exists, callable)
- `test_goodbye_acceptance.py::test_farewell_parameter_annotation` — covers AC-6 (`name: str`)
- `test_goodbye_acceptance.py::test_farewell_return_annotation` — covers AC-6 (`-> str`)
- `test_goodbye_acceptance.py::test_farewell_docstring_present_and_single_line` — covers AC-7
- `test_goodbye_acceptance.py::test_goodbye_module_is_three_lines` — covers AC-8 (3-line file shape)
- `test_goodbye_acceptance.py::test_no_module_level_side_effects` — covers AC-8 (no side effects)
- `test_goodbye_acceptance.py::test_test_goodbye_module_has_three_test_functions` — covers AC-10

## Acceptance criterion coverage

| Criterion | Covering test(s) |
| --------- | ---------------- |
| AC-1: `goodbye.py` exists at project root | `test_module_exists_and_exports_farewell` (import would fail if absent) |
| AC-2: exports `farewell` callable | `test_module_exists_and_exports_farewell` |
| AC-3: `farewell('World')` → `'Goodbye, World!'` | `test_farewell_normal_name` |
| AC-4: `farewell('')` → `'Goodbye, !'` | `test_farewell_empty_string` |
| AC-5: whitespace preserved verbatim | `test_farewell_whitespace_padded` |
| AC-6: `name: str` and `-> str` annotations | `test_farewell_parameter_annotation`, `test_farewell_return_annotation` |
| AC-7: one-line docstring | `test_farewell_docstring_present_and_single_line` |
| AC-8: 3-line file, single def, no side effects | `test_goodbye_module_is_three_lines`, `test_no_module_level_side_effects` |
| AC-9: `test_goodbye.py` exists at project root | `test_test_goodbye_module_has_three_test_functions` (import would fail if absent) |
| AC-10: `test_goodbye.py` has ≥3 test functions | `test_test_goodbye_module_has_three_test_functions` |
| AC-11: 6 tests pass, zero warnings | Full run verified with `pytest -W error` |
| AC-structural: mirrors `test_hello.py` | Visual inspection only — see coverage gaps |

## Run results

Command: `python -m pytest test_hello.py test_goodbye.py test_hello_acceptance.py test_goodbye_acceptance.py -v`

- **Passed:** 18
- **Failed:** 0
- **Skipped:** 0

Command (spec requirement — exactly 6 tests, zero warnings): `python -m pytest test_hello.py test_goodbye.py -v -W error`

- **Passed:** 6
- **Failed:** 0
- **Skipped:** 0

## Mutation testing results

`mutmut` is not installed in this environment (`python -m mutmut` exits with "No module named mutmut"). Mutation testing was skipped.

## Coverage gaps

- **AC-structural (mirror shape):** The spec requires `test_goodbye.py` to mirror `test_hello.py` in naming and ordering. This is confirmed by inspection — the two files differ only in module/function name and greeting word — but no automated test enforces it, as string-matching on source is fragile and subjective. Treated as a human-review criterion.
- **AC-11 (zero-warnings for full `pytest` root run):** The spec says running `pytest` from the project root must emit zero warnings. The root currently has untracked files (`batch.yaml`, `__pycache__/`, etc.) that are not test files; pytest only collects files matching `test_*.py` / `*_test.py` so these do not affect collection. The `-W error` run against all six functional tests confirmed zero warnings.
