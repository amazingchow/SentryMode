"""
VIX risk-light regime factor.

[INPUT]: `MonitorContext` + aligned daily VIX/SPY series from `DailySeriesProvider`.
[OUTPUT]: `FactorResult` with regime classification, allocation guidance, and summary metrics.
[POS]: Concrete factor plugin in `sentrymode.factors`.
       Upstream: factor registry + `MonitorRunner`.
       Downstream: `sentrymode.market_data` provider seam and monitoring result contracts.

[PROTOCOL]:
1. Keep data loading via provider abstraction to preserve testability and backend swap support.
   The default provider is `YahooSeriesProvider` for both VIX and SPY daily closes.
2. Preserve deterministic regime rules in `_classify_regime`; tune thresholds through `Settings`.
3. Validate historical depth before calculations; fail fast on malformed or insufficient data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from zoneinfo import ZoneInfo

from sentrymode.market_data import DailyBar, DailySeriesProvider, YahooSeriesProvider
from sentrymode.monitoring import (
    ConsoleBarkNotifier,
    FactorResult,
    MonitorContext,
    MonitorRunner,
    Settings,
    Severity,
)


@dataclass(slots=True)
class VIXFactor:
    """Risk-light factor driven by VIX and SPY confirmation."""

    _LOCALIZED_TEXT = {
        "en": {
            "display_name": "VIX Risk Light",
            "title_prefix": "VIX risk light",
            "summary_template": "{regime} | target allocation {allocation}",
            "details_allocation": "Allocation guidance: {value}",
            "details_interpretation": "Interpretation: {value}",
            "details_vix": "VIX close={close:.2f}, SMA10={sma:.2f}, ROC10={roc:.2%}",
            "details_spy": "SPY close={close:.2f}, SMA20={sma:.2f}, below_SMA20={below}",
            "details_confirmation": "Two-day above SMA10={above}, recent VIX spike={spike}",
            "regime_green": "green",
            "regime_yellow": "yellow",
            "regime_red": "red",
            "regime_blue": "blue",
            "regime_neutral": "neutral",
            "guidance_green": "Risk appetite is healthy. Favor trend-following and active long exposure.",
            "guidance_yellow": "Defense alert. Stop opening new risk and tighten existing positions.",
            "guidance_red": "Panic regime. Prioritize capital preservation and avoid bottom-fishing.",
            "guidance_blue": "Peak fear is cooling. Rebuild exposure gradually instead of all at once.",
            "guidance_neutral": "No clear risk-light signal. Maintain observation and avoid forced allocation changes.",
            "allocation_neutral": "observe",
        },
        "zh": {
            "display_name": "VIX 风险红绿灯",
            "title_prefix": "VIX 风险红绿灯",
            "summary_template": "{regime} | 建议仓位 {allocation}",
            "details_allocation": "仓位建议: {value}",
            "details_interpretation": "市场解读: {value}",
            "details_vix": "VIX 收盘={close:.2f}，SMA10={sma:.2f}，ROC10={roc:.2%}",
            "details_spy": "SPY 收盘={close:.2f}，SMA20={sma:.2f}，低于 SMA20={below}",
            "details_confirmation": "连续两日站上 SMA10={above}，近期 VIX 尖峰={spike}",
            "regime_green": "绿灯",
            "regime_yellow": "黄灯",
            "regime_red": "红灯",
            "regime_blue": "蓝灯",
            "regime_neutral": "中性",
            "guidance_green": "风险偏好健康，可偏进攻，适合顺势和主动做多。",
            "guidance_yellow": "防守预警，停止开新高风险仓位并收紧已有仓位。",
            "guidance_red": "恐慌阶段，以控制回撤和保留现金为主，避免抄底。",
            "guidance_blue": "恐慌回落，可分批逐步恢复仓位，但不宜一次性加满。",
            "guidance_neutral": "当前没有清晰的红绿灯信号，保持观察即可。",
            "allocation_neutral": "观察",
        },
    }

    provider: DailySeriesProvider = field(default_factory=YahooSeriesProvider)
    name: str = "vix"
    display_name: str = "VIX Risk Light"

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Evaluate once per configured post-close window unless forced."""
        if context.force_run:
            return True

        timezone = self._get_vix_timezone(context.settings)
        local_now = context.now.astimezone(timezone)
        if local_now.hour != context.settings.vix_run_hour or local_now.minute != context.settings.vix_run_minute:
            return False

        last_run = context.last_run_for(self.name)
        if last_run is None:
            return True

        return last_run.astimezone(timezone).date() != local_now.date()

    def evaluate(
        self,
        context: MonitorContext,
    ) -> FactorResult:
        """Evaluate the current VIX regime and return a structured result."""
        vix_bars = self.provider.get_series("vix", context.settings)
        spy_bars = self.provider.get_series("spy", context.settings)
        aligned_vix_bars, aligned_spy_bars = self._align_series(vix_bars, spy_bars)

        signals = self._calculate_signals(aligned_vix_bars, aligned_spy_bars, context.settings)
        regime = self._classify_regime(signals, context.settings)
        severity = self._severity_for_regime(regime)
        title, summary, details = self._build_message(regime, signals, context.settings)
        display_name = self._display_name(context.settings)

        return FactorResult(
            factor_name=self.name,
            display_name=display_name,
            severity=severity,
            title=title,
            summary=summary,
            details=details,
            metrics={
                "regime": regime,
                "vix_close": round(signals["vix_close"], 2),
                "vix_sma10": round(signals["vix_sma10"], 2),
                "vix_roc10": round(signals["vix_roc10"], 4),
                "spy_close": round(signals["spy_close"], 2),
                "spy_sma20": round(signals["spy_sma20"], 2),
            },
        )

    def _get_vix_timezone(
        self,
        settings: Settings,
    ) -> ZoneInfo:
        return ZoneInfo(settings.vix_run_timezone)

    def _align_series(
        self,
        vix_bars: list[DailyBar],
        spy_bars: list[DailyBar],
    ) -> tuple[list[DailyBar], list[DailyBar]]:
        spy_by_date = {bar.date: bar for bar in spy_bars}
        common_dates = sorted({bar.date for bar in vix_bars} & set(spy_by_date))
        if not common_dates:
            raise ValueError("VIX and SPY daily series do not share any common trading dates.")

        aligned_vix = [bar for bar in vix_bars if bar.date in spy_by_date]
        aligned_spy = [spy_by_date[bar.date] for bar in aligned_vix]
        return aligned_vix, aligned_spy

    def _calculate_signals(
        self,
        vix_bars: list[DailyBar],
        spy_bars: list[DailyBar],
        settings: Settings,
    ) -> dict[str, float | bool]:
        required_points = max(
            settings.vix_lookback_days,
            settings.vix_sma_window + settings.vix_two_day_confirmation - 1,
            settings.vix_roc_window + 1,
            settings.spy_sma_window,
        )
        if len(vix_bars) < required_points or len(spy_bars) < required_points:
            raise ValueError(f"VIX factor requires at least {required_points} aligned trading days of history.")

        vix_closes = [bar.close for bar in vix_bars[-settings.vix_lookback_days :]]
        spy_closes = [bar.close for bar in spy_bars[-settings.vix_lookback_days :]]

        current_vix = vix_closes[-1]
        previous_vix = vix_closes[-2]
        current_vix_sma = self._simple_moving_average(vix_closes, settings.vix_sma_window)
        previous_vix_sma = self._simple_moving_average(
            vix_closes[:-1],
            settings.vix_sma_window,
        )
        current_roc = self._rate_of_change(vix_closes, settings.vix_roc_window)
        current_spy = spy_closes[-1]
        current_spy_sma = self._simple_moving_average(spy_closes, settings.spy_sma_window)

        return {
            "vix_close": current_vix,
            "vix_prev_close": previous_vix,
            "vix_sma10": current_vix_sma,
            "vix_prev_sma10": previous_vix_sma,
            "vix_roc10": current_roc,
            "spy_close": current_spy,
            "spy_sma20": current_spy_sma,
            "spy_below_sma20": current_spy < current_spy_sma,
            "two_day_above_sma10": self._closed_above_sma_for_days(
                vix_closes,
                settings.vix_sma_window,
                settings.vix_two_day_confirmation,
            ),
            "recent_vix_spike": max(vix_closes[-settings.vix_sma_window :]) > settings.vix_blue_spike_min,
        }

    def _classify_regime(
        self,
        signals: dict[str, float | bool],
        settings: Settings,
    ) -> str:
        vix_close = float(signals["vix_close"])
        vix_sma = float(signals["vix_sma10"])
        vix_prev_close = float(signals["vix_prev_close"])
        vix_prev_sma = float(signals["vix_prev_sma10"])
        vix_roc = float(signals["vix_roc10"])
        spy_below_sma20 = bool(signals["spy_below_sma20"])
        two_day_above_sma10 = bool(signals["two_day_above_sma10"])
        recent_vix_spike = bool(signals["recent_vix_spike"])

        if recent_vix_spike and vix_close < vix_sma and vix_prev_close >= vix_prev_sma:
            return "blue"

        if (
            vix_close > settings.vix_red_min
            and vix_close > vix_sma
            and vix_roc > settings.vix_roc_red_threshold
            and spy_below_sma20
        ):
            return "red"

        if (
            settings.vix_yellow_min <= vix_close <= settings.vix_red_min
            and (two_day_above_sma10 or vix_roc > settings.vix_roc_yellow_threshold)
            and spy_below_sma20
        ):
            return "yellow"

        if vix_close < settings.vix_green_max and vix_close < vix_sma:
            return "green"

        return "neutral"

    def _severity_for_regime(
        self,
        regime: str,
    ) -> Severity:
        if regime == "yellow":
            return Severity.WARNING
        if regime == "red":
            return Severity.CRITICAL
        return Severity.INFO

    def _build_message(
        self,
        regime: str,
        signals: dict[str, float | bool],
        settings: Settings,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        regime_name, allocation, guidance = self._regime_guidance(regime, settings)
        title = f"{text['title_prefix']}: {regime_name}"
        summary = text["summary_template"].format(regime=regime_name, allocation=allocation)
        details = (
            f"- {text['details_allocation'].format(value=allocation)}\n"
            f"- {text['details_interpretation'].format(value=guidance)}\n"
            f"- {text['details_vix'].format(close=float(signals['vix_close']), sma=float(signals['vix_sma10']), roc=float(signals['vix_roc10']))}\n"
            f"- {text['details_spy'].format(close=float(signals['spy_close']), sma=float(signals['spy_sma20']), below=bool(signals['spy_below_sma20']))}\n"
            f"- {text['details_confirmation'].format(above=bool(signals['two_day_above_sma10']), spike=bool(signals['recent_vix_spike']))}"
        )
        return title, summary, details

    def _regime_guidance(
        self,
        regime: str,
        settings: Settings,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        if regime == "green":
            return (
                text["regime_green"],
                "80%-100%",
                text["guidance_green"],
            )
        if regime == "yellow":
            return (
                text["regime_yellow"],
                "50%-60%",
                text["guidance_yellow"],
            )
        if regime == "red":
            return (
                text["regime_red"],
                "0%-30%",
                text["guidance_red"],
            )
        if regime == "blue":
            return (
                text["regime_blue"],
                "30% -> 60% -> 80%",
                text["guidance_blue"],
            )
        return (
            text["regime_neutral"],
            text["allocation_neutral"],
            text["guidance_neutral"],
        )

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

    def _localized_text(
        self,
        settings: Settings,
    ) -> dict[str, str]:
        language = settings.report_language.strip().lower()
        return self._LOCALIZED_TEXT.get(language, self._LOCALIZED_TEXT["en"])

    def _closed_above_sma_for_days(
        self,
        closes: list[float],
        sma_window: int,
        days: int,
    ) -> bool:
        if len(closes) < sma_window + days - 1:
            return False

        for index in range(len(closes) - days, len(closes)):
            rolling_window = closes[index - sma_window + 1 : index + 1]
            if closes[index] <= mean(rolling_window):
                return False
        return True

    def _simple_moving_average(
        self,
        closes: list[float],
        window: int,
    ) -> float:
        if len(closes) < window:
            raise ValueError(f"Need at least {window} closes to compute SMA.")
        return mean(closes[-window:])

    def _rate_of_change(
        self,
        closes: list[float],
        window: int,
    ) -> float:
        if len(closes) <= window:
            raise ValueError(f"Need more than {window} closes to compute ROC.")
        base_value = closes[-window - 1]
        if base_value <= 0:
            raise ValueError("ROC base value must be positive.")
        return (closes[-1] - base_value) / base_value


def build_vix_runner() -> MonitorRunner:
    """Build a runner configured with only the VIX factor."""
    settings = Settings(enabled_factors=["vix"])
    notifier = ConsoleBarkNotifier(
        bark_server=settings.bark_server,
        bark_device_key=settings.bark_device_key,
        report_format=settings.report_format,
        timeout_seconds=settings.vix_http_timeout_seconds,
    )
    return MonitorRunner(
        factors=[VIXFactor()],
        settings=settings,
        notifier=notifier,
    )


def run_once() -> None:
    """Run the VIX factor immediately."""
    build_vix_runner().run_once(factor_names=["vix"], force=True)


def run_monitor() -> None:
    """Start the shared monitoring loop with only the VIX factor."""
    build_vix_runner().run_forever(factor_names=["vix"])


if __name__ == "__main__":
    run_once()
