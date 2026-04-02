from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sentrymode.factors.ai_portfolio import AIPortfolioFactor, _TickerSnapshot
from sentrymode.market_data import DailyBar, YahooSeriesProvider
from sentrymode.monitoring import MonitorContext, Settings, Severity


class _FakeSeriesProvider:
    def __init__(
        self,
        series: dict[str, list[DailyBar]],
    ) -> None:
        self._series = series

    def get_series(
        self,
        series_name: str,
        settings: Settings,
    ) -> list[DailyBar]:
        return self._series[series_name]


class _FakeEarningsProvider:
    def __init__(
        self,
        dates: dict[str, date | None] | None = None,
    ) -> None:
        self._dates = dates or {}

    def get_next_earnings_date(
        self,
        symbol: str,
        *,
        as_of: date,
    ) -> date | None:
        return self._dates.get(symbol)


def _build_settings(
    **overrides,
) -> Settings:
    payload = {
        "_env_file": None,
        "bark_server": "https://example.com",
        "bark_device_key": "device-key",
        "report_language": "zh",
        "portfolio_run_timezone": "UTC",
        "portfolio_run_hour": 16,
        "portfolio_run_minute": 15,
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


def _build_bars(
    closes: list[float],
    *,
    start: date = date(2025, 1, 1),
) -> list[DailyBar]:
    return [DailyBar(date=start + timedelta(days=index), close=close) for index, close in enumerate(closes)]


def _uptrend(
    *,
    length: int = 220,
    start: float = 100.0,
    step: float = 1.0,
) -> list[float]:
    return [start + step * index for index in range(length)]


def test_ai_portfolio_uses_yahoo_provider_by_default() -> None:
    factor = AIPortfolioFactor()
    assert isinstance(factor.provider, YahooSeriesProvider)


def test_ai_portfolio_should_evaluate_respects_schedule_and_force() -> None:
    factor = AIPortfolioFactor()
    settings = _build_settings()

    should_run = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 15, tzinfo=UTC),
        )
    )
    should_skip_wrong_minute = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 14, tzinfo=UTC),
        )
    )
    should_skip_same_day = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 16, 15, tzinfo=UTC),
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


def test_ai_portfolio_classifies_market_regimes() -> None:
    factor = AIPortfolioFactor()
    settings = _build_settings()
    strong = _TickerSnapshot(
        symbol="QQQ",
        close=120.0,
        sma20=110.0,
        sma50=100.0,
        sma200=90.0,
        prev_close=119.0,
        prev_sma20=109.5,
        prev_sma50=99.5,
        high10=120.0,
        latest_date=date(2025, 8, 1),
    )
    weak50 = _TickerSnapshot(
        symbol="QQQ",
        close=95.0,
        sma20=100.0,
        sma50=101.0,
        sma200=90.0,
        prev_close=96.0,
        prev_sma20=100.5,
        prev_sma50=101.5,
        high10=105.0,
        latest_date=date(2025, 8, 1),
    )
    weak200 = _TickerSnapshot(
        symbol="QQQ",
        close=85.0,
        sma20=90.0,
        sma50=95.0,
        sma200=100.0,
        prev_close=86.0,
        prev_sma20=91.0,
        prev_sma50=96.0,
        high10=95.0,
        latest_date=date(2025, 8, 1),
    )

    assert factor._classify_market_regime(vix_close=16.0, qqq=strong, smh=strong, settings=settings) == "green"
    assert factor._classify_market_regime(vix_close=20.0, qqq=strong, smh=strong, settings=settings) == "yellow"
    assert factor._classify_market_regime(vix_close=24.5, qqq=strong, smh=strong, settings=settings) == "orange"
    assert factor._classify_market_regime(vix_close=31.0, qqq=strong, smh=strong, settings=settings) == "red"
    assert factor._classify_market_regime(vix_close=16.0, qqq=weak200, smh=strong, settings=settings) == "extreme"
    assert factor._classify_market_regime(vix_close=16.0, qqq=weak50, smh=strong, settings=settings) == "orange"


