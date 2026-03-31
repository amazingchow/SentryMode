from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import sentrymode.factors.vix as vix_module
from sentrymode.factors.vix import VIXFactor
from sentrymode.market_data import DailyBar, YahooSeriesProvider
from sentrymode.monitoring import MonitorContext, Settings, Severity


class _FakeSeriesProvider:
    def __init__(
        self,
        *,
        vix_closes: list[float],
        spy_closes: list[float],
        start: date = date(2025, 1, 1),
    ) -> None:
        self._series = {
            "vix": self._build_bars(vix_closes, start),
            "spy": self._build_bars(spy_closes, start),
        }

    def _build_bars(
        self,
        closes: list[float],
        start: date,
    ) -> list[DailyBar]:
        return [DailyBar(date=start + timedelta(days=index), close=close) for index, close in enumerate(closes)]

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        return self._series[series_name]


def _build_settings(
    **overrides,
) -> Settings:
    payload = {
        "_env_file": None,
        "bark_server": "https://example.com",
        "bark_device_key": "device-key",
        "vix_run_timezone": "UTC",
        "vix_run_hour": 16,
        "vix_run_minute": 5,
        "vix_lookback_days": 6,
        "vix_sma_window": 3,
        "vix_roc_window": 2,
        "vix_two_day_confirmation": 2,
        "spy_sma_window": 3,
    }
    payload.update(overrides)
    return Settings(**payload)


def _build_context(
    settings: Settings,
    *,
    now: datetime,
    force_run: bool = False,
    last_evaluated_at: dict[str, datetime] | None = None,
) -> MonitorContext:
    return MonitorContext(
        now=now,
        settings=settings,
        last_evaluated_at=last_evaluated_at or {},
        force_run=force_run,
    )


def test_vix_factor_uses_yahoo_provider_by_default() -> None:
    factor = VIXFactor()
    assert isinstance(factor.provider, YahooSeriesProvider)


def test_vix_should_evaluate_respects_schedule_and_force() -> None:
    factor = VIXFactor()
    settings = _build_settings()

    should_run = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 5, tzinfo=UTC),
        )
    )
    should_skip_wrong_minute = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 4, tzinfo=UTC),
        )
    )
    should_skip_same_day = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 5, tzinfo=UTC),
            last_evaluated_at={factor.name: datetime(2025, 2, 1, 1, 0, tzinfo=UTC)},
        )
    )
    force_run = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 0, 0, tzinfo=UTC),
            force_run=True,
        )
    )

    assert should_run is True
    assert should_skip_wrong_minute is False
    assert should_skip_same_day is False
    assert force_run is True


def test_vix_align_series_raises_when_no_common_dates() -> None:
    factor = VIXFactor()

    with pytest.raises(ValueError, match="do not share any common trading dates"):
        factor._align_series(
            [DailyBar(date=date(2025, 1, 1), close=1.0)],
            [DailyBar(date=date(2025, 1, 2), close=2.0)],
        )


def test_vix_calculate_signals_requires_enough_history() -> None:
    factor = VIXFactor()
    settings = _build_settings(vix_lookback_days=6, vix_sma_window=4, vix_roc_window=3, spy_sma_window=5)
    bars = [DailyBar(date=date(2025, 1, 1), close=10.0)] * 3

    with pytest.raises(ValueError, match="requires at least"):
        factor._calculate_signals(bars, bars, settings)


def test_vix_classify_regime_all_paths() -> None:
    factor = VIXFactor()
    settings = _build_settings(vix_red_min=20.0, vix_yellow_min=15.0, vix_green_max=18.0)

    blue = factor._classify_regime(
        {
            "vix_close": 19.0,
            "vix_sma10": 20.0,
            "vix_prev_close": 21.0,
            "vix_prev_sma10": 20.0,
            "vix_roc10": -0.1,
            "spy_below_sma20": False,
            "two_day_above_sma10": False,
            "recent_vix_spike": True,
        },
        settings,
    )
    red = factor._classify_regime(
        {
            "vix_close": 25.0,
            "vix_sma10": 20.0,
            "vix_prev_close": 24.0,
            "vix_prev_sma10": 19.0,
            "vix_roc10": 0.5,
            "spy_below_sma20": True,
            "two_day_above_sma10": True,
            "recent_vix_spike": False,
        },
        settings,
    )
    yellow = factor._classify_regime(
        {
            "vix_close": 18.0,
            "vix_sma10": 17.0,
            "vix_prev_close": 17.5,
            "vix_prev_sma10": 16.5,
            "vix_roc10": 0.2,
            "spy_below_sma20": True,
            "two_day_above_sma10": False,
            "recent_vix_spike": False,
        },
        settings,
    )
    green = factor._classify_regime(
        {
            "vix_close": 14.0,
            "vix_sma10": 15.0,
            "vix_prev_close": 14.5,
            "vix_prev_sma10": 15.5,
            "vix_roc10": -0.1,
            "spy_below_sma20": False,
            "two_day_above_sma10": False,
            "recent_vix_spike": False,
        },
        settings,
    )
    neutral = factor._classify_regime(
        {
            "vix_close": 19.0,
            "vix_sma10": 18.0,
            "vix_prev_close": 18.0,
            "vix_prev_sma10": 18.0,
            "vix_roc10": 0.0,
            "spy_below_sma20": False,
            "two_day_above_sma10": False,
            "recent_vix_spike": False,
        },
        settings,
    )

    assert blue == "blue"
    assert red == "red"
    assert yellow == "yellow"
    assert green == "green"
    assert neutral == "neutral"


