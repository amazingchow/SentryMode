"""Pytest configuration for SentryMode tests."""

from __future__ import annotations

from typing import Generator

import pytest


@pytest.fixture(autouse=True)
def set_up_and_tear_down(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Set up and tear down the test environment."""
    monkeypatch.setenv("SENTRYMODE_BARK_SERVER", "http://127.0.0.1:1")
    monkeypatch.setenv("SENTRYMODE_BARK_DEVICE_KEY", "test-bark-device-key")
    yield
    # Teardown code here
