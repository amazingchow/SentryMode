"""Application settings for monitoring runtime."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized runtime configuration for the monitoring app."""

    model_config = SettingsConfigDict(
        env_prefix="SENTRYMODE_",
        env_file=".env",
        extra="ignore",
    )

    bark_server: str = Field(
        ...,
        description="Bark API base URL; must be non-empty after trim.",
    )
    bark_device_key: str = Field(
        ...,
        description="Bark device key; must be non-empty after trim.",
    )
    poll_interval_seconds: int = 60
    enabled_factors: list[str] = Field(default_factory=lambda: ["ahr999"])
    report_format: Literal["plain", "markdown"] = Field(
        default="markdown",
        description="Notification body format: plain or markdown only.",
    )
    report_language: Literal["en", "zh"] = Field(
        default="en",
        description="Report copy language: en or zh only.",
    )

    @field_validator("bark_server", "bark_device_key", mode="before")
    @classmethod
    def _non_empty_bark_strings(
        cls,
        value: object,
    ) -> str:
        if value is None:
            msg = "bark_server and bark_device_key cannot be empty"
            raise ValueError(msg)
        if not isinstance(value, str):
            msg = "bark_server and bark_device_key must be strings"
            raise TypeError(msg)
        stripped = value.strip()
        if not stripped:
            msg = "bark_server and bark_device_key cannot be empty"
            raise ValueError(msg)
        return stripped

    @field_validator("report_format", mode="before")
    @classmethod
    def _normalize_report_format(
        cls,
        value: object,
    ) -> str:
        if not isinstance(value, str):
            msg = "report_format must be a string: 'plain' or 'markdown'"
            raise TypeError(msg)
        key = value.strip().lower()
        if key not in ("plain", "markdown"):
            msg = "report_format must be 'plain' or 'markdown'"
            raise ValueError(msg)
        return key

    @field_validator("report_language", mode="before")
    @classmethod
    def _normalize_report_language(
        cls,
        value: object,
    ) -> str:
        if not isinstance(value, str):
            msg = "report_language must be a string: 'en' or 'zh'"
            raise TypeError(msg)
        key = value.strip().lower()
        if key not in ("en", "zh"):
            msg = "report_language must be 'en' or 'zh'"
            raise ValueError(msg)
        return key

    ahr_run_hour: int = 9
    ahr_run_minute: int = 20
    ahr_run_timezone: str = "America/New_York"
    ahr_genesis_date: date = date(2009, 1, 3)
    ahr_fit_a: float = 5.8
    ahr_fit_b: float = 16.88
    ahr_lookback_days: int = 200
    ahr_kraken_pair: str = "XBTUSD"
    ahr_kraken_interval_minutes: int = 1440
    ahr_kraken_api_url: str = "https://api.kraken.com/0/public/OHLC"
    ahr_http_timeout_seconds: float = 10.0

    vix_run_hour: int = 16
    vix_run_minute: int = 5
    vix_run_timezone: str = "America/New_York"
    vix_lookback_days: int = 60
    vix_sma_window: int = 10
    vix_roc_window: int = 10
    vix_yellow_min: float = 15.0
    vix_green_max: float = 18.0
    vix_red_min: float = 20.0
    vix_blue_spike_min: float = 30.0
    vix_roc_yellow_threshold: float = 0.15
    vix_roc_red_threshold: float = 0.30
    vix_two_day_confirmation: int = 2
    spy_sma_window: int = 20
    vix_cboe_csv_url: str = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    spy_daily_csv_url: str = "https://stooq.com/q/d/l/?s=spy.us&i=d"
    vix_http_timeout_seconds: float = 10.0
