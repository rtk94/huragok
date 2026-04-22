"""Supplemental acceptance tests for task-0002 (testwriter-authored)."""
import inspect
import goodbye
from goodbye import farewell


def test_module_exists_and_exports_farewell():
    assert callable(farewell)


def test_farewell_parameter_annotation():
    hints = farewell.__annotations__
    assert hints.get('name') is str, f"expected 'name: str', got {hints}"


def test_farewell_return_annotation():
    hints = farewell.__annotations__
    assert hints.get('return') is str, f"expected '-> str', got {hints}"


def test_farewell_docstring_present_and_single_line():
    doc = farewell.__doc__
    assert doc is not None, "farewell must have a docstring"
    stripped = doc.strip()
    assert stripped, "docstring must not be empty"
    assert '\n' not in stripped, f"docstring must be a single line, got: {doc!r}"


def test_goodbye_module_is_three_lines():
    source = inspect.getsource(goodbye).rstrip('\n')
    lines = source.splitlines()
    assert len(lines) == 3, f"goodbye.py must be exactly 3 lines, got {len(lines)}: {lines}"


def test_no_module_level_side_effects():
    source = inspect.getsource(goodbye)
    lines = [l for l in source.splitlines() if l.strip() and not l.startswith('def ') and not l.startswith(' ') and not l.startswith('\t') and not l.startswith('#')]
    non_def_lines = [l for l in lines if not l.startswith('def farewell')]
    assert not non_def_lines, f"unexpected module-level statements: {non_def_lines}"


def test_test_goodbye_module_has_three_test_functions():
    import test_goodbye
    test_fns = [name for name in dir(test_goodbye) if name.startswith('test_')]
    assert len(test_fns) >= 3, f"test_goodbye.py must have at least 3 test functions, found: {test_fns}"
