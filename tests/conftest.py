"""Pytest configuration for SentryMode tests."""

from __future__ import annotations

from typing import Generator

import pytest

from sentrymode.monitoring import Settings


def pytest_addoption(
    parser: pytest.Parser,
) -> None:
    """Register custom CLI options for test runs."""
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests marked with 'network' that access public APIs.",
    )


def pytest_configure(
    config: pytest.Config,
) -> None:
    """Declare custom markers used in this test suite."""
    config.addinivalue_line("markers", "network: marks tests that require network access")


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip network tests unless explicitly enabled."""
    if config.getoption("--run-network"):
        return

    skip_network = pytest.mark.skip(reason="requires --run-network option")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)


@pytest.fixture(autouse=True)
def set_up_and_tear_down(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Set up and tear down the test environment."""
    monkeypatch.setenv("SENTRYMODE_BARK_SERVER", "http://127.0.0.1:1")
    monkeypatch.setenv("SENTRYMODE_BARK_DEVICE_KEY", "test-bark-device-key")
    yield


@pytest.fixture
def base_settings() -> Settings:
    """Build baseline settings for tests without reading .env."""
    return Settings(
        _env_file=None,
        bark_server="https://example.com",
        bark_device_key="device-key",
    )
