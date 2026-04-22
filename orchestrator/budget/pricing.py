"""Pricing-table loader and per-event dollar estimation (ADR-0002 D4).

``orchestrator/pricing.yaml`` is the daemon's local source of dollar
truth; :func:`load_pricing` validates the file against the
:class:`~orchestrator.state.PricingTable` Pydantic model, and
:func:`dollars_for_usage` converts a :class:`~orchestrator.session.UsageBlock`
to a live-estimate dollar figure.

The daemon refuses to start if any model referenced by an active session
is missing from the table — :func:`ensure_models_priced` is the hook the
supervisor calls during startup.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

from orchestrator.session.stream import UsageBlock
from orchestrator.state import PricingTable

__all__ = [
    "PricingError",
    "PricingMissingModelError",
    "default_pricing_path",
    "dollars_for_usage",
    "ensure_models_priced",
    "load_pricing",
]


class PricingError(ValueError):
    """Base class for pricing-table errors."""


class PricingMissingModelError(PricingError):
    """Raised when a referenced model is not present in the pricing table."""


def default_pricing_path() -> Path:
    """Return the shipped ``orchestrator/pricing.yaml`` path."""
    return Path(__file__).resolve().parent.parent / "pricing.yaml"


def load_pricing(path: Path | None = None) -> PricingTable:
    """Read and validate the pricing YAML; defaults to the shipped table.

    Raises :class:`PricingError` if the file is missing or malformed.
    """
    target = path if path is not None else default_pricing_path()
    if not target.is_file():
        raise PricingError(f"pricing table not found at {target}")
    try:
        with open(target, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise PricingError(f"could not parse {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise PricingError(f"pricing table {target} is not a YAML mapping")
    try:
        return PricingTable.model_validate(data)
    except Exception as exc:
        raise PricingError(f"pricing table {target} failed validation: {exc}") from exc


def dollars_for_usage(usage: UsageBlock, model: str, table: PricingTable) -> float:
    """Estimate the dollar cost of ``usage`` for ``model`` using ``table``.

    Raises :class:`PricingMissingModelError` if ``model`` is not in the
    pricing table. The daemon's startup check means we should never see
    this at runtime, but the explicit error means a regression surfaces
    loudly instead of producing silent $0.00 estimates.
    """
    pricing = table.models.get(model)
    if pricing is None:
        raise PricingMissingModelError(
            f"model {model!r} is not listed in pricing.yaml; cannot estimate cost"
        )
    return (
        usage.input_tokens * pricing.input_per_mtok
        + usage.output_tokens * pricing.output_per_mtok
        + usage.cache_read_input_tokens * pricing.cache_read_per_mtok
        + usage.cache_creation_input_tokens * pricing.cache_write_per_mtok
    ) / 1_000_000.0


def ensure_models_priced(table: PricingTable, models: Iterable[str]) -> None:
    """Raise :class:`PricingMissingModelError` if any model is unpriced.

    Called by the supervisor at daemon startup against the set of models
    the current batch will actually use (Architect + Implementer +
    TestWriter + Critic + Documenter roles). Refusing to start is ADR-0002
    D4's contract — we don't silently estimate at $0 for an unknown model.
    """
    missing = [m for m in models if m not in table.models]
    if missing:
        raise PricingMissingModelError(
            "models missing from pricing table: " + ", ".join(sorted(set(missing)))
        )
