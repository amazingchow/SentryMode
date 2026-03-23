"""Shared market data access primitives."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from typing import Protocol

import httpx

from sentrymode.monitoring.settings import Settings


@dataclass(slots=True, frozen=True)
class DailyBar:
    """Normalized daily OHLC subset used by factors."""

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
