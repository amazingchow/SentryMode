"""
US10Y dual-moving-average trend factor.

[INPUT]: `MonitorContext` + daily US10Y/VIX/SPY series from `DailySeriesProvider`.
[OUTPUT]: `FactorResult` with state-machine regime, allocation guidance, and black-swan overlay.
[POS]: Concrete factor plugin in `sentrymode.factors`.
       Upstream: factor registry + `MonitorRunner`.
       Downstream: `sentrymode.market_data` provider seam and local JSON state snapshot.

[PROTOCOL]:
1. Keep deterministic regime transitions in `_advance_state` and persistence in dedicated helpers.
2. Preserve state continuity across process restarts through `us10y_state_file` JSON snapshots.
3. Treat persistence corruption/failure as recoverable and keep factor evaluation running.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean
from typing import Literal
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

Regime = Literal["green", "yellow", "red"]


@dataclass(slots=True, frozen=True)
class _StateSnapshot:
    """Persisted US10Y state-machine snapshot."""

    state: Regime
    as_of_date: date
    streak_above_green: int
    streak_above_red: int
    streak_below_red_and_sma: int
    streak_below_green_and_neg_roc: int


@dataclass(slots=True)
class US10YFactor:
    """US10Y trend factor with confirmed state transitions."""

    _LOCALIZED_TEXT = {
        "en": {
            "display_name": "US10Y Dual-MA Trend",
            "title_prefix": "US10Y trend light",
            "summary_template": "{regime} | target allocation {allocation}",
            "details_allocation": "Allocation guidance: {value}",
            "details_interpretation": "Interpretation: {value}",
            "details_us10y": "US10Y close={close:.2f}%, SMA20={sma:.2f}%, ROC10={roc:.2%}",
            "details_spy": "SPY close={close:.2f}, SMA20={sma:.2f}, below_SMA20={below}",
            "details_vix": "VIX close={close:.2f}, threshold>{threshold:.2f}",
            "details_state": "State transition: {previous} -> {current}",
            "details_confirmation": "Confirm streaks (up4.0={up4}, up4.5={up45}, down4.5+SMA={down45sma}, down4.0+ROC<0={down4roc})",
            "details_black_swan": "Black swan overlay: {active}",
            "details_recovery": "State recovery note: {message}",
            "details_persist_warning": "State persistence warning: {message}",
            "regime_green": "green",
            "regime_yellow": "yellow",
            "regime_red": "red",
            "guidance_green": "Liquidity is supportive. Keep proactive long exposure.",
            "guidance_yellow": "Valuation pressure zone. Reduce high-beta risk and stay selective.",
            "guidance_yellow_flashing": "Yield is rising quickly. Tighten risk and cut exposure further.",
            "guidance_red": "Risk-free yield dominates. Keep defensive posture and preserve capital.",
            "guidance_black_swan": "Equity-bond stress signal detected. Move to max defense immediately.",
            "black_swan_active": "YES",
            "black_swan_inactive": "NO",
        },
        "zh": {
            "display_name": "US10Y 双均线趋势",
            "title_prefix": "US10Y 风险红绿灯",
            "summary_template": "{regime} | 建议仓位 {allocation}",
            "details_allocation": "仓位建议: {value}",
            "details_interpretation": "市场解读: {value}",
            "details_us10y": "US10Y 收盘={close:.2f}%，SMA20={sma:.2f}%，ROC10={roc:.2%}",
            "details_spy": "SPY 收盘={close:.2f}，SMA20={sma:.2f}，低于 SMA20={below}",
            "details_vix": "VIX 收盘={close:.2f}，阈值>{threshold:.2f}",
            "details_state": "状态转换: {previous} -> {current}",
            "details_confirmation": "确认计数 (连涨破4.0={up4}, 连涨破4.5={up45}, 连跌4.5且破均线={down45sma}, 连跌4.0且ROC<0={down4roc})",
            "details_black_swan": "黑天鹅叠加信号: {active}",
            "details_recovery": "状态恢复提示: {message}",
            "details_persist_warning": "状态持久化警告: {message}",
            "regime_green": "绿灯",
            "regime_yellow": "黄灯",
            "regime_red": "红灯",
            "guidance_green": "流动性环境友好，可维持进攻型仓位。",
            "guidance_yellow": "估值压力区，降低高 Beta 风险并偏向高质量资产。",
            "guidance_yellow_flashing": "收益率加速上行，需进一步降仓并强化防守。",
            "guidance_red": "无风险收益率吸引力高，优先防守和保留现金。",
            "guidance_black_swan": "股债双杀信号触发，建议立即进入最高级防守。",
            "black_swan_active": "是",
            "black_swan_inactive": "否",
        },
    }

    provider: DailySeriesProvider = field(default_factory=YahooSeriesProvider)
    name: str = "us10y"
    display_name: str = "US10Y Dual-MA Trend"

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Evaluate once per configured day/time unless forced."""
        if context.force_run:
            return True

        timezone = self._get_us10y_timezone(context.settings)
        local_now = context.now.astimezone(timezone)
        if local_now.hour != context.settings.us10y_run_hour or local_now.minute != context.settings.us10y_run_minute:
            return False

        last_run = context.last_run_for(self.name)
        if last_run is None:
            return True

        return last_run.astimezone(timezone).date() != local_now.date()

    def evaluate(
        self,
        context: MonitorContext,
    ) -> FactorResult:
        """Evaluate US10Y trend state and emit a structured monitoring result."""
        us10y_bars = self.provider.get_series("us10y", context.settings)
        vix_bars = self.provider.get_series("vix", context.settings)
        spy_bars = self.provider.get_series("spy", context.settings)
        signals = self._calculate_signals(us10y_bars, vix_bars, spy_bars, context.settings)

        snapshot, recovery_note = self._load_state(context.settings)
        previous_state = (
            snapshot.state if snapshot is not None else self._base_regime(signals["us10y_close"], context.settings)
        )
        current_state = self._advance_state(previous_state, signals, context.settings)

        black_swan = self._is_black_swan(current_state, signals, context.settings)
        title, summary, details = self._build_message(
            previous_state=previous_state,
            current_state=current_state,
            black_swan=black_swan,
            signals=signals,
            settings=context.settings,
            recovery_note=recovery_note,
        )

        persist_warning = self._persist_state(
            settings=context.settings,
            snapshot=_StateSnapshot(
                state=current_state,
                as_of_date=signals["as_of_date"],
                streak_above_green=signals["streak_above_green"],
                streak_above_red=signals["streak_above_red"],
                streak_below_red_and_sma=signals["streak_below_red_and_sma"],
                streak_below_green_and_neg_roc=signals["streak_below_green_and_neg_roc"],
            ),
        )
        if persist_warning:
            details = f"{details}\n- {self._localized_text(context.settings)['details_persist_warning'].format(message=persist_warning)}"

        display_name = self._display_name(context.settings)
        return FactorResult(
            factor_name=self.name,
            display_name=display_name,
            severity=self._severity_for(current_state, black_swan),
            title=title,
            summary=summary,
            details=details,
            metrics={
                "regime": current_state,
                "black_swan": str(black_swan).lower(),
                "us10y_close": round(signals["us10y_close"], 4),
                "us10y_sma20": round(signals["us10y_sma20"], 4),
                "us10y_roc10": round(signals["us10y_roc10"], 6),
                "vix_close": round(signals["vix_close"], 4),
                "spy_close": round(signals["spy_close"], 4),
                "spy_sma20": round(signals["spy_sma20"], 4),
            },
        )

    def _get_us10y_timezone(
        self,
        settings: Settings,
    ) -> ZoneInfo:
        return ZoneInfo(settings.us10y_run_timezone)

    def _calculate_signals(
        self,
        us10y_bars: list[DailyBar],
        vix_bars: list[DailyBar],
        spy_bars: list[DailyBar],
        settings: Settings,
    ) -> dict[str, float | int | bool | date]:
        required_us10y_points = max(
            settings.us10y_lookback_days,
            settings.us10y_sma_window,
            settings.us10y_roc_window + settings.us10y_down_confirm_days,
        )
        if len(us10y_bars) < required_us10y_points:
            raise ValueError(f"US10Y factor requires at least {required_us10y_points} daily points.")
        if len(vix_bars) < 1:
            raise ValueError("US10Y factor requires at least one VIX daily point.")
        if len(spy_bars) < settings.us10y_spy_sma_window:
            raise ValueError(
                f"US10Y factor requires at least {settings.us10y_spy_sma_window} SPY daily points.",
            )

        us10y_closes = [bar.close for bar in us10y_bars[-settings.us10y_lookback_days :]]
        spy_closes = [bar.close for bar in spy_bars]

        us10y_close = us10y_closes[-1]
        us10y_sma = self._simple_moving_average(us10y_closes, settings.us10y_sma_window)
        us10y_roc = self._rate_of_change(us10y_closes, settings.us10y_roc_window)
        vix_close = vix_bars[-1].close
        spy_close = spy_closes[-1]
        spy_sma = self._simple_moving_average(spy_closes, settings.us10y_spy_sma_window)

        return {
            "as_of_date": us10y_bars[-1].date,
            "us10y_close": us10y_close,
            "us10y_sma20": us10y_sma,
            "us10y_roc10": us10y_roc,
            "vix_close": vix_close,
            "spy_close": spy_close,
            "spy_sma20": spy_sma,
            "spy_below_sma20": spy_close < spy_sma,
            "yellow_flashing": us10y_close > us10y_sma and us10y_roc > settings.us10y_roc_warning_threshold,
            "streak_above_green": self._count_streak(
                us10y_closes, lambda value,: value >= settings.us10y_green_threshold
            ),
            "streak_above_red": self._count_streak(us10y_closes, lambda value,: value >= settings.us10y_red_threshold),
            "streak_below_red_and_sma": self._count_streak_below_red_and_sma(us10y_closes, settings),
            "streak_below_green_and_neg_roc": self._count_streak_below_green_and_negative_roc(us10y_closes, settings),
        }

    def _advance_state(
        self,
        previous_state: Regime,
        signals: dict[str, float | int | bool | date],
        settings: Settings,
    ) -> Regime:
        streak_up_green = int(signals["streak_above_green"])
        streak_up_red = int(signals["streak_above_red"])
        streak_down_red_sma = int(signals["streak_below_red_and_sma"])
        streak_down_green_roc = int(signals["streak_below_green_and_neg_roc"])

        if previous_state == "green" and streak_up_green >= settings.us10y_up_confirm_days:
            return "yellow"
        if previous_state == "yellow" and streak_up_red >= settings.us10y_up_confirm_days:
            return "red"
        if previous_state == "red" and streak_down_red_sma >= settings.us10y_down_confirm_days:
            return "yellow"
        if previous_state == "yellow" and streak_down_green_roc >= settings.us10y_down_confirm_days:
            return "green"
        return previous_state

    def _is_black_swan(
        self,
        regime: Regime,
        signals: dict[str, float | int | bool | date],
        settings: Settings,
    ) -> bool:
        return (
            regime == "red"
            and float(signals["us10y_roc10"]) > settings.us10y_roc_warning_threshold
            and float(signals["vix_close"]) > settings.us10y_black_swan_vix_threshold
            and bool(signals["spy_below_sma20"])
        )

    def _severity_for(
        self,
        regime: Regime,
        black_swan: bool,
    ) -> Severity:
        if black_swan:
            return Severity.CRITICAL
        if regime == "yellow":
            return Severity.WARNING
        if regime == "red":
            return Severity.CRITICAL
        return Severity.INFO

    def _build_message(
        self,
        *,
        previous_state: Regime,
        current_state: Regime,
        black_swan: bool,
        signals: dict[str, float | int | bool | date],
        settings: Settings,
        recovery_note: str | None,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        regime_name, allocation, guidance = self._regime_guidance(current_state, signals, settings)
        if black_swan:
            allocation = "0%"
            guidance = text["guidance_black_swan"]

        title = f"{text['title_prefix']}: {regime_name}"
        summary = text["summary_template"].format(regime=regime_name, allocation=allocation)

        black_swan_label_key = "black_swan_active" if black_swan else "black_swan_inactive"
        details_lines = [
            f"- {text['details_allocation'].format(value=allocation)}",
            f"- {text['details_interpretation'].format(value=guidance)}",
            f"- {text['details_state'].format(previous=self._regime_name(previous_state, settings), current=regime_name)}",
            f"- {text['details_us10y'].format(close=float(signals['us10y_close']), sma=float(signals['us10y_sma20']), roc=float(signals['us10y_roc10']))}",
            f"- {text['details_vix'].format(close=float(signals['vix_close']), threshold=settings.us10y_black_swan_vix_threshold)}",
            f"- {text['details_spy'].format(close=float(signals['spy_close']), sma=float(signals['spy_sma20']), below=bool(signals['spy_below_sma20']))}",
            (
                "- "
                + text["details_confirmation"].format(
                    up4=int(signals["streak_above_green"]),
                    up45=int(signals["streak_above_red"]),
                    down45sma=int(signals["streak_below_red_and_sma"]),
                    down4roc=int(signals["streak_below_green_and_neg_roc"]),
                )
            ),
            f"- {text['details_black_swan'].format(active=text[black_swan_label_key])}",
        ]
        if recovery_note:
            details_lines.append(f"- {text['details_recovery'].format(message=recovery_note)}")

        return title, summary, "\n".join(details_lines)

    def _regime_guidance(
        self,
        regime: Regime,
        signals: dict[str, float | int | bool | date],
        settings: Settings,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        if regime == "green":
            return text["regime_green"], "80%-100%", text["guidance_green"]
        if regime == "yellow":
            if bool(signals["yellow_flashing"]):
                return text["regime_yellow"], "40%-50%", text["guidance_yellow_flashing"]
            return text["regime_yellow"], "50%-70%", text["guidance_yellow"]
        return text["regime_red"], "0%-30%", text["guidance_red"]

    def _base_regime(
        self,
        us10y_close: float,
        settings: Settings,
    ) -> Regime:
        if us10y_close >= settings.us10y_red_threshold:
            return "red"
        if us10y_close >= settings.us10y_green_threshold:
            return "yellow"
        return "green"

    def _count_streak(
        self,
        values: list[float],
        predicate,
    ) -> int:
        count = 0
        for value in reversed(values):
            if not predicate(value):
                break
            count += 1
        return count

    def _count_streak_below_red_and_sma(
        self,
        closes: list[float],
        settings: Settings,
    ) -> int:
        count = 0
        for index in range(len(closes) - 1, -1, -1):
            if index < settings.us10y_sma_window - 1:
                break
            sma_value = mean(closes[index - settings.us10y_sma_window + 1 : index + 1])
            if closes[index] < settings.us10y_red_threshold and closes[index] < sma_value:
                count += 1
                continue
            break
        return count

    def _count_streak_below_green_and_negative_roc(
        self,
        closes: list[float],
        settings: Settings,
    ) -> int:
        count = 0
        for index in range(len(closes) - 1, -1, -1):
            if index < settings.us10y_roc_window:
                break
            base_value = closes[index - settings.us10y_roc_window]
            if base_value <= 0:
                break
            roc = (closes[index] - base_value) / base_value
            if closes[index] < settings.us10y_green_threshold and roc < 0:
                count += 1
                continue
            break
        return count

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

    def _load_state(
        self,
        settings: Settings,
    ) -> tuple[_StateSnapshot | None, str | None]:
        path = self._state_file_path(settings)
        if not path.exists():
            return None, None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = payload["state"]
            if state not in ("green", "yellow", "red"):
                raise ValueError(f"Unsupported state value: {state}")
            return (
                _StateSnapshot(
                    state=state,
                    as_of_date=date.fromisoformat(payload["as_of_date"]),
                    streak_above_green=int(payload["streak_above_green"]),
                    streak_above_red=int(payload["streak_above_red"]),
                    streak_below_red_and_sma=int(payload["streak_below_red_and_sma"]),
                    streak_below_green_and_neg_roc=int(payload["streak_below_green_and_neg_roc"]),
                ),
                None,
            )
        except Exception as exc:
            return None, f"invalid state file at {path}: {exc}"

    def _persist_state(
        self,
        *,
        settings: Settings,
        snapshot: _StateSnapshot,
    ) -> str | None:
        path = self._state_file_path(settings)
        payload = {
            "state": snapshot.state,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "streak_above_green": snapshot.streak_above_green,
            "streak_above_red": snapshot.streak_above_red,
            "streak_below_red_and_sma": snapshot.streak_below_red_and_sma,
            "streak_below_green_and_neg_roc": snapshot.streak_below_green_and_neg_roc,
            "updated_at": datetime.now(UTC).isoformat(),
        }

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return None
        except OSError as exc:
            return f"cannot write state file {path}: {exc}"

    def _state_file_path(
        self,
        settings: Settings,
    ) -> Path:
        return Path(settings.us10y_state_file).expanduser()

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

    def _regime_name(
        self,
        regime: Regime,
        settings: Settings,
    ) -> str:
        return self._localized_text(settings)[f"regime_{regime}"]

    def _localized_text(
        self,
        settings: Settings,
    ) -> dict[str, str]:
        language = settings.report_language.strip().lower()
        return self._LOCALIZED_TEXT.get(language, self._LOCALIZED_TEXT["en"])


def build_us10y_runner() -> MonitorRunner:
    """Build a runner configured with only the US10Y factor."""
    settings = Settings(enabled_factors=["us10y"])
    notifier = ConsoleBarkNotifier(
        bark_server=settings.bark_server,
        bark_device_key=settings.bark_device_key,
        report_format=settings.report_format,
        timeout_seconds=settings.vix_http_timeout_seconds,
    )
    return MonitorRunner(
        factors=[US10YFactor()],
        settings=settings,
        notifier=notifier,
    )


def run_once() -> None:
    """Run the US10Y factor immediately."""
    build_us10y_runner().run_once(factor_names=["us10y"], force=True)


def run_monitor() -> None:
    """Start the shared monitoring loop with only the US10Y factor."""
    build_us10y_runner().run_forever(factor_names=["us10y"])


if __name__ == "__main__":
    run_once()
