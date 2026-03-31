from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import sentrymode.factors.us10y as us10y_module
from sentrymode.factors.us10y import US10YFactor
from sentrymode.market_data import DailyBar
from sentrymode.monitoring import MonitorContext, Settings, Severity


class FakeSeriesProvider:
    def __init__(
        self,
        *,
        us10y_closes: list[float],
        vix_closes: list[float],
        spy_closes: list[float],
        start: date = date(2025, 1, 1),
    ) -> None:
        self._series = {
            "us10y": self._build_bars(us10y_closes, start),
            "vix": self._build_bars(vix_closes, start),
            "spy": self._build_bars(spy_closes, start),
        }

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        return self._series[series_name]

    def _build_bars(
        self,
        closes: list[float],
        start: date,
    ) -> list[DailyBar]:
        return [
            DailyBar(
                date=start + timedelta(days=index),
                close=close,
            )
            for index, close in enumerate(closes)
        ]


def _build_settings(
    *,
    state_file: Path,
    lookback_days: int = 15,
    sma_window: int = 5,
    roc_window: int = 3,
) -> Settings:
    return Settings(
        us10y_state_file=str(state_file),
        us10y_lookback_days=lookback_days,
        us10y_sma_window=sma_window,
        us10y_roc_window=roc_window,
        us10y_spy_sma_window=5,
    )


def _write_state_file(
    path: Path,
    state: str,
) -> None:
    payload = {
        "state": state,
        "as_of_date": "2025-01-31",
        "streak_above_green": 0,
        "streak_above_red": 0,
        "streak_below_red_and_sma": 0,
        "streak_below_green_and_neg_roc": 0,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _build_context(
    settings: Settings,
) -> MonitorContext:
    return MonitorContext(
        now=datetime(2025, 2, 1, 20, 0, tzinfo=UTC),
        settings=settings,
        last_evaluated_at={},
        force_run=True,
    )


def test_us10y_transition_green_to_yellow_and_persists_state(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    _write_state_file(state_file, "green")

    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[3.8] * 13 + [4.05, 4.1],
            vix_closes=[16.0] * 15,
            spy_closes=[500.0] * 15,
        )
    )
    settings = _build_settings(state_file=state_file)

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "yellow"
    assert result.severity == Severity.WARNING

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["state"] == "yellow"
    assert persisted["streak_above_green"] >= 2


def test_us10y_transition_yellow_to_red_triggers_black_swan(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    _write_state_file(state_file, "yellow")

    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[4.2] * 11 + [4.35, 4.55, 4.7, 4.85],
            vix_closes=[18.0] * 14 + [24.0],
            spy_closes=[520.0] * 10 + [500.0, 495.0, 490.0, 485.0, 470.0],
        )
    )
    settings = _build_settings(state_file=state_file)

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "red"
    assert result.metrics["black_swan"] == "true"
    assert result.severity == Severity.CRITICAL
    assert "0%" in result.summary


def test_us10y_transition_red_to_yellow(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    _write_state_file(state_file, "red")

    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[4.7] * 9 + [4.85, 4.8, 4.75, 4.2, 4.1, 4.0],
            vix_closes=[18.0] * 15,
            spy_closes=[500.0] * 15,
        )
    )
    settings = _build_settings(state_file=state_file)

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "yellow"
    assert result.severity == Severity.WARNING


def test_us10y_transition_yellow_to_green_requires_negative_roc(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    _write_state_file(state_file, "yellow")

    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[4.2] * 8 + [4.1, 4.05, 4.0, 3.95, 3.8, 3.7, 3.6],
            vix_closes=[15.0] * 15,
            spy_closes=[520.0] * 15,
        )
    )
    settings = _build_settings(state_file=state_file)

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "green"
    assert result.severity == Severity.INFO


def test_us10y_recovers_from_corrupted_state_file(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{ invalid json", encoding="utf-8")

    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[3.8] * 15,
            vix_closes=[14.0] * 15,
            spy_closes=[520.0] * 15,
        )
    )
    settings = _build_settings(state_file=state_file)

    result = factor.evaluate(_build_context(settings))

    assert result.metrics["regime"] == "green"
    assert "State recovery note" in result.details or "状态恢复提示" in result.details

    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted["state"] == "green"


def test_us10y_should_evaluate_respects_schedule_and_force(
    tmp_path: Path,
) -> None:
    settings = _build_settings(
        state_file=tmp_path / "state.json",
        lookback_days=15,
        sma_window=5,
        roc_window=3,
    )
    factor = US10YFactor()

    should_run = factor.should_evaluate(
        MonitorContext(
            now=datetime(2025, 2, 1, 21, 10, tzinfo=UTC),
            settings=settings,
            last_evaluated_at={},
            force_run=False,
        )
    )
    should_skip_wrong_minute = factor.should_evaluate(
        MonitorContext(
            now=datetime(2025, 2, 1, 21, 9, tzinfo=UTC),
            settings=settings,
            last_evaluated_at={},
            force_run=False,
        )
    )
    should_skip_same_day = factor.should_evaluate(
        MonitorContext(
            now=datetime(2025, 2, 1, 21, 10, tzinfo=UTC),
            settings=settings,
            last_evaluated_at={factor.name: datetime(2025, 2, 1, 22, 0, tzinfo=UTC)},
            force_run=False,
        )
    )
    force_run = factor.should_evaluate(
        MonitorContext(
            now=datetime(2025, 2, 1, 0, 0, tzinfo=UTC),
            settings=settings,
            last_evaluated_at={},
            force_run=True,
        )
    )

    assert should_run is True
    assert should_skip_wrong_minute is False
    assert should_skip_same_day is False
    assert force_run is True


