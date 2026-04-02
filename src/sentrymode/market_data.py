"""
Shared daily market-data adapter seam.

[INPUT]: Series name + `Settings` with provider symbols/periods and timeout values.
[OUTPUT]: Normalized ascending `DailyBar` sequences for downstream factor calculations.
[POS]: Shared adapter module in `src/sentrymode`.
       Upstream: factor modules (`vix.py`, `us10y.py`, `btc_realized_pl_ratio_90d.py`,
       `ai_portfolio.py`).
       Downstream: Yahoo Finance API and Glassnode API.

[PROTOCOL]:
1. Keep provider seam (`DailySeriesProvider`) stable so factors can swap data backends.
2. Surface malformed payloads as explicit exceptions; do not silently coerce unknown schemas.
3. Keep Yahoo query parameters factor-scoped (`us10y_*`, `vix_*`, `portfolio_*`) to avoid
   cross-factor coupling while still supporting generic `ticker:<SYMBOL>` portfolio lookups.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

import httpx
import yfinance

from sentrymode.monitoring.settings import Settings


@dataclass(slots=True, frozen=True)
class DailyBar:
    """Normalized daily scalar series sample used by factors."""

    date: date
    close: float


class DailySeriesProvider(Protocol):
    """Protocol for loading normalized daily bar series."""

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        """Return a daily series sorted by ascending date."""


class YahooSeriesProvider:
    """Load daily close series from Yahoo Finance via yfinance."""

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        """Fetch and normalize the requested series from Yahoo Finance."""
        normalized_name = series_name.strip().lower()
        symbol, period = self._resolve_query(series_name, settings)
        history = yfinance.Ticker(symbol).history(period=period, interval="1d")
        if history.empty:
            raise ValueError(
                "Yahoo Finance returned empty history "
                f"for series='{normalized_name}', symbol='{symbol}', period='{period}'."
            )
        if "Close" not in history.columns:
            raise ValueError(
                "Yahoo Finance response is missing Close column "
                f"for series='{normalized_name}', symbol='{symbol}', period='{period}'."
            )

        bars: list[DailyBar] = []
        for index, close in history["Close"].items():
            if close is None:
                continue
            close_value = float(close)
            if not math.isfinite(close_value) or close_value <= 0:
                continue
            bar_date = index.date()
            bars.append(
                DailyBar(
                    date=bar_date,
                    close=self._normalize_close(normalized_name, close_value, settings),
                )
            )

        if not bars:
            raise ValueError(
                "Yahoo Finance history has no valid close rows "
                f"for series='{normalized_name}', symbol='{symbol}', period='{period}'."
            )
        return sorted(bars, key=lambda bar,: bar.date)

    def _resolve_query(
        self,
        series_name: str,
        settings: Settings,
    ) -> tuple[str, str]:
        normalized_name = series_name.strip().lower()
        if normalized_name == "us10y":
            return (
                self._require_non_empty(settings.us10y_symbol, "us10y_symbol"),
                self._require_non_empty(settings.us10y_yahoo_period, "us10y_yahoo_period"),
            )
        if normalized_name == "vix":
            return (
                self._require_non_empty(settings.vix_yahoo_symbol, "vix_yahoo_symbol"),
                self._require_non_empty(settings.vix_yahoo_period, "vix_yahoo_period"),
            )
        if normalized_name == "spy":
            return (
                self._require_non_empty(settings.spy_yahoo_symbol, "spy_yahoo_symbol"),
                self._require_non_empty(settings.vix_yahoo_period, "vix_yahoo_period"),
            )
        if normalized_name.startswith("ticker:"):
            symbol = series_name.split(":", maxsplit=1)[1].strip().upper()
            if not symbol:
                raise ValueError("Ticker series requests must provide a non-empty symbol after 'ticker:'.")
            return (
                symbol,
                self._require_non_empty(settings.portfolio_yahoo_period, "portfolio_yahoo_period"),
            )
        raise ValueError(f"Unsupported Yahoo series requested: {normalized_name}")

    def _require_non_empty(
        self,
        raw_value: str,
        setting_name: str,
    ) -> str:
        value = raw_value.strip()
        if not value:
            raise ValueError(f"Yahoo setting '{setting_name}' cannot be empty.")
        return value

    def _normalize_close(
        self,
        series_name: str,
        close_value: float,
        settings: Settings,
    ) -> float:
        if series_name.strip().lower() == "us10y":
            # Align incoming ^TNX scale to threshold scale:
            # some payloads are 43.5 (=> 4.35%), others are already 4.35.
            if close_value >= settings.us10y_red_threshold * 2:
                return close_value / 10.0
            return close_value
        return close_value


class GlassnodeSeriesProvider:
    """Load daily metric series from Glassnode."""

    _SERIES_CONFIGS: dict[str, dict[str, str]] = {
        "btc_realized_pl_ratio": {
            "asset": "BTC",
            "interval": "24h",
            "path": "/v1/metrics/indicators/realized_profit_loss_ratio",
        }
    }

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        """Fetch and normalize the requested Glassnode metric series."""
        api_key = settings.glassnode_api_key.strip()
        if not api_key:
            raise ValueError(f"{series_name} requires a non-empty Glassnode API key.")

        series_config = self._resolve_config(series_name)
        response = httpx.get(
            self._resolve_url(settings, series_config["path"]),
            params={
                "a": series_config["asset"],
                "api_key": api_key,
                "i": series_config["interval"],
            },
            timeout=settings.glassnode_http_timeout_seconds,
        )
        response.raise_for_status()
        return self._parse_time_series(response.json(), series_name)

    def _resolve_config(
        self,
        series_name: str,
    ) -> dict[str, str]:
        normalized_name = series_name.strip().lower()
        config = self._SERIES_CONFIGS.get(normalized_name)
        if config is None:
            raise ValueError(f"Unsupported Glassnode series requested: {series_name}")
        return config

    def _resolve_url(
        self,
        settings: Settings,
        path: str,
    ) -> str:
        base_url = settings.glassnode_api_url.strip().rstrip("/")
        if not base_url:
            raise ValueError("Glassnode API URL cannot be empty.")
        return f"{base_url}{path}"

    def _parse_time_series(
        self,
        payload: object,
        series_name: str,
    ) -> list[DailyBar]:
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{series_name} Glassnode response is empty or not a list.")

        bars: list[DailyBar] = []
        for point in payload:
            if not isinstance(point, dict):
                raise ValueError(f"{series_name} Glassnode response contains a non-object datapoint.")

            raw_timestamp = point.get("t")
            raw_value = point.get("v")
            if raw_timestamp is None or raw_value is None:
                raise ValueError(f"{series_name} Glassnode datapoint must contain both 't' and 'v'.")

            timestamp = self._parse_timestamp(raw_timestamp, series_name)
            value = self._parse_value(raw_value, series_name)
            bars.append(
                DailyBar(
                    date=datetime.fromtimestamp(timestamp, tz=UTC).date(),
                    close=value,
                )
            )

        return sorted(bars, key=lambda bar,: bar.date)

    def _parse_timestamp(
        self,
        raw_timestamp: object,
        series_name: str,
    ) -> int:
        if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, float)):
            raise ValueError(f"{series_name} Glassnode datapoint has an invalid timestamp.")
        timestamp = int(raw_timestamp)
        if timestamp <= 0:
            raise ValueError(f"{series_name} Glassnode datapoint timestamp must be positive.")
        return timestamp

    def _parse_value(
        self,
        raw_value: object,
        series_name: str,
    ) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError(f"{series_name} Glassnode datapoint has an invalid numeric value.")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"{series_name} Glassnode datapoint value must be finite.")
        return value
