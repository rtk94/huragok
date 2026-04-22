"""Supplemental acceptance tests for task-0001 (testwriter-authored)."""
import inspect
import hello
from hello import greet


def test_module_exists_and_exports_greet():
    assert callable(greet)


def test_greet_parameter_annotation():
    hints = greet.__annotations__
    assert hints.get('name') is str, f"expected 'name: str', got {hints}"


def test_greet_return_annotation():
    hints = greet.__annotations__
    assert hints.get('return') is str, f"expected '-> str', got {hints}"


def test_greet_docstring_present_and_single_line():
    doc = greet.__doc__
    assert doc is not None, "greet must have a docstring"
    stripped = doc.strip()
    assert stripped, "docstring must not be empty"
    assert '\n' not in stripped, f"docstring must be a single line, got: {doc!r}"


def test_no_module_level_side_effects():
    source = inspect.getsource(hello)
    lines = [l for l in source.splitlines() if l.strip() and not l.startswith('def ') and not l.startswith(' ') and not l.startswith('\t') and not l.startswith('#')]
    non_def_lines = [l for l in lines if not l.startswith('def greet')]
    assert not non_def_lines, f"unexpected module-level statements: {non_def_lines}"
