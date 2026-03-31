from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import sentrymode.factors.btc_realized_pl_ratio_90d as factor_module
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


def test_btc_realized_pl_ratio_simple_moving_average_requires_window() -> None:
    factor = BTCRealizedPLRatio90DFactor()

    with pytest.raises(ValueError, match="Need at least 5 daily values"):
        factor._simple_moving_average([1.0, 2.0, 3.0], 5)


def test_btc_realized_pl_ratio_signal_labels_and_guidance_localized() -> None:
    factor = BTCRealizedPLRatio90DFactor()
    settings = _build_settings()
    zh_settings = Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        report_language="zh",
    )

    assert factor._regime_label("profit_dominant", settings) == "profit_dominant"
    assert factor._signal_label("still_above_1", settings) == "still_above_1"
    assert "confirmation" in factor._guidance_for_regime("profit_dominant", settings)
    assert "盈利主导" in factor._regime_label("profit_dominant", zh_settings)


def test_btc_realized_pl_ratio_build_runner_and_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _FakeSettings:
        bark_server = "https://bark.example.com"
        bark_device_key = "device-key"
        report_format = "markdown"
        glassnode_http_timeout_seconds = 6.0

        def __init__(
            self,
            *,
            enabled_factors: list[str],
        ) -> None:
            observed["enabled_factors"] = enabled_factors

    class _FakeNotifier:
        def __init__(
            self,
            bark_server: str,
            bark_device_key: str,
            report_format: str,
            timeout_seconds: float,
        ) -> None:
            observed["notifier"] = (bark_server, bark_device_key, report_format, timeout_seconds)

    class _FakeRunner:
        def __init__(
            self,
            *,
            factors,
            settings,
            notifier,
        ) -> None:
            observed["runner"] = (factors, settings, notifier)

        def run_once(
            self,
            *,
            factor_names: list[str],
            force: bool,
        ) -> None:
            observed["run_once"] = (factor_names, force)

        def run_forever(
            self,
            *,
            factor_names: list[str],
        ) -> None:
            observed["run_forever"] = factor_names

    monkeypatch.setattr(factor_module, "Settings", _FakeSettings)
    monkeypatch.setattr(factor_module, "ConsoleBarkNotifier", _FakeNotifier)
    monkeypatch.setattr(factor_module, "MonitorRunner", _FakeRunner)

    runner = factor_module.build_btc_realized_pl_ratio_90d_runner()
    assert isinstance(runner, _FakeRunner)
    assert observed["enabled_factors"] == ["btc_realized_pl_ratio_90d"]
    assert observed["notifier"] == ("https://bark.example.com", "device-key", "markdown", 6.0)

    monkeypatch.setattr(factor_module, "build_btc_realized_pl_ratio_90d_runner", lambda: runner)
    factor_module.run_once()
    factor_module.run_monitor()
    assert observed["run_once"] == (["btc_realized_pl_ratio_90d"], True)
    assert observed["run_forever"] == ["btc_realized_pl_ratio_90d"]
