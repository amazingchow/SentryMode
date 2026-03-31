from __future__ import annotations

from argparse import Namespace

import pytest

import sentrymode.__main__ as cli
from sentrymode import __version__
from sentrymode.factors import list_factor_names
from sentrymode.monitoring import Settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_output(
    capsys,
) -> None:
    cli.main([])
    captured = capsys.readouterr()
    assert "SentryMode" in captured.out


def test_registered_factors_include_us10y() -> None:
    assert "us10y" in list_factor_names()
    assert "btc_realized_pl_ratio_90d" in list_factor_names()


def test_default_enabled_factors_exclude_us10y() -> None:
    settings = Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
    )
    assert "us10y" not in settings.enabled_factors
    assert "btc_realized_pl_ratio_90d" not in settings.enabled_factors


def test_build_runner_wires_settings_notifier_and_factors(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    class _FakeSettings:
        bark_server = "https://bark.example.com"
        bark_device_key = "device-key"
        report_format = "plain"
        ahr_http_timeout_seconds = 9.0

    def fake_settings() -> _FakeSettings:
        return _FakeSettings()

    def fake_create_factors() -> list[str]:
        return ["factor-a", "factor-b"]

    class _FakeNotifier:
        def __init__(
            self,
            bark_server: str,
            bark_device_key: str,
            report_format: str,
            timeout_seconds: float,
        ) -> None:
            observed["notifier_args"] = {
                "bark_server": bark_server,
                "bark_device_key": bark_device_key,
                "report_format": report_format,
                "timeout_seconds": timeout_seconds,
            }

    class _FakeRunner:
        def __init__(
            self,
            *,
            factors,
            settings,
            notifier,
        ) -> None:
            observed["runner_args"] = {
                "factors": factors,
                "settings": settings,
                "notifier": notifier,
            }

    monkeypatch.setattr(cli, "Settings", fake_settings)
    monkeypatch.setattr(cli, "create_factors", fake_create_factors)
    monkeypatch.setattr(cli, "ConsoleBarkNotifier", _FakeNotifier)
    monkeypatch.setattr(cli, "MonitorRunner", _FakeRunner)

    runner = cli.build_runner()

    assert isinstance(runner, _FakeRunner)
    assert observed["notifier_args"] == {
        "bark_server": "https://bark.example.com",
        "bark_device_key": "device-key",
        "report_format": "plain",
        "timeout_seconds": 9.0,
    }
    assert observed["runner_args"]["factors"] == ["factor-a", "factor-b"]


def test_print_factor_list_marks_enabled(
    monkeypatch,
    capsys,
) -> None:
    class _FakeSettings:
        enabled_factors = ["vix"]

    monkeypatch.setattr(cli, "Settings", lambda: _FakeSettings())
    monkeypatch.setattr(cli, "list_factor_names", lambda: ["ahr999", "vix"])

    cli.print_factor_list()
    captured = capsys.readouterr()

    assert "Available factors:" in captured.out
    assert "- vix (enabled)" in captured.out
    assert "- ahr999" in captured.out


def test_main_dispatches_list_factors(
    monkeypatch,
) -> None:
    called = False

    def fake_print_factor_list() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(cli, "print_factor_list", fake_print_factor_list)

    cli.main(["list-factors"])

    assert called is True


def test_main_dispatches_run_once_with_selected_factors(
    monkeypatch,
) -> None:
    observed: list[tuple[list[str] | None, bool]] = []

    class _FakeRunner:
        def run_once(
            self,
            *,
            factor_names: list[str] | None,
            force: bool,
        ) -> None:
            observed.append((factor_names, force))

    monkeypatch.setattr(cli, "build_runner", lambda: _FakeRunner())

    cli.main(["run-once", "--factor", "vix", "--factor", "ahr999"])

    assert observed == [(["vix", "ahr999"], True)]


def test_main_dispatches_run_monitor(
    monkeypatch,
) -> None:
    observed: list[list[str] | None] = []

    class _FakeRunner:
        def run_forever(
            self,
            *,
            factor_names: list[str] | None,
        ) -> None:
            observed.append(factor_names)

    monkeypatch.setattr(cli, "build_runner", lambda: _FakeRunner())

    cli.main(["run-monitor", "--factor", "vix"])

    assert observed == [["vix"]]


def test_main_uses_sys_argv_when_argv_is_none(
    monkeypatch,
) -> None:
    observed: list[tuple[list[str] | None, bool]] = []

    class _FakeRunner:
        def run_once(
            self,
            *,
            factor_names: list[str] | None,
            force: bool,
        ) -> None:
            observed.append((factor_names, force))

    monkeypatch.setattr(cli, "build_runner", lambda: _FakeRunner())
    monkeypatch.setattr(cli.sys, "argv", ["sentrymode", "run-once", "--factor", "vix"])

    cli.main(None)

    assert observed == [(["vix"], True)]


def test_main_unsupported_command_calls_parser_error(
    monkeypatch,
) -> None:
    class _FakeParser:
        def parse_args(
            self,
            argv: list[str],
        ) -> Namespace:
            return Namespace(command="invalid", factors=None)

        def print_help(
            self,
        ) -> None:
            return None

        def error(
            self,
            message: str,
        ) -> None:
            raise RuntimeError(message)

    monkeypatch.setattr(cli, "build_parser", lambda: _FakeParser())
    monkeypatch.setattr(cli, "build_runner", lambda: object())

    with pytest.raises(RuntimeError, match="Unsupported command: invalid"):
        cli.main(["invalid"])