def test_us10y_calculate_signals_input_validation(
    tmp_path: Path,
) -> None:
    factor = US10YFactor()
    settings = _build_settings(state_file=tmp_path / "state.json", lookback_days=5, sma_window=3, roc_window=2)
    bars = [DailyBar(date=date(2025, 1, 1), close=1.0)] * 2
    enough_us10y = [DailyBar(date=date(2025, 1, 1), close=4.0)] * 5
    enough_spy = [DailyBar(date=date(2025, 1, 1), close=500.0)] * 5

    with pytest.raises(ValueError, match="requires at least .* daily points"):
        factor._calculate_signals(bars, enough_us10y, enough_spy, settings)
    with pytest.raises(ValueError, match="requires at least one VIX daily point"):
        factor._calculate_signals(enough_us10y, [], enough_spy, settings)
    with pytest.raises(ValueError, match="requires at least .* SPY daily points"):
        factor._calculate_signals(enough_us10y, enough_us10y, bars, settings)


def test_us10y_helper_error_branches(
    tmp_path: Path,
) -> None:
    factor = US10YFactor()
    settings = _build_settings(state_file=tmp_path / "state.json", lookback_days=5, sma_window=3, roc_window=2)

    assert factor._base_regime(settings.us10y_red_threshold, settings) == "red"
    assert factor._base_regime(settings.us10y_green_threshold, settings) == "yellow"
    assert factor._severity_for("red", black_swan=False) == Severity.CRITICAL

    with pytest.raises(ValueError, match="Need at least 4 closes"):
        factor._simple_moving_average([1.0, 2.0, 3.0], 4)
    with pytest.raises(ValueError, match="Need more than 3 closes"):
        factor._rate_of_change([1.0, 2.0, 3.0], 3)
    with pytest.raises(ValueError, match="ROC base value must be positive"):
        factor._rate_of_change([0.0, 1.0, 2.0], 2)


def test_us10y_load_state_missing_and_invalid_state_value(
    tmp_path: Path,
) -> None:
    factor = US10YFactor()
    missing_settings = _build_settings(state_file=tmp_path / "missing.json")

    snapshot, note = factor._load_state(missing_settings)
    assert snapshot is None
    assert note is None

    invalid_state_file = tmp_path / "invalid.json"
    invalid_state_file.write_text(
        json.dumps(
            {
                "state": "unknown",
                "as_of_date": "2025-01-31",
                "streak_above_green": 0,
                "streak_above_red": 0,
                "streak_below_red_and_sma": 0,
                "streak_below_green_and_neg_roc": 0,
            }
        ),
        encoding="utf-8",
    )
    invalid_settings = _build_settings(state_file=invalid_state_file)

    snapshot2, note2 = factor._load_state(invalid_settings)
    assert snapshot2 is None
    assert note2 is not None
    assert "invalid state file" in note2


def test_us10y_persist_state_oserror_returns_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factor = US10YFactor()
    state_file = tmp_path / "cannot-write" / "state.json"
    settings = _build_settings(state_file=state_file)

    def raise_oserror(
        *args,
        **kwargs,
    ) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", raise_oserror)

    warning = factor._persist_state(
        settings=settings,
        snapshot=us10y_module._StateSnapshot(
            state="green",
            as_of_date=date(2025, 2, 1),
            streak_above_green=1,
            streak_above_red=0,
            streak_below_red_and_sma=0,
            streak_below_green_and_neg_roc=0,
        ),
    )

    assert warning is not None
    assert "cannot write state file" in warning


def test_us10y_build_message_includes_persist_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "us10y_state.json"
    _write_state_file(state_file, "green")
    factor = US10YFactor(
        provider=FakeSeriesProvider(
            us10y_closes=[3.8] * 13 + [4.05, 4.1],
            vix_closes=[16.0] * 15,
            spy_closes=[500.0] * 15,
        )
    )
    settings = _build_settings(state_file=state_file)

    monkeypatch.setattr(US10YFactor, "_persist_state", lambda self, **kwargs,: "write failed")
    result = factor.evaluate(_build_context(settings))

    assert "State persistence warning" in result.details or "状态持久化警告" in result.details


def test_us10y_runner_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _FakeSettings:
        bark_server = "https://bark.example.com"
        bark_device_key = "device-key"
        report_format = "plain"
        vix_http_timeout_seconds = 8.0

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

    monkeypatch.setattr(us10y_module, "Settings", _FakeSettings)
    monkeypatch.setattr(us10y_module, "ConsoleBarkNotifier", _FakeNotifier)
    monkeypatch.setattr(us10y_module, "MonitorRunner", _FakeRunner)

    runner = us10y_module.build_us10y_runner()
    assert isinstance(runner, _FakeRunner)
    assert observed["enabled_factors"] == ["us10y"]
    assert observed["notifier"] == ("https://bark.example.com", "device-key", "plain", 8.0)

    monkeypatch.setattr(us10y_module, "build_us10y_runner", lambda: runner)
    us10y_module.run_once()
    us10y_module.run_monitor()
    assert observed["run_once"] == (["us10y"], True)
    assert observed["run_forever"] == ["us10y"]


def test_us10y_localized_display_name(
    tmp_path: Path,
) -> None:
    factor = US10YFactor()
    settings = _build_settings(state_file=tmp_path / "state.json", lookback_days=5, sma_window=3, roc_window=2)
    assert factor.localized_display_name(settings) == factor._display_name(settings)
