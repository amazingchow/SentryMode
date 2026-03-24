"""
Factor orchestration and report assembly.

[INPUT]: Factor instances, runtime `Settings`, notifier adapter, and optional factor filters.
[OUTPUT]: Aggregated execution results plus formatted notifications (plain or markdown).
[POS]: Orchestration layer in `sentrymode.monitoring`.
       Upstream: CLI commands and single-factor helpers.
       Downstream: factor protocol calls and notifier side effects.

[PROTOCOL]:
1. Isolate factor exceptions into error results so one failure does not crash the cycle.
2. Keep scheduling/dispatch logic here; factors decide strategy signals only.
3. Sync localized label dictionaries when report fields or severities change.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from colorama import Fore, Style

from sentrymode.monitoring.models import Factor, FactorResult, MonitorContext, Notifier, Severity
from sentrymode.monitoring.settings import Settings


class MonitorRunner:
    """Run one or more monitoring factors on demand or on a shared schedule."""

    _LOCALIZED_TEXT = {
        "en": {
            "report_title": "SentryMode Monitor Report",
            "plain_title": "Title",
            "plain_summary": "Summary",
            "plain_details": "Details",
            "plain_metrics": "Metrics",
            "markdown_summary": "Summary",
            "markdown_details": "Details",
            "markdown_metrics": "Metrics",
            "generated_at": "Generated at",
            "factor": "Factor",
            "factor_count": "Factor count",
            "severity": "Severity",
            "execution_failed": "execution failed",
            "exception_details": "The factor raised an exception during evaluation.",
            "severity_info": "INFO",
            "severity_warning": "WARNING",
            "severity_critical": "CRITICAL",
            "severity_error": "ERROR",
        },
        "zh": {
            "report_title": "SentryMode 监控报告",
            "plain_title": "标题",
            "plain_summary": "摘要",
            "plain_details": "详情",
            "plain_metrics": "指标",
            "markdown_summary": "摘要",
            "markdown_details": "详情",
            "markdown_metrics": "指标",
            "generated_at": "生成时间",
            "factor": "因子",
            "factor_count": "因子数量",
            "severity": "级别",
            "execution_failed": "执行失败",
            "exception_details": "该因子在执行过程中抛出了异常。",
            "severity_info": "信息",
            "severity_warning": "预警",
            "severity_critical": "严重",
            "severity_error": "错误",
        },
    }

    def __init__(
        self,
        *,
        factors: list[Factor],
        settings: Settings,
        notifier: Notifier,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._notifier = notifier
        self._sleep_fn = sleep_fn
        self._factors_by_name = {factor.name: factor for factor in factors}
        self._last_evaluated_at: dict[str, datetime] = {}

    def factor_names(
        self,
    ) -> list[str]:
        """Return all registered factor names."""
        return sorted(self._factors_by_name)

    def run_once(
        self,
        *,
        factor_names: list[str] | None = None,
        force: bool = False,
    ) -> list[FactorResult]:
        """Run selected factors once and emit a single aggregated notification."""
        now = datetime.now(UTC)
        context = MonitorContext(
            now=now,
            settings=self._settings,
            last_evaluated_at=dict(self._last_evaluated_at),
            force_run=force,
        )

        factors = self._resolve_factors(factor_names)
        results: list[FactorResult] = []

        for factor in factors:
            if not force and not factor.should_evaluate(context):
                continue

            try:
                result = factor.evaluate(context)
            except Exception as exc:
                text = self._localized_text()
                display_name = self._factor_display_name(factor)
                result = FactorResult(
                    factor_name=factor.name,
                    display_name=display_name,
                    severity=Severity.ERROR,
                    title=f"{display_name} {text['execution_failed']}",
                    summary=str(exc),
                    details=text["exception_details"],
                )

            self._last_evaluated_at[factor.name] = now
            results.append(result)

        if results:
            title, body = self._build_selected_report(results, now)
            self._notifier.send(title, body)

        return results

    def run_forever(
        self,
        *,
        factor_names: list[str] | None = None,
    ) -> None:
        """Run the shared scheduling loop forever."""
        chosen_factors = self._resolve_factors(factor_names)
        display_names = ", ".join(factor.name for factor in chosen_factors)
        print(f"{Fore.GREEN}Starting shared monitor loop for: {display_names}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}Polling every {self._settings.poll_interval_seconds} seconds.{Style.RESET_ALL}")

        while True:
            self.run_once(
                factor_names=[factor.name for factor in chosen_factors],
                force=False,
            )
            self._sleep_fn(self._settings.poll_interval_seconds)

    def _resolve_factors(
        self,
        factor_names: list[str] | None,
    ) -> list[Factor]:
        names = factor_names or self._settings.enabled_factors
        unknown_names = sorted(set(names) - self._factors_by_name.keys())
        if unknown_names:
            raise ValueError(f"Unknown factors requested: {', '.join(unknown_names)}")
        return [self._factors_by_name[name] for name in names]

    def _build_report(
        self,
        results: list[FactorResult],
        now: datetime,
    ) -> tuple[str, str]:
        text = self._localized_text()
        title = f"{text['report_title']} ({now.astimezone().strftime('%Y-%m-%d %H:%M:%S')})"
        sections = []
        for result in results:
            metrics_text = ""
            if result.metrics:
                formatted_metrics = ", ".join(f"{key}={value}" for key, value in result.metrics.items())
                metrics_text = f"\n{text['plain_metrics']}: {formatted_metrics}"

            sections.append(
                "\n".join(
                    [
                        f"[{self._severity_label(result.severity)}] {result.display_name}",
                        f"{text['plain_title']}: {result.title}",
                        f"{text['plain_summary']}: {result.summary}",
                        f"{text['plain_details']}: {result.details}{metrics_text}",
                    ]
                )
            )

        return title, "\n\n".join(sections)

    def _build_markdown_formatted_report(
        self,
        results: list[FactorResult],
        now: datetime,
    ) -> tuple[str, str]:
        text = self._localized_text()
        title = f"{text['report_title']}"
        sections = [
            "",
            f"- **{text['generated_at']}**: `{now.astimezone().strftime('%Y-%m-%d %H:%M:%S')}`",
            f"- **{text['factor_count']}**: `{len(results)}`",
            "",
        ]

        for result in results:
            sections.extend(
                [
                    "",
                    f"## {result.display_name}",
                    "",
                    f"- **{text['severity']}**: `{self._severity_label(result.severity)}`",
                    f"- **{text['plain_title']}**: {result.title}",
                    "",
                    f"### {text['markdown_summary']}",
                    "",
                    result.summary,
                    "",
                    f"### {text['markdown_details']}",
                    "",
                    result.details,
                    "",
                ]
            )

            # if result.metrics:
            #     sections.append(f"### {text['markdown_metrics']}")
            #     sections.append("")
            #     sections.append("| Key | Value |")
            #     sections.append("| --- | --- |")
            #     for key, value in result.metrics.items():
            #         sections.append(f"| `{key}` | `{value}` |")
            #     sections.append("")

        body = "\n".join(sections).rstrip()
        return title, body

    def _build_selected_report(
        self,
        results: list[FactorResult],
        now: datetime,
    ) -> tuple[str, str]:
        report_format = self._settings.report_format.strip().lower()
        if report_format == "plain":
            return self._build_report(results, now)
        return self._build_markdown_formatted_report(results, now)

    def _localized_text(
        self,
    ) -> dict[str, str]:
        language = self._settings.report_language.strip().lower()
        return self._LOCALIZED_TEXT.get(language, self._LOCALIZED_TEXT["en"])

    def _severity_label(
        self,
        severity: Severity,
    ) -> str:
        text = self._localized_text()
        return text.get(f"severity_{severity.value}", severity.value.upper())

    def _factor_display_name(
        self,
        factor: Factor,
    ) -> str:
        localized_display_name = getattr(factor, "localized_display_name", None)
        if callable(localized_display_name):
            return localized_display_name(self._settings)
        return factor.display_name
