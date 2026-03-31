from __future__ import annotations

import os

import httpx
import pytest
import yfinance


@pytest.mark.network
def test_yahoo_public_smoke() -> None:
    history = yfinance.Ticker("^VIX").history(period="5d", interval="1d")

    assert not history.empty
    assert "Close" in history.columns


@pytest.mark.network
def test_kraken_public_ohlc_smoke() -> None:
    response = httpx.get(
        "https://api.kraken.com/0/public/OHLC",
        params={"pair": "XBTUSD", "interval": 1440},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()

    assert payload.get("error") == []
    assert isinstance(payload.get("result"), dict)


@pytest.mark.network
def test_glassnode_realized_pl_ratio_smoke() -> None:
    api_key = os.environ.get("SENTRYMODE_GLASSNODE_API_KEY", "").strip()
    if not api_key:
        pytest.skip("SENTRYMODE_GLASSNODE_API_KEY is not set")

    response = httpx.get(
        "https://api.glassnode.com/v1/metrics/indicators/realized_profit_loss_ratio",
        params={"a": "BTC", "i": "24h", "api_key": api_key},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()

    assert isinstance(payload, list)
