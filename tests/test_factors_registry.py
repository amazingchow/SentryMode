from __future__ import annotations

from sentrymode.factors import AVAILABLE_FACTORS, create_factors, list_factor_names


def test_list_factor_names_matches_registry_keys() -> None:
    assert list_factor_names() == sorted(AVAILABLE_FACTORS)


def test_create_factors_instantiates_every_registered_factor() -> None:
    factors = create_factors()

    assert len(factors) == len(AVAILABLE_FACTORS)
    assert sorted(factor.name for factor in factors) == sorted(AVAILABLE_FACTORS)
