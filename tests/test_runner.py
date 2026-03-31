from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from sentrymode.monitoring import FactorResult, MonitorRunner, Settings, Severity


class _DummyNotifier:
    def __init__(
        self,
    ) -> None:
        self.calls: list[tuple[str, str]] = []

    def send(
        self,
        title: str,
        body: str,
    ) -> None:
        self.calls.append((title, body))


@dataclass
class _StaticFactor:
    name: str
    display_name: str
    should_run: bool = True
    raise_error: bool = False
    localized_name: str | None = None

    def should_evaluate(
        self,
        context,
    ) -> bool:
        return self.should_run

    def evaluate(
        self,
        context,
    ) -> FactorResult:
        if self.raise_error:
            raise RuntimeError(f"{self.name} failed")

        return FactorResult(
            factor_name=self.name,
            display_name=self.display_name,
            severity=Severity.INFO,
            title=f"{self.display_name} ok",
            summary="all good",
            details="details",
            metrics={"x": 1},
        )

    def localized_display_name(
        self,
        settings: Settings,
    ) -> str:
        return self.localized_name or self.display_name


class _NoLocalizedFactor(_StaticFactor):
    def localized_display_name(  # type: ignore[override]
        self,
        settings: Settings,
    ) -> str:
        raise AssertionError("should not be called")


def _build_settings(
    **overrides,
) -> Settings:
    payload = {
        "_env_file": None,
        "bark_server": "https://example.com",
        "bark_device_key": "device-key",
        "enabled_factors": ["alpha"],
    }
    payload.update(overrides)
    return Settings(**payload)


def test_runner_factor_names_are_sorted() -> None:
    runner = MonitorRunner(
        factors=[_StaticFactor("z", "Z"), _StaticFactor("a", "A")],
        settings=_build_settings(enabled_factors=["a"]),
        notifier=_DummyNotifier(),
    )

    assert runner.factor_names() == ["a", "z"]


def test_runner_run_once_skips_factor_when_not_due() -> None:
    notifier = _DummyNotifier()
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha", should_run=False)],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=notifier,
    )

    results = runner.run_once(force=False)

    assert results == []
    assert notifier.calls == []


def test_runner_run_once_runs_factor_when_forced() -> None:
    notifier = _DummyNotifier()
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha", should_run=False)],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=notifier,
    )

    results = runner.run_once(force=True)

    assert len(results) == 1
    assert results[0].factor_name == "alpha"
    assert len(notifier.calls) == 1


def test_runner_run_once_isolates_factor_exception_and_uses_localized_name() -> None:
    notifier = _DummyNotifier()
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha", raise_error=True, localized_name="Localized Alpha")],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=notifier,
    )

    results = runner.run_once(force=True)

    assert len(results) == 1
    assert results[0].severity == Severity.ERROR
    assert results[0].display_name == "Localized Alpha"
    assert "failed" in results[0].summary
    assert len(notifier.calls) == 1


def test_runner_run_once_raises_for_unknown_factor() -> None:
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=_DummyNotifier(),
    )

    with pytest.raises(ValueError, match="Unknown factors requested: missing"):
        runner.run_once(factor_names=["missing"], force=True)


def test_runner_resolve_factors_uses_enabled_defaults() -> None:
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=_DummyNotifier(),
    )

    resolved = runner._resolve_factors(None)

    assert [factor.name for factor in resolved] == ["alpha"]


def test_runner_build_selected_report_plain_and_markdown() -> None:
    result = FactorResult(
        factor_name="alpha",
        display_name="Alpha",
        severity=Severity.WARNING,
        title="alert",
        summary="summary text",
        details="details text",
        metrics={"m1": 10},
    )
    now = datetime(2025, 2, 1, 10, 0, tzinfo=UTC)

    plain_runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"], report_format="plain"),
        notifier=_DummyNotifier(),
    )
    markdown_runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"], report_format="markdown"),
        notifier=_DummyNotifier(),
    )

    plain_title, plain_body = plain_runner._build_selected_report([result], now)
    markdown_title, markdown_body = markdown_runner._build_selected_report([result], now)

    assert "SentryMode Monitor Report" in plain_title
    assert "Metrics" in plain_body
    assert markdown_title == "SentryMode Monitor Report"
    assert "## Alpha" in markdown_body
    assert "Factor count" in markdown_body


def test_runner_severity_label_uses_language() -> None:
    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"], report_language="zh"),
        notifier=_DummyNotifier(),
    )

    assert runner._severity_label(Severity.INFO) == "信息"
    assert runner._severity_label(Severity.CRITICAL) == "严重"


def test_runner_factor_display_name_falls_back_to_display_name() -> None:
    runner = MonitorRunner(
        factors=[_NoLocalizedFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"]),
        notifier=_DummyNotifier(),
    )

    factor = _NoLocalizedFactor("alpha", "Alpha")
    factor.localized_display_name = "not-callable"  # type: ignore[assignment]

    assert runner._factor_display_name(factor) == "Alpha"


def test_runner_run_forever_calls_sleep_with_poll_interval() -> None:
    notifier = _DummyNotifier()
    sleep_calls: list[float] = []

    class _StopLoop(Exception):
        pass

    def fake_sleep(
        seconds: float,
    ) -> None:
        sleep_calls.append(seconds)
        raise _StopLoop

    runner = MonitorRunner(
        factors=[_StaticFactor("alpha", "Alpha")],
        settings=_build_settings(enabled_factors=["alpha"], poll_interval_seconds=7),
        notifier=notifier,
        sleep_fn=fake_sleep,
    )

    with pytest.raises(_StopLoop):
        runner.run_forever(factor_names=["alpha"])

    assert sleep_calls == [7]
    assert len(notifier.calls) == 1
