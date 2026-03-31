from __future__ import annotations

from datetime import datetime
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


class _DummyHistory:
    def __init__(
        self,
        rows: list[tuple[datetime, float | None]],
        *,
        include_close: bool = True,
    ) -> None:
        self.empty = len(rows) == 0
        self.columns = ["Close"] if include_close else ["Open"]
        self._close_rows = dict(rows)

    def __getitem__(
        self,
        column: str,
    ) -> dict[datetime, float | None]:
        if column != "Close":
            raise KeyError(column)
        return self._close_rows


def _build_settings(
    **overrides: Any,
) -> Settings:
    return Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        **overrides,
    )


def _install_yahoo_ticker_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history_by_symbol: dict[str, _DummyHistory],
) -> list[tuple[str, str, str]]:
    requests: list[tuple[str, str, str]] = []

    class _DummyTicker:
        def __init__(
            self,
            symbol: str,
        ) -> None:
            self._symbol = symbol

        def history(
            self,
            *,
            period: str,
            interval: str,
        ) -> _DummyHistory:
            requests.append((self._symbol, period, interval))
            return history_by_symbol[self._symbol]

    monkeypatch.setattr(market_data.yfinance, "Ticker", _DummyTicker)
    return requests


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


def test_yahoo_provider_uses_us10y_symbol_and_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings(
        us10y_symbol="^CUSTOM10Y",
        us10y_yahoo_period="2y",
    )
    requests = _install_yahoo_ticker_mock(
        monkeypatch,
        history_by_symbol={
            "^CUSTOM10Y": _DummyHistory(
                rows=[
                    (datetime(2025, 1, 1), 43.5),
                    (datetime(2025, 1, 2), 44.0),
                ]
            )
        },
    )

    bars = provider.get_series("us10y", settings)

    assert requests == [("^CUSTOM10Y", "2y", "1d")]
    assert [bar.close for bar in bars] == [4.35, 4.4]


def test_yahoo_provider_uses_vix_symbol_and_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings(
        vix_yahoo_symbol="^VIX_CUSTOM",
        vix_yahoo_period="5y",
    )
    requests = _install_yahoo_ticker_mock(
        monkeypatch,
        history_by_symbol={
            "^VIX_CUSTOM": _DummyHistory(
                rows=[
                    (datetime(2025, 1, 1), 18.2),
                    (datetime(2025, 1, 2), 19.1),
                ]
            )
        },
    )

    bars = provider.get_series("vix", settings)

    assert requests == [("^VIX_CUSTOM", "5y", "1d")]
    assert [bar.close for bar in bars] == [18.2, 19.1]


def test_yahoo_provider_uses_spy_symbol_and_vix_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings(
        spy_yahoo_symbol="SPY_ALT",
        vix_yahoo_period="6mo",
    )
    requests = _install_yahoo_ticker_mock(
        monkeypatch,
        history_by_symbol={
            "SPY_ALT": _DummyHistory(
                rows=[
                    (datetime(2025, 1, 1), 500.0),
                    (datetime(2025, 1, 2), 502.0),
                ]
            )
        },
    )

    bars = provider.get_series("spy", settings)

    assert requests == [("SPY_ALT", "6mo", "1d")]
    assert [bar.close for bar in bars] == [500.0, 502.0]


def test_yahoo_provider_rejects_empty_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings(
        vix_yahoo_symbol="^VIX_CUSTOM",
        vix_yahoo_period="5y",
    )
    _install_yahoo_ticker_mock(
        monkeypatch,
        history_by_symbol={"^VIX_CUSTOM": _DummyHistory(rows=[])},
    )

    with pytest.raises(ValueError, match="empty history.*series='vix'.*symbol='\\^VIX_CUSTOM'.*period='5y'"):
        provider.get_series("vix", settings)


def test_yahoo_provider_rejects_missing_close_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = YahooSeriesProvider()
    settings = _build_settings(
        spy_yahoo_symbol="SPY_ALT",
        vix_yahoo_period="1y",
    )
    _install_yahoo_ticker_mock(
        monkeypatch,
        history_by_symbol={
            "SPY_ALT": _DummyHistory(
                rows=[(datetime(2025, 1, 1), 500.0)],
                include_close=False,
            )
        },
    )

    with pytest.raises(ValueError, match="missing Close column.*series='spy'.*symbol='SPY_ALT'.*period='1y'"):
        provider.get_series("spy", settings)


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
