from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentrymode.monitoring import Settings


def test_settings_trim_bark_values() -> None:
    settings = Settings(
        _env_file=None,
        bark_server=" https://example.com ",
        bark_device_key=" key-1 ",
    )

    assert settings.bark_server == "https://example.com"
    assert settings.bark_device_key == "key-1"


def test_settings_rejects_none_bark_server() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        Settings(
            _env_file=None,
            bark_server=None,
            bark_device_key="device-key",
        )


def test_settings_rejects_non_string_bark_server() -> None:
    with pytest.raises(TypeError, match="must be strings"):
        Settings(
            _env_file=None,
            bark_server=123,
            bark_device_key="device-key",
        )


def test_settings_rejects_blank_bark_device_key() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="   ",
        )


def test_settings_normalizes_report_format_and_language() -> None:
    settings = Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        report_format=" MARKDOWN ",
        report_language=" ZH ",
    )

    assert settings.report_format == "markdown"
    assert settings.report_language == "zh"


def test_settings_rejects_invalid_report_format() -> None:
    with pytest.raises(ValidationError, match="report_format must be 'plain' or 'markdown'"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="device-key",
            report_format="html",
        )


def test_settings_rejects_non_string_report_format() -> None:
    with pytest.raises(TypeError, match="report_format must be a string"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="device-key",
            report_format=1,
        )


def test_settings_rejects_invalid_report_language() -> None:
    with pytest.raises(ValidationError, match="report_language must be 'en' or 'zh'"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="device-key",
            report_language="jp",
        )


def test_settings_rejects_non_string_report_language() -> None:
    with pytest.raises(TypeError, match="report_language must be a string"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="device-key",
            report_language=2,
        )


def test_settings_normalize_portfolio_positions_and_cost_basis() -> None:
    settings = Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
        portfolio_current_positions=[" goog ", "NVDA", "goog"],
        portfolio_cost_basis={" goog ": 120, "nvda": 150.5},
    )

    assert settings.portfolio_current_positions == ["GOOG", "NVDA"]
    assert settings.portfolio_cost_basis == {"GOOG": 120.0, "NVDA": 150.5}


def test_settings_rejects_non_positive_portfolio_cost_basis() -> None:
    with pytest.raises(ValidationError, match="must be positive"):
        Settings(
            _env_file=None,
            bark_server="https://example.com",
            bark_device_key="device-key",
            portfolio_cost_basis={"GOOG": 0},
        )