def test_vix_severity_for_regime() -> None:
    factor = VIXFactor()

    assert factor._severity_for_regime("yellow") == Severity.WARNING
    assert factor._severity_for_regime("red") == Severity.CRITICAL
    assert factor._severity_for_regime("blue") == Severity.INFO


def test_vix_math_helpers() -> None:
    factor = VIXFactor()

    assert factor._simple_moving_average([1.0, 2.0, 3.0], 2) == 2.5
    assert factor._rate_of_change([10.0, 12.0, 15.0], 2) == 0.5
    assert factor._closed_above_sma_for_days([10.0, 11.0, 12.0, 13.0], 2, 2) is True
    assert factor._closed_above_sma_for_days([10.0], 2, 2) is False

    with pytest.raises(ValueError, match="Need at least 3 closes"):
        factor._simple_moving_average([1.0, 2.0], 3)
    with pytest.raises(ValueError, match="Need more than 3 closes"):
        factor._rate_of_change([1.0, 2.0, 3.0], 3)
    with pytest.raises(ValueError, match="base value must be positive"):
        factor._rate_of_change([0.0, 1.0, 2.0], 2)


def test_vix_build_message_and_guidance_localization() -> None:
    factor = VIXFactor()
    settings = _build_settings(report_language="zh")

    title, summary, details = factor._build_message(
        "blue",
        {
            "vix_close": 19.0,
            "vix_sma10": 20.0,
            "vix_roc10": -0.1,
            "spy_close": 500.0,
            "spy_sma20": 510.0,
            "spy_below_sma20": True,
            "two_day_above_sma10": False,
            "recent_vix_spike": True,
        },
        settings,
    )

    assert "VIX" in title
    assert "建议仓位" in summary
    assert "黑" not in details


def test_vix_evaluate_integration_with_fake_provider() -> None:
    factor = VIXFactor(
        provider=_FakeSeriesProvider(
            vix_closes=[14.0, 15.0, 16.0, 17.0, 18.0, 25.0],
            spy_closes=[500.0, 498.0, 495.0, 492.0, 490.0, 480.0],
        )
    )
    settings = _build_settings(vix_red_min=20.0, vix_roc_red_threshold=0.2)

    result = factor.evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 5, tzinfo=UTC),
            force_run=True,
        )
    )

    assert result.factor_name == "vix"
    assert result.metrics["regime"] in {"red", "yellow", "green", "blue", "neutral"}


def test_vix_build_runner_helpers(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    class _FakeSettings:
        bark_server = "https://bark.example.com"
        bark_device_key = "device-key"
        report_format = "markdown"
        vix_http_timeout_seconds = 4.0

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

    monkeypatch.setattr(vix_module, "Settings", _FakeSettings)
    monkeypatch.setattr(vix_module, "ConsoleBarkNotifier", _FakeNotifier)
    monkeypatch.setattr(vix_module, "MonitorRunner", _FakeRunner)

    runner = vix_module.build_vix_runner()

    assert isinstance(runner, _FakeRunner)
    assert observed["enabled_factors"] == ["vix"]
    assert observed["notifier"] == ("https://bark.example.com", "device-key", "markdown", 4.0)


def test_vix_run_helpers_dispatch(
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str], bool | None]] = []

    class _FakeRunner:
        def run_once(
            self,
            *,
            factor_names: list[str],
            force: bool,
        ) -> None:
            calls.append(("run_once", factor_names, force))

        def run_forever(
            self,
            *,
            factor_names: list[str],
        ) -> None:
            calls.append(("run_forever", factor_names, None))

    monkeypatch.setattr(vix_module, "build_vix_runner", lambda: _FakeRunner())

    vix_module.run_once()
    vix_module.run_monitor()

    assert calls == [
        ("run_once", ["vix"], True),
        ("run_forever", ["vix"], None),
    ]
