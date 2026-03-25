from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
