"""
Factor registry and factory helpers.

[INPUT]: No runtime input; imports concrete factor classes at module load.
[OUTPUT]: Registry-backed helpers to list names and instantiate factor objects.
[POS]: Boundary between CLI/runner wiring and concrete factor implementations.
       Upstream: `sentrymode.__main__` and tests.
       Downstream: `ahr999.py`, `btc_realized_pl_ratio_90d.py`, `vix.py`, `us10y.py`,
       `ai_portfolio.py`.

[PROTOCOL]:
1. Update `AVAILABLE_FACTORS` whenever factor files are added, removed, or renamed.
2. Keep registry keys stable because they are user-facing CLI identifiers.
"""

from __future__ import annotations

from sentrymode.factors.ahr999 import AHR999Factor
from sentrymode.factors.ai_portfolio import AIPortfolioFactor
from sentrymode.factors.btc_realized_pl_ratio_90d import BTCRealizedPLRatio90DFactor
from sentrymode.factors.us10y import US10YFactor
from sentrymode.factors.vix import VIXFactor
from sentrymode.monitoring import Factor

AVAILABLE_FACTORS: dict[str, type[Factor]] = {
    "ai_portfolio": AIPortfolioFactor,
    "ahr999": AHR999Factor,
    "btc_realized_pl_ratio_90d": BTCRealizedPLRatio90DFactor,
    "us10y": US10YFactor,
    "vix": VIXFactor,
}


def create_factors() -> list[Factor]:
    """Create all registered factor instances."""
    return [factor_cls() for factor_cls in AVAILABLE_FACTORS.values()]


def list_factor_names() -> list[str]:
    """Return all registered factor names."""
    return sorted(AVAILABLE_FACTORS)
