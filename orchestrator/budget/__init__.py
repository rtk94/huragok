"""Budget accounting: tokens, dollars, wall-clock, rate-limit windows.

The package ships three cooperating pieces per ADR-0002 D4: a pricing
loader (:mod:`.pricing`), a persistent rate-limit log
(:mod:`.rate_limit`), and the live :class:`BudgetTracker`
(:mod:`.tracker`) that consumes session events and updates
``state.yaml``.
"""

from orchestrator.budget.pricing import (
    PricingError,
    PricingMissingModelError,
    dollars_for_usage,
    load_pricing,
)
from orchestrator.budget.rate_limit import (
    RATE_LIMIT_WINDOW_HOURS,
    RateLimitDecision,
    RateLimitLog,
)
from orchestrator.budget.tracker import (
    BudgetSnapshot,
    BudgetTracker,
    CostReconciler,
)

__all__ = [
    "RATE_LIMIT_WINDOW_HOURS",
    "BudgetSnapshot",
    "BudgetTracker",
    "CostReconciler",
    "PricingError",
    "PricingMissingModelError",
    "RateLimitDecision",
    "RateLimitLog",
    "dollars_for_usage",
    "load_pricing",
]
