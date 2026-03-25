from __future__ import annotations

from sentrymode import __version__
from sentrymode.__main__ import main
from sentrymode.factors import list_factor_names
from sentrymode.monitoring import Settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_output(
    capsys,
) -> None:
    main([])
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
