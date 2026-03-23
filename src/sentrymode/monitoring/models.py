"""Core monitoring domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sentrymode.monitoring.settings import Settings

MetricValue = str | float | int


class Severity(StrEnum):
    """Supported severities for factor evaluation results."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class FactorResult:
    """Structured result emitted by a monitoring factor."""

    factor_name: str
    display_name: str
    severity: Severity
    title: str
    summary: str
    details: str
    metrics: dict[str, MetricValue] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MonitorContext:
    """Runtime context shared with factor execution."""

    now: datetime
    settings: Settings
    last_evaluated_at: dict[str, datetime]
    force_run: bool = False

    def last_run_for(
        self,
        factor_name: str,
    ) -> datetime | None:
        """Return the last execution time for the given factor, if any."""
        return self.last_evaluated_at.get(factor_name)


class Factor(Protocol):
    """Protocol implemented by all monitoring factors."""

    name: str
    display_name: str

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Return whether the factor should execute for the given context."""

    def evaluate(
        self,
        context: MonitorContext,
    ) -> FactorResult:
        """Evaluate the factor and return a structured result."""


class Notifier(Protocol):
    """Protocol for downstream notification senders."""

    def send(
        self,
        title: str,
        body: str,
    ) -> None:
        """Send a notification message."""
