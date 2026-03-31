from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

import sentrymode.factors.ahr999 as ahr999_module
from sentrymode.factors.ahr999 import AHR999Factor
from sentrymode.monitoring import MonitorContext, Settings, Severity


class _DummyResponse:
    def __init__(
        self,
        payload: dict[str, object],
    ) -> None:
        self._payload = payload

    def raise_for_status(
        self,
    ) -> None:
        return None

    def json(
        self,
    ) -> dict[str, object]:
        return self._payload


def _build_settings(
    **overrides,
) -> Settings:
    payload = {
        "_env_file": None,
        "bark_server": "https://example.com",
        "bark_device_key": "device-key",
        "ahr_run_timezone": "UTC",
        "ahr_run_hour": 9,
        "ahr_run_minute": 20,
        "ahr_lookback_days": 5,
        "ahr_genesis_date": date(2009, 1, 3),
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


def test_ahr999_should_evaluate_respects_schedule_and_last_run() -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    should_run = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 9, 20, tzinfo=UTC),
        )
    )
    should_skip_wrong_minute = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 9, 19, tzinfo=UTC),
        )
    )
    should_skip_same_day = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 9, 20, tzinfo=UTC),
            last_evaluated_at={factor.name: datetime(2025, 2, 1, 9, 0, tzinfo=UTC)},
        )
    )
    forced = factor.should_evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 1, 0, tzinfo=UTC),
            force_run=True,
        )
    )

    assert should_run is True
    assert should_skip_wrong_minute is False
    assert should_skip_same_day is False
    assert forced is True


def test_ahr999_fetch_kraken_success(
    monkeypatch,
) -> None:
    factor = AHR999Factor()
    settings = _build_settings(ahr_lookback_days=3)

    def fake_get(
        url: str,
        *,
        params: dict[str, object],
        timeout: float,
    ) -> _DummyResponse:
        assert params["pair"] == settings.ahr_kraken_pair
        return _DummyResponse(
            {
                "error": [],
                "result": {
                    "XXBTZUSD": [
                        [0, 0, 0, 0, "1.1"],
                        [0, 0, 0, 0, "2.2"],
                        [0, 0, 0, 0, "3.3"],
                    ],
                    "last": "abc",
                },
            }
        )

    monkeypatch.setattr(ahr999_module.httpx, "get", fake_get)

    closes = factor._fetch_bitcoin_data_from_kraken(settings)

    assert closes == [1.1, 2.2, 3.3]


def test_ahr999_fetch_kraken_raises_on_api_error(
    monkeypatch,
) -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    monkeypatch.setattr(
        ahr999_module.httpx,
        "get",
        lambda *args, **kwargs,: _DummyResponse({"error": ["EGeneral:Invalid arguments"], "result": {}}),
    )

    with pytest.raises(RuntimeError, match="Kraken API error"):
        factor._fetch_bitcoin_data_from_kraken(settings)


def test_ahr999_fetch_kraken_raises_on_missing_pair_data(
    monkeypatch,
) -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    monkeypatch.setattr(
        ahr999_module.httpx,
        "get",
        lambda *args, **kwargs,: _DummyResponse({"error": [], "result": {"last": "123"}}),
    )

    with pytest.raises(RuntimeError, match="does not contain OHLC data"):
        factor._fetch_bitcoin_data_from_kraken(settings)


def test_ahr999_calculate_requires_enough_history() -> None:
    factor = AHR999Factor()
    settings = _build_settings(ahr_lookback_days=5)

    with pytest.raises(ValueError, match="at least 5 days"):
        factor._calculate_ahr999(
            closes=[1.0, 2.0, 3.0],
            settings=settings,
            today=date(2025, 2, 1),
        )


def test_ahr999_classification_thresholds() -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    strategy, severity = factor._classify_ahr999(0.44, settings)
    assert severity == Severity.WARNING
    assert "Accumulate" in strategy

    assert factor._classify_ahr999(0.45, settings)[1] == Severity.INFO
    assert factor._classify_ahr999(1.2, settings)[1] == Severity.INFO
    assert factor._classify_ahr999(1.2001, settings)[1] == Severity.WARNING
    assert factor._classify_ahr999(5.0, settings)[1] == Severity.WARNING
    assert factor._classify_ahr999(5.01, settings)[1] == Severity.CRITICAL


def test_ahr999_build_message_contains_key_sections() -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    summary, details = factor._build_ahr999_message(
        ahr999=1.1,
        current_price=35000,
        gma200=30000,
        estimated_price=40000,
        strategy="DCA",
        settings=settings,
    )

    assert "AHR999=1.1000" in summary
    assert "Current BTC price" in details
    assert "Strategy" in details


def test_ahr999_evaluate_returns_factor_result(
    monkeypatch,
) -> None:
    factor = AHR999Factor()
    settings = _build_settings()

    monkeypatch.setattr(
        AHR999Factor,
        "_fetch_bitcoin_data_from_kraken",
        lambda self, settings,: [10000.0, 12000.0, 13000.0, 14000.0, 15000.0],
    )

    result = factor.evaluate(
        _build_context(
            settings,
            now=datetime(2025, 2, 1, 9, 20, tzinfo=UTC),
            force_run=True,
        )
    )

    assert result.factor_name == "ahr999"
    assert "AHR999" in result.title
    assert "ahr999" in result.metrics


def test_ahr999_build_runner_helpers(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    class _FakeSettings:
        bark_server = "https://bark.example.com"
        bark_device_key = "k"
        report_format = "markdown"
        ahr_http_timeout_seconds = 1.5

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

    monkeypatch.setattr(ahr999_module, "Settings", _FakeSettings)
    monkeypatch.setattr(ahr999_module, "ConsoleBarkNotifier", _FakeNotifier)
    monkeypatch.setattr(ahr999_module, "MonitorRunner", _FakeRunner)

    runner = ahr999_module.build_ahr999_runner()

    assert isinstance(runner, _FakeRunner)
    assert observed["enabled_factors"] == ["ahr999"]
    assert observed["notifier"] == ("https://bark.example.com", "k", "markdown", 1.5)


def test_ahr999_run_helpers_dispatch(
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

    monkeypatch.setattr(ahr999_module, "build_ahr999_runner", lambda: _FakeRunner())

    ahr999_module.run_once()
    ahr999_module.run_monitor()

    assert calls == [
        ("run_once", ["ahr999"], True),
        ("run_forever", ["ahr999"], None),
    ]


def test_ahr999_get_timezone() -> None:
    factor = AHR999Factor()
    settings = _build_settings(ahr_run_timezone="America/New_York")

    timezone = factor._get_ahr_timezone(settings)

    assert str(timezone) == "America/New_York"


def test_ahr999_calculate_returns_tuple_values() -> None:
    factor = AHR999Factor()
    settings = _build_settings(ahr_lookback_days=5)

    ahr999_value, current_price, gma200, estimated_price = factor._calculate_ahr999(
        closes=[10000.0, 11000.0, 12000.0, 13000.0, 14000.0],
        settings=settings,
        today=date(2025, 2, 1),
    )

    assert ahr999_value > 0
    assert current_price == 14000.0
    assert gma200 > 0
    assert estimated_price > 0
