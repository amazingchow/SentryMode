"""Factor registry."""

from __future__ import annotations

from sentrymode.factors.ahr999 import AHR999Factor
from sentrymode.factors.vix import VIXFactor
from sentrymode.monitoring import Factor

AVAILABLE_FACTORS: dict[str, type[Factor]] = {
    "ahr999": AHR999Factor,
    "vix": VIXFactor,
}


def create_factors() -> list[Factor]:
    """Create all registered factor instances."""
    return [factor_cls() for factor_cls in AVAILABLE_FACTORS.values()]


def list_factor_names() -> list[str]:
    """Return all registered factor names."""
    return sorted(AVAILABLE_FACTORS)
