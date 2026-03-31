from __future__ import annotations

from sentrymode.factors.vix import VIXFactor
from sentrymode.market_data import YahooSeriesProvider


def test_vix_factor_uses_yahoo_provider_by_default() -> None:
    factor = VIXFactor()
    assert isinstance(factor.provider, YahooSeriesProvider)
