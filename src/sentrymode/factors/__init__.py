"""
Factor registry and factory helpers.

[INPUT]: No runtime input; imports concrete factor classes at module load.
[OUTPUT]: Registry-backed helpers to list names and instantiate factor objects.
[POS]: Boundary between CLI/runner wiring and concrete factor implementations.
       Upstream: `sentrymode.__main__` and tests.
       Downstream: `ahr999.py`, `vix.py`.

[PROTOCOL]:
1. Update `AVAILABLE_FACTORS` whenever factor files are added, removed, or renamed.
2. Keep registry keys stable because they are user-facing CLI identifiers.
"""

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
