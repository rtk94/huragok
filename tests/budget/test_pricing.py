"""Tests for ``orchestrator.budget.pricing``."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.budget.pricing import (
    PricingError,
    PricingMissingModelError,
    default_pricing_path,
    dollars_for_usage,
    ensure_models_priced,
    load_pricing,
)
from orchestrator.session.stream import UsageBlock


def test_load_default_pricing_file_parses() -> None:
    table = load_pricing()
    assert "claude-opus-4-7" in table.models
    assert "claude-sonnet-4-6" in table.models
    assert "claude-haiku-4-5-20251001" in table.models


def test_load_pricing_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PricingError):
        load_pricing(tmp_path / "nowhere.yaml")


def test_load_pricing_malformed_raises(tmp_path: Path) -> None:
    bad = tmp_path / "pricing.yaml"
    bad.write_text("version: 1\nmodels: not-a-mapping\n")
    with pytest.raises(PricingError):
        load_pricing(bad)


def test_dollars_for_usage_matches_table_math() -> None:
    table = load_pricing()
    usage = UsageBlock(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    pricing = table.models["claude-sonnet-4-6"]
    expected = (
        pricing.input_per_mtok
        + pricing.output_per_mtok
        + pricing.cache_read_per_mtok
        + pricing.cache_write_per_mtok
    )
    assert dollars_for_usage(usage, "claude-sonnet-4-6", table) == pytest.approx(expected)


def test_dollars_for_usage_unknown_model_raises() -> None:
    table = load_pricing()
    with pytest.raises(PricingMissingModelError):
        dollars_for_usage(UsageBlock(input_tokens=10), "claude-fictional-1", table)


def test_ensure_models_priced_accepts_known() -> None:
    table = load_pricing()
    ensure_models_priced(table, ["claude-opus-4-7", "claude-sonnet-4-6"])


def test_ensure_models_priced_rejects_unknown() -> None:
    table = load_pricing()
    with pytest.raises(PricingMissingModelError) as excinfo:
        ensure_models_priced(table, ["claude-opus-4-7", "claude-fictional-1"])
    assert "claude-fictional-1" in str(excinfo.value)


def test_default_pricing_path_resolves_to_shipped_file() -> None:
    path = default_pricing_path()
    assert path.is_file()
    assert path.name == "pricing.yaml"


def test_dollars_for_usage_small_delta() -> None:
    table = load_pricing()
    usage = UsageBlock(input_tokens=100, output_tokens=50)
    cost = dollars_for_usage(usage, "claude-opus-4-7", table)
    # 100 * $15/Mtok + 50 * $75/Mtok = 0.0015 + 0.00375 = 0.00525
    assert cost == pytest.approx(0.00525)
