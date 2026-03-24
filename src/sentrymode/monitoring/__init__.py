"""
Monitoring package public API facade.

[INPUT]: Import-time module loading.
[OUTPUT]: Stable public exports for settings, protocols, result models, runner, and notifier.
[POS]: Facade for the monitoring kernel package.
       Upstream: CLI and factor modules.
       Downstream: `models.py`, `settings.py`, `runner.py`, `notifiers.py`.

[PROTOCOL]:
1. Keep `__all__` aligned with supported public API.
2. Avoid importing factor packages here to preserve layer direction.
"""

from sentrymode.monitoring.models import Factor, FactorResult, MonitorContext, Notifier, Severity
from sentrymode.monitoring.notifiers import ConsoleBarkNotifier
from sentrymode.monitoring.runner import MonitorRunner
from sentrymode.monitoring.settings import Settings

__all__ = [
    "ConsoleBarkNotifier",
    "Factor",
    "FactorResult",
    "MonitorContext",
    "MonitorRunner",
    "Notifier",
    "Settings",
    "Severity",
]
