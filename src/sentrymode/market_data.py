"""
Shared daily market-data adapter seam.

[INPUT]: Series name + `Settings` with source URLs and timeout values.
[OUTPUT]: Normalized ascending `DailyBar` sequences for downstream factor calculations.
[POS]: Shared adapter module in `src/sentrymode`.
       Upstream: factor modules (currently `vix.py`, `us10y.py`, `btc_realized_pl_ratio_90d.py`).
       Downstream: external HTTP CSV providers, Yahoo Finance API, and Glassnode API.

[PROTOCOL]:
1. Keep provider seam (`DailySeriesProvider`) stable so factors can swap data backends.
2. Surface malformed payloads as explicit exceptions; do not silently coerce unknown schemas.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from io import StringIO
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


class HttpCsvSeriesProvider:
    """Load daily time series from HTTP CSV sources."""

    _DATE_CANDIDATES = ("date", "datetime", "timestamp")
    _CLOSE_CANDIDATES = ("close", "adj close", "adj_close", "adjusted close", "settle")

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        """Fetch and parse the requested series from its configured CSV source."""
        url = self._resolve_url(series_name, settings)
        response = httpx.get(url, timeout=settings.vix_http_timeout_seconds)
        response.raise_for_status()
        return self._parse_csv(response.text, series_name)

    def _resolve_url(
        self,
        series_name: str,
        settings: Settings,
    ) -> str:
        normalized_name = series_name.lower()
        if normalized_name == "vix":
            return settings.vix_cboe_csv_url
        if normalized_name == "spy":
            if not settings.spy_daily_csv_url:
                raise ValueError("VIX factor requires a valid SPY daily CSV source.")
            return settings.spy_daily_csv_url
        raise ValueError(f"Unsupported series requested: {series_name}")

    def _parse_csv(
        self,
        csv_text: str,
        series_name: str,
    ) -> list[DailyBar]:
        reader = csv.DictReader(StringIO(csv_text))
        if not reader.fieldnames:
            raise ValueError(f"{series_name} CSV response is missing a header row.")

        date_column = self._resolve_column(reader.fieldnames, self._DATE_CANDIDATES)
        close_column = self._resolve_column(reader.fieldnames, self._CLOSE_CANDIDATES)

        bars: list[DailyBar] = []
        for row in reader:
            raw_date = row.get(date_column, "").strip()
            raw_close = row.get(close_column, "").strip()
            if not raw_date or not raw_close:
                continue

            bars.append(
                DailyBar(
                    date=self._parse_date(raw_date),
                    close=float(raw_close.replace(",", "")),
                )
            )

        if not bars:
            raise ValueError(f"{series_name} CSV response does not contain valid daily rows.")

        return sorted(bars, key=lambda bar,: bar.date)

    def _resolve_column(
        self,
        fieldnames: list[str],
        candidates: tuple[str, ...],
    ) -> str:
        normalized_map = {fieldname.strip().lower(): fieldname for fieldname in fieldnames}
        for candidate in candidates:
            if candidate in normalized_map:
                return normalized_map[candidate]
        raise ValueError("CSV response is missing one of the expected columns: " + ", ".join(candidates))

    def _parse_date(
        self,
        raw_date: str,
    ) -> date:
        normalized_value = raw_date.strip()
        formats = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y")
        for fmt in formats:
            try:
                return datetime.strptime(normalized_value, fmt).date()
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(normalized_value).date()
        except ValueError as exc:
            raise ValueError(f"Unsupported date format: {raw_date}") from exc


class YahooSeriesProvider:
    """Load daily close series from Yahoo Finance via yfinance."""

    _SYMBOLS: dict[str, str] = {
        "us10y": "^TNX",
        "vix": "^VIX",
        "spy": "SPY",
    }

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        """Fetch and normalize the requested series from Yahoo Finance."""
        symbol = self._resolve_symbol(series_name, settings)
        history = yfinance.Ticker(symbol).history(period=settings.us10y_yahoo_period, interval="1d")
        if history.empty:
            raise ValueError(f"Yahoo Finance returned empty history for {series_name} ({symbol}).")
        if "Close" not in history.columns:
            raise ValueError(f"Yahoo Finance response for {series_name} ({symbol}) is missing Close column.")

        bars: list[DailyBar] = []
        for index, close in history["Close"].items():
            if close is None:
                continue
            close_value = float(close)
            if close_value <= 0:
                continue
            bar_date = index.date()
            bars.append(
                DailyBar(
                    date=bar_date,
                    close=self._normalize_close(series_name, close_value, settings),
                )
            )

        if not bars:
            raise ValueError(f"Yahoo Finance history for {series_name} ({symbol}) has no valid close rows.")
        return sorted(bars, key=lambda bar,: bar.date)

    def _resolve_symbol(
        self,
        series_name: str,
        settings: Settings,
    ) -> str:
        normalized_name = series_name.strip().lower()
        if normalized_name == "us10y":
            return settings.us10y_symbol
        symbol = self._SYMBOLS.get(normalized_name)
        if symbol is None:
            raise ValueError(f"Unsupported Yahoo series requested: {series_name}")
        return symbol

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
