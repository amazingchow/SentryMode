"""
BTC realized P/L ratio 90-day SMA factor.

[INPUT]: `MonitorContext` + BTC realized profit/loss ratio daily series from `GlassnodeSeriesProvider`.
[OUTPUT]: `FactorResult` with SMA90 regime, threshold-crossing signal, and cycle guidance.
[POS]: Concrete factor plugin in `sentrymode.factors`.
       Upstream: factor registry + `MonitorRunner`.
       Downstream: `sentrymode.market_data` Glassnode provider seam and monitoring result contracts.

[PROTOCOL]:
1. Keep vendor-specific HTTP behavior inside `sentrymode.market_data`; this module should consume normalized daily values only.
2. Base regime and signal decisions on the smoothed SMA90 series, not on the raw daily ratio.
3. Raise explicit errors for missing API credentials or insufficient history so runner isolation remains effective.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from zoneinfo import ZoneInfo

from sentrymode.market_data import DailyBar, DailySeriesProvider, GlassnodeSeriesProvider
from sentrymode.monitoring import (
    ConsoleBarkNotifier,
    FactorResult,
    MonitorContext,
    MonitorRunner,
    Settings,
    Severity,
)


@dataclass(slots=True)
class BTCRealizedPLRatio90DFactor:
    """BTC cycle factor based on realized profit/loss ratio SMA90."""

    _LOCALIZED_TEXT = {
        "en": {
            "display_name": "BTC Realized P/L Ratio (SMA90)",
            "title_prefix": "BTC realized P/L ratio",
            "summary_template": "{regime} | {signal} | SMA90={sma90:.4f}",
            "details_signal": "Cycle signal: {value}",
            "details_ratio": "Latest realized P/L ratio: {value:.4f}",
            "details_sma90": "90-day simple moving average: {value:.4f}",
            "details_previous_sma90": "Previous 90-day simple moving average: {value:.4f}",
            "details_threshold": "Cycle threshold: {value:.4f}",
            "details_interpretation": "Interpretation: {value}",
            "regime_profit_dominant": "profit_dominant",
            "regime_loss_dominant": "loss_dominant",
            "signal_crossed_below_1": "crossed_below_1",
            "signal_reclaimed_above_1": "reclaimed_above_1",
            "signal_still_below_1": "still_below_1",
            "signal_still_above_1": "still_above_1",
            "guidance_profit_dominant": "Realized profits dominate again. Treat this as a higher-conviction right-side cycle confirmation.",
            "guidance_loss_dominant": "Realized losses dominate. Treat this as a bear-market bottom zone and stay patient with sizing.",
        },
        "zh": {
            "display_name": "BTC 已实现盈亏比（90日均值）",
            "title_prefix": "BTC 已实现盈亏比",
            "summary_template": "{regime} | {signal} | SMA90={sma90:.4f}",
            "details_signal": "周期信号: {value}",
            "details_ratio": "最新已实现盈亏比: {value:.4f}",
            "details_sma90": "90 日简单均值: {value:.4f}",
            "details_previous_sma90": "前一日 90 日简单均值: {value:.4f}",
            "details_threshold": "周期阈值: {value:.4f}",
            "details_interpretation": "市场解读: {value}",
            "regime_profit_dominant": "盈利主导",
            "regime_loss_dominant": "亏损主导",
            "signal_crossed_below_1": "跌破 1",
            "signal_reclaimed_above_1": "重新站回 1 上方",
            "signal_still_below_1": "仍在 1 下方",
            "signal_still_above_1": "仍在 1 上方",
            "guidance_profit_dominant": "已实现利润重新占优，可视作熊市结束后的高确定性右侧确认信号。",
            "guidance_loss_dominant": "已实现亏损占优，可视作熊市底部区域信号，仓位上更适合保持耐心。",
        },
    }

    provider: DailySeriesProvider = field(default_factory=GlassnodeSeriesProvider)
    name: str = "btc_realized_pl_ratio_90d"
    display_name: str = "BTC Realized P/L Ratio (SMA90)"

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Evaluate once per configured day/time unless forced."""
        if context.force_run:
            return True

        timezone = self._get_factor_timezone(context.settings)
        local_now = context.now.astimezone(timezone)
        if (
            local_now.hour != context.settings.btc_realized_pl_ratio_90d_run_hour
            or local_now.minute != context.settings.btc_realized_pl_ratio_90d_run_minute
        ):
            return False

        last_run = context.last_run_for(self.name)
        if last_run is None:
            return True

        return last_run.astimezone(timezone).date() != local_now.date()

    def evaluate(
        self,
        context: MonitorContext,
    ) -> FactorResult:
        """Evaluate BTC realized P/L ratio SMA90 regime and threshold-crossing state."""
        ratio_bars = self.provider.get_series("btc_realized_pl_ratio", context.settings)
        signals = self._calculate_signals(ratio_bars, context.settings)
        regime = self._classify_regime(signals["sma90"], context.settings)
        signal = self._classify_signal(
            current_sma=signals["sma90"],
            previous_sma=signals["previous_sma90"],
            settings=context.settings,
        )
        title, summary, details = self._build_message(regime, signal, signals, context.settings)
        display_name = self._display_name(context.settings)

        return FactorResult(
            factor_name=self.name,
            display_name=display_name,
            severity=self._severity_for_regime(regime),
            title=title,
            summary=summary,
            details=details,
            metrics={
                "regime": regime,
                "signal": signal,
                "latest_ratio": round(signals["latest_ratio"], 4),
                "sma90": round(signals["sma90"], 4),
                "previous_sma90": round(signals["previous_sma90"], 4),
                "threshold": round(context.settings.btc_realized_pl_ratio_90d_threshold, 4),
            },
        )

    def _get_factor_timezone(
        self,
        settings: Settings,
    ) -> ZoneInfo:
        return ZoneInfo(settings.btc_realized_pl_ratio_90d_run_timezone)

    def _calculate_signals(
        self,
        ratio_bars: list[DailyBar],
        settings: Settings,
    ) -> dict[str, float]:
        required_points = max(
            settings.btc_realized_pl_ratio_90d_lookback_days,
            settings.btc_realized_pl_ratio_90d_sma_window + 1,
        )
        if len(ratio_bars) < required_points:
            raise ValueError(
                "BTC realized P/L ratio factor requires at least "
                f"{required_points} daily points to compute current and previous SMA values."
            )

        ratio_values = [bar.close for bar in ratio_bars[-settings.btc_realized_pl_ratio_90d_lookback_days :]]
        latest_ratio = ratio_values[-1]
        sma90 = self._simple_moving_average(ratio_values, settings.btc_realized_pl_ratio_90d_sma_window)
        previous_sma90 = self._simple_moving_average(ratio_values[:-1], settings.btc_realized_pl_ratio_90d_sma_window)
        return {
            "latest_ratio": latest_ratio,
            "previous_sma90": previous_sma90,
            "sma90": sma90,
        }

    def _simple_moving_average(
        self,
        values: list[float],
        window: int,
    ) -> float:
        if len(values) < window:
            raise ValueError(f"Need at least {window} daily values to compute SMA.")
        return mean(values[-window:])

    def _classify_regime(
        self,
        sma90: float,
        settings: Settings,
    ) -> str:
        if sma90 < settings.btc_realized_pl_ratio_90d_threshold:
            return "loss_dominant"
        return "profit_dominant"

    def _classify_signal(
        self,
        *,
        current_sma: float,
        previous_sma: float,
        settings: Settings,
    ) -> str:
        threshold = settings.btc_realized_pl_ratio_90d_threshold
        if current_sma < threshold:
            if previous_sma >= threshold:
                return "crossed_below_1"
            return "still_below_1"
        if previous_sma < threshold:
            return "reclaimed_above_1"
        return "still_above_1"

    def _severity_for_regime(
        self,
        regime: str,
    ) -> Severity:
        if regime == "loss_dominant":
            return Severity.WARNING
        return Severity.INFO

    def _build_message(
        self,
        regime: str,
        signal: str,
        signals: dict[str, float],
        settings: Settings,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        regime_label = self._regime_label(regime, settings)
        signal_label = self._signal_label(signal, settings)
        guidance = self._guidance_for_regime(regime, settings)

        title = f"{text['title_prefix']}: {regime_label}"
        summary = text["summary_template"].format(
            regime=regime_label,
            signal=signal_label,
            sma90=signals["sma90"],
        )
        details = (
            f"- {text['details_signal'].format(value=signal_label)}\n"
            f"- {text['details_ratio'].format(value=signals['latest_ratio'])}\n"
            f"- {text['details_sma90'].format(value=signals['sma90'])}\n"
            f"- {text['details_previous_sma90'].format(value=signals['previous_sma90'])}\n"
            f"- {text['details_threshold'].format(value=settings.btc_realized_pl_ratio_90d_threshold)}\n"
            f"- {text['details_interpretation'].format(value=guidance)}"
        )
        return title, summary, details

    def _display_name(
        self,
        settings: Settings,
    ) -> str:
        return self._localized_text(settings)["display_name"]

    def localized_display_name(
        self,
        settings: Settings,
    ) -> str:
        """Return a localized display name for runner-generated messages."""
        return self._display_name(settings)

    def _regime_label(
        self,
        regime: str,
        settings: Settings,
    ) -> str:
        return self._localized_text(settings)[f"regime_{regime}"]

    def _signal_label(
        self,
        signal: str,
        settings: Settings,
    ) -> str:
        return self._localized_text(settings)[f"signal_{signal}"]

    def _guidance_for_regime(
        self,
        regime: str,
        settings: Settings,
    ) -> str:
        return self._localized_text(settings)[f"guidance_{regime}"]

    def _localized_text(
        self,
        settings: Settings,
    ) -> dict[str, str]:
        language = settings.report_language.strip().lower()
        return self._LOCALIZED_TEXT.get(language, self._LOCALIZED_TEXT["en"])


def build_btc_realized_pl_ratio_90d_runner() -> MonitorRunner:
    """Build a runner configured with only the BTC realized P/L ratio SMA90 factor."""
    settings = Settings(enabled_factors=["btc_realized_pl_ratio_90d"])
    notifier = ConsoleBarkNotifier(
        bark_server=settings.bark_server,
        bark_device_key=settings.bark_device_key,
        report_format=settings.report_format,
        timeout_seconds=settings.glassnode_http_timeout_seconds,
    )
    return MonitorRunner(
        factors=[BTCRealizedPLRatio90DFactor()],
        settings=settings,
        notifier=notifier,
    )


def run_once() -> None:
    """Run the BTC realized P/L ratio SMA90 factor immediately."""
    build_btc_realized_pl_ratio_90d_runner().run_once(
        factor_names=["btc_realized_pl_ratio_90d"],
        force=True,
    )


def run_monitor() -> None:
    """Start the shared monitoring loop with only the BTC realized P/L ratio SMA90 factor."""
    build_btc_realized_pl_ratio_90d_runner().run_forever(
        factor_names=["btc_realized_pl_ratio_90d"],
    )


if __name__ == "__main__":
    run_once()
