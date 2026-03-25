from __future__ import annotations

from sentrymode.market_data import YahooSeriesProvider
from sentrymode.monitoring import Settings


def test_us10y_normalization_scales_tnx_10x_quote_to_threshold_level() -> None:
    provider = YahooSeriesProvider()
    settings = Settings(_env_file=None)

    assert provider._normalize_close("us10y", 43.5, settings) == 4.35


def test_us10y_normalization_keeps_already_scaled_quote_unchanged() -> None:
    provider = YahooSeriesProvider()
    settings = Settings(_env_file=None)

    assert provider._normalize_close("us10y", 4.35, settings) == 4.35


def test_non_us10y_normalization_is_unchanged() -> None:
    provider = YahooSeriesProvider()
    settings = Settings(_env_file=None)

    assert provider._normalize_close("vix", 22.4, settings) == 22.4
