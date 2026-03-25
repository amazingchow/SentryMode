from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from sentrymode.factors.btc_realized_pl_ratio_90d import BTCRealizedPLRatio90DFactor
from sentrymode.market_data import DailyBar
from sentrymode.monitoring import MonitorContext, Settings, Severity


class FakeSeriesProvider:
    def __init__(
        self,
        *,
        ratio_values: list[float],
        start: date = date(2025, 1, 1),
    ) -> None:
        self._series = [
            DailyBar(
                date=start + timedelta(days=index),
                close=value,
            )
            for index, value in enumerate(ratio_values)
        ]

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        assert series_name == "btc_realized_pl_ratio"
        return self._series


def _build_settings(
    *,
    lookback_days: int = 5,
    sma_window: int = 3,
    threshold: float = 1.0,
) -> Settings:
    return Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        btc_realized_pl_ratio_90d_lookback_days=lookback_days,
        btc_realized_pl_ratio_90d_sma_window=sma_window,
        btc_realized_pl_ratio_90d_threshold=threshold,
    )


def _build_context(
    settings: Settings,
    *,
    now: datetime = datetime(2025, 2, 1, 14, 25, tzinfo=UTC),
    force_run: bool = True,
    last_evaluated_at: dict[str, datetime] | None = None,
) -> MonitorContext:
    return MonitorContext(
        now=now,
        settings=settings,
        last_evaluated_at=last_evaluated_at or {},
        force_run=force_run,
    )


def test_btc_realized_pl_ratio_crossed_below_threshold() -> None:
    factor = BTCRealizedPLRatio90DFactor(
        provider=FakeSeriesProvider(ratio_values=[1.2, 1.2, 1.2, 1.2, 0.2]),
    )
    settings = _build_settings()

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "loss_dominant"
    assert result.metrics["signal"] == "crossed_below_1"
    assert result.severity == Severity.WARNING


def test_btc_realized_pl_ratio_reclaimed_above_threshold() -> None:
    factor = BTCRealizedPLRatio90DFactor(
        provider=FakeSeriesProvider(ratio_values=[0.8, 0.8, 0.8, 0.8, 1.8]),
    )
    settings = _build_settings()

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "profit_dominant"
    assert result.metrics["signal"] == "reclaimed_above_1"
    assert result.severity == Severity.INFO


def test_btc_realized_pl_ratio_still_below_threshold() -> None:
    factor = BTCRealizedPLRatio90DFactor(
        provider=FakeSeriesProvider(ratio_values=[0.6, 0.7, 0.8, 0.9, 0.95]),
    )
    settings = _build_settings()

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "loss_dominant"
    assert result.metrics["signal"] == "still_below_1"


def test_btc_realized_pl_ratio_still_above_threshold() -> None:
    factor = BTCRealizedPLRatio90DFactor(
        provider=FakeSeriesProvider(ratio_values=[1.2, 1.1, 1.3, 1.2, 1.4]),
    )
    settings = _build_settings()

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "profit_dominant"
    assert result.metrics["signal"] == "still_above_1"


def test_btc_realized_pl_ratio_requires_enough_history() -> None:
    factor = BTCRealizedPLRatio90DFactor(
        provider=FakeSeriesProvider(ratio_values=[1.1, 1.0, 0.9]),
    )
    settings = _build_settings(lookback_days=5, sma_window=3)

    with pytest.raises(ValueError, match="requires at least 5 daily points"):
        factor.evaluate(_build_context(settings))


def test_btc_realized_pl_ratio_should_evaluate_once_per_configured_day() -> None:
    factor = BTCRealizedPLRatio90DFactor()
    settings = _build_settings()

    should_run = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 14, 25, tzinfo=UTC),
            force_run=False,
        )
    )
    should_skip_wrong_minute = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 14, 24, tzinfo=UTC),
            force_run=False,
        )
    )
    should_skip_same_day = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 14, 25, tzinfo=UTC),
            force_run=False,
            last_evaluated_at={
                factor.name: datetime(2025, 2, 1, 14, 25, tzinfo=UTC),
            },
        )
    )

    assert should_run is True
    assert should_skip_wrong_minute is False
    assert should_skip_same_day is False