def test_ai_portfolio_orange_regime_only_opens_small_goog() -> None:
    factor = AIPortfolioFactor(
        provider=_FakeSeriesProvider(
            {
                "vix": _build_bars([20.0] * 219 + [24.35]),
                "ticker:QQQ": _build_bars(_uptrend(start=300.0, step=1.0)),
                "ticker:SMH": _build_bars(_uptrend(start=200.0, step=1.0)),
                "ticker:GOOG": _build_bars(_uptrend(start=150.0, step=0.8)),
                "ticker:NVDA": _build_bars(_uptrend(start=100.0, step=1.5)),
                "ticker:MU": _build_bars(_uptrend(start=90.0, step=0.7)),
                "ticker:ASML": _build_bars(_uptrend(start=600.0, step=1.0)),
                "ticker:ORCL": _build_bars([100.0] * 218 + [99.0, 101.0]),
                "ticker:NLR": _build_bars(_uptrend(start=70.0, step=0.25)),
            }
        ),
        earnings_provider=_FakeEarningsProvider(),
    )
    settings = _build_settings()

    result = factor.evaluate(
        _build_context(
            settings,
            now=datetime(2025, 8, 10, 16, 15, tzinfo=UTC),
            force_run=True,
        )
    )

    assert result.severity == Severity.WARNING
    assert result.metrics["regime"] == "orange"
    assert "GOOG (20%): 建仓" in result.details
    assert "NVDA (18%): 暂停" in result.details
    assert "MU (15%): 暂停" in result.details
    assert "ASML (12%): 暂停" in result.details
    assert "ORCL (10%): 暂停" in result.details
    assert "NLR (10%): 暂停" in result.details


def test_ai_portfolio_green_regime_adds_profitable_holds_and_respects_earnings_guard() -> None:
    factor = AIPortfolioFactor(
        provider=_FakeSeriesProvider(
            {
                "vix": _build_bars([16.0] * 220),
                "ticker:QQQ": _build_bars(_uptrend(start=300.0, step=1.0)),
                "ticker:SMH": _build_bars(_uptrend(start=200.0, step=1.0)),
                "ticker:GOOG": _build_bars(_uptrend(start=150.0, step=0.8)),
                "ticker:NVDA": _build_bars(_uptrend(start=100.0, step=1.0)),
                "ticker:MU": _build_bars(_uptrend(start=90.0, step=0.7)),
                "ticker:ASML": _build_bars(_uptrend(start=600.0, step=0.6)),
                "ticker:ORCL": _build_bars([100.0] * 218 + [99.0, 101.0]),
                "ticker:NLR": _build_bars(_uptrend(start=70.0, step=0.25)),
            }
        ),
        earnings_provider=_FakeEarningsProvider(
            {
                "ORCL": date(2025, 8, 11),
            }
        ),
    )
    settings = _build_settings(
        portfolio_current_positions=["goog", "nvda"],
        portfolio_cost_basis={"goog": 120.0, "nvda": 150.0},
    )

    result = factor.evaluate(
        _build_context(
            settings,
            now=datetime(2025, 8, 10, 16, 15, tzinfo=UTC),
            force_run=True,
        )
    )

    assert result.severity == Severity.INFO
    assert result.metrics["regime"] == "green"
    assert "GOOG (20%): 加仓" in result.details
    assert "NVDA (18%): 加仓" in result.details
    assert "ORCL (10%): 暂停" in result.details
    assert "3 天内有财报" in result.details


def test_ai_portfolio_red_regime_reduces_high_beta_positions() -> None:
    factor = AIPortfolioFactor(
        provider=_FakeSeriesProvider(
            {
                "vix": _build_bars([22.0] * 219 + [31.0]),
                "ticker:QQQ": _build_bars(_uptrend(start=300.0, step=1.0)),
                "ticker:SMH": _build_bars(_uptrend(start=200.0, step=1.0)),
                "ticker:GOOG": _build_bars(_uptrend(start=150.0, step=0.8)),
                "ticker:NVDA": _build_bars([100.0] * 218 + [80.0, 79.0]),
                "ticker:MU": _build_bars([100.0] * 218 + [92.0, 90.0]),
                "ticker:ASML": _build_bars(_uptrend(start=600.0, step=0.6)),
                "ticker:ORCL": _build_bars([100.0] * 218 + [99.0, 101.0]),
                "ticker:NLR": _build_bars(_uptrend(start=70.0, step=0.25)),
            }
        ),
        earnings_provider=_FakeEarningsProvider(),
    )
    settings = _build_settings(
        portfolio_current_positions=["GOOG", "NVDA", "MU", "ASML", "ORCL", "NLR"],
        portfolio_cost_basis={
            "GOOG": 120.0,
            "NVDA": 110.0,
            "MU": 95.0,
            "ASML": 620.0,
            "ORCL": 100.0,
            "NLR": 80.0,
        },
    )

    result = factor.evaluate(
        _build_context(
            settings,
            now=datetime(2025, 8, 10, 16, 15, tzinfo=UTC),
            force_run=True,
        )
    )

    assert result.severity == Severity.CRITICAL
    assert result.metrics["regime"] == "red"
    assert "GOOG (20%): 暂停" in result.details
    assert "NVDA (18%): 减仓" in result.details
    assert "MU (15%): 减仓" in result.details
    assert "ASML (12%): 减仓" in result.details
    assert "ORCL (10%): 减仓" in result.details
    assert "NLR (10%): 减仓" in result.details
