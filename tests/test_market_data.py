from __future__ import annotations

from typing import Any

import pytest

import sentrymode.market_data as market_data
from sentrymode.market_data import GlassnodeSeriesProvider, YahooSeriesProvider
from sentrymode.monitoring import Settings


class _DummyResponse:
    def __init__(
        self,
        payload: object,
    ) -> None:
        self._payload = payload

    def raise_for_status(
        self,
    ) -> None:
        return None

    def json(
        self,
    ) -> object:
        return self._payload


def _build_settings(
    **overrides: Any,
) -> Settings:
    return Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        **overrides,
    )


def test_us10y_normalization_scales_tnx_10x_quote_to_threshold_level() -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings()

    assert provider._normalize_close("us10y", 43.5, settings) == 4.35


def test_us10y_normalization_keeps_already_scaled_quote_unchanged() -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings()

    assert provider._normalize_close("us10y", 4.35, settings) == 4.35


def test_non_us10y_normalization_is_unchanged() -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings()

    assert provider._normalize_close("vix", 22.4, settings) == 22.4


def test_glassnode_provider_parses_btc_realized_pl_ratio_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GlassnodeSeriesProvider()
    settings = _build_settings(glassnode_api_key="test-key")

    def fake_get(
        url: str,
        *,
        params: dict[str, str],
        timeout: float,
    ) -> _DummyResponse:
        assert url == "https://api.glassnode.com/v1/metrics/indicators/realized_profit_loss_ratio"
        assert params == {
            "a": "BTC",
            "api_key": "test-key",
            "i": "24h",
        }
        assert timeout == settings.glassnode_http_timeout_seconds
        return _DummyResponse(
            [
                {"t": 1735689600, "v": 0.82},
                {"t": 1735776000, "v": 1.05},
            ]
        )

    monkeypatch.setattr(market_data.httpx, "get", fake_get)

    bars = provider.get_series("btc_realized_pl_ratio", settings)

    assert [bar.close for bar in bars] == [0.82, 1.05]
    assert str(bars[0].date) == "2025-01-01"
    assert str(bars[1].date) == "2025-01-02"


def test_glassnode_provider_rejects_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GlassnodeSeriesProvider()
    settings = _build_settings(glassnode_api_key="test-key")

    monkeypatch.setattr(market_data.httpx, "get", lambda *args, **kwargs,: _DummyResponse([]))

    with pytest.raises(ValueError, match="empty or not a list"):
        provider.get_series("btc_realized_pl_ratio", settings)


def test_glassnode_provider_rejects_missing_value_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GlassnodeSeriesProvider()
    settings = _build_settings(glassnode_api_key="test-key")

    monkeypatch.setattr(
        market_data.httpx,
        "get",
        lambda *args, **kwargs,: _DummyResponse([{"t": 1735689600}]),
    )

    with pytest.raises(ValueError, match="must contain both 't' and 'v'"):
        provider.get_series("btc_realized_pl_ratio", settings)


def test_glassnode_provider_rejects_invalid_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = GlassnodeSeriesProvider()
    settings = _build_settings(glassnode_api_key="test-key")

    monkeypatch.setattr(
        market_data.httpx,
        "get",
        lambda *args, **kwargs,: _DummyResponse([{"t": "bad", "v": 1.02}]),
    )

    with pytest.raises(ValueError, match="invalid timestamp"):
        provider.get_series("btc_realized_pl_ratio", settings)


def test_glassnode_provider_requires_api_key() -> None:
    provider = GlassnodeSeriesProvider()
    settings = _build_settings(glassnode_api_key="")

    with pytest.raises(ValueError, match="requires a non-empty Glassnode API key"):
        provider.get_series("btc_realized_pl_ratio", settings)
