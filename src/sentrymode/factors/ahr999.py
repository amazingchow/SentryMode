"""AHR999 factor implementation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo

import httpx

from sentrymode.monitoring import (
    ConsoleBarkNotifier,
    FactorResult,
    MonitorContext,
    MonitorRunner,
    Settings,
    Severity,
)


@dataclass(slots=True)
class AHR999Factor:
    """Monitor factor for BTC AHR999."""

    _LOCALIZED_TEXT = {
        "en": {
            "display_name": "BTC AHR999",
            "title_evaluated": "evaluated",
            "summary_template": "AHR999={ahr999:.4f}, BTC=${current_price:,.2f}",
            "details_price": "Current BTC price: ${value:,.2f}",
            "details_gma200": "200-day geometric mean cost: ${value:,.2f}",
            "details_estimated": "Fitted valuation price: ${value:,.2f}",
            "details_ahr999": "AHR999: {value:.4f}",
            "details_strategy": "Strategy: {value}",
            "strategy_deep_value": "Accumulate aggressively. The market looks materially undervalued.",
            "strategy_dca": "DCA zone. Price looks reasonable for disciplined accumulation.",
            "strategy_caution": "Observe cautiously. Price is elevated, so consider slowing buys.",
            "strategy_take_profit": "Take-profit zone. Price appears euphoric and may justify phased exits.",
        },
        "zh": {
            "display_name": "BTC AHR999",
            "title_evaluated": "评估完成",
            "summary_template": "AHR999={ahr999:.4f}，BTC=${current_price:,.2f}",
            "details_price": "当前 BTC 价格: ${value:,.2f}",
            "details_gma200": "200 日几何均价成本: ${value:,.2f}",
            "details_estimated": "拟合估值价格: ${value:,.2f}",
            "details_ahr999": "AHR999: {value:.4f}",
            "details_strategy": "策略建议: {value}",
            "strategy_deep_value": "积极分批买入，市场明显处于低估区间。",
            "strategy_dca": "适合定投，价格仍处于相对合理区间。",
            "strategy_caution": "偏高观察区，建议放缓买入并提高警惕。",
            "strategy_take_profit": "高风险兑现区，可考虑分批止盈或降低风险暴露。",
        },
    }

    name: str = "ahr999"
    display_name: str = "BTC AHR999"

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Evaluate once per configured day/time unless forced."""
        if context.force_run:
            return True

        timezone = self._get_ahr_timezone(context.settings)
        local_now = context.now.astimezone(timezone)

        if local_now.hour != context.settings.ahr_run_hour or local_now.minute != context.settings.ahr_run_minute:
            return False

        last_run = context.last_run_for(self.name)
        if last_run is None:
            return True

        return last_run.astimezone(timezone).date() != local_now.date()

    def evaluate(
        self,
        context: MonitorContext,
    ) -> FactorResult:
        """Run the full AHR999 evaluation."""
        timezone = self._get_ahr_timezone(context.settings)
        current_date = context.now.astimezone(timezone).date()
        closes = self._fetch_bitcoin_data_from_kraken(settings=context.settings)
        ahr999, current_price, gma200, estimated_price = self._calculate_ahr999(
            closes=closes,
            settings=context.settings,
            today=current_date,
        )
        strategy, severity = self._classify_ahr999(ahr999, context.settings)
        summary, details = self._build_ahr999_message(
            ahr999=ahr999,
            current_price=current_price,
            gma200=gma200,
            estimated_price=estimated_price,
            strategy=strategy,
            settings=context.settings,
        )
        display_name = self._display_name(context.settings)

        return FactorResult(
            factor_name=self.name,
            display_name=display_name,
            severity=severity,
            title=f"{display_name} {self._localized_text(context.settings)['title_evaluated']}",
            summary=summary,
            details=details,
            metrics={
                "ahr999": round(ahr999, 4),
                "btc_price": round(current_price, 2),
                "gma200": round(gma200, 2),
                "estimated_price": round(estimated_price, 2),
            },
        )

    def _get_ahr_timezone(
        self,
        settings: Settings,
    ) -> ZoneInfo:
        """Return the configured timezone for AHR999 scheduling."""
        return ZoneInfo(settings.ahr_run_timezone)

    def _fetch_bitcoin_data_from_kraken(
        self,
        settings: Settings | None = None,
    ) -> list[float]:
        """Fetch the recent BTC daily closes from Kraken."""
        runtime_settings = settings or Settings()
        params = {
            "pair": runtime_settings.ahr_kraken_pair,
            "interval": runtime_settings.ahr_kraken_interval_minutes,
        }

        response = httpx.get(
            runtime_settings.ahr_kraken_api_url,
            params=params,
            timeout=runtime_settings.ahr_http_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("error"):
            raise RuntimeError(f"Kraken API error: {data['error']}")

        result = data.get("result", {})
        pair_key = next((key for key in result if key != "last"), None)
        if pair_key is None:
            raise RuntimeError("Kraken response does not contain OHLC data.")

        klines = result[pair_key]
        return [float(kline[4]) for kline in klines[-runtime_settings.ahr_lookback_days :]]

    def _calculate_ahr999(
        self,
        closes: list[float],
        settings: Settings | None = None,
        today: date | None = None,
    ) -> tuple[float, float, float, float]:
        """Calculate AHR999, current price, GMA200, and estimated price."""
        runtime_settings = settings or Settings()
        closes = [price for price in closes if price and price > 0]
        if len(closes) < runtime_settings.ahr_lookback_days:
            raise ValueError(
                f"Effective close price data must contain at least {runtime_settings.ahr_lookback_days} days.",
            )

        current_price = closes[-1]
        gma200 = math.exp(sum(math.log(price) for price in closes) / len(closes))
        valuation_date = today or date.today()
        age_days = (valuation_date - runtime_settings.ahr_genesis_date).days
        estimated_price = 10 ** (runtime_settings.ahr_fit_a * math.log10(age_days) - runtime_settings.ahr_fit_b)
        ahr999 = (current_price / gma200) * (current_price / estimated_price)

        return ahr999, current_price, gma200, estimated_price

    def _classify_ahr999(
        self,
        ahr999: float,
        settings: Settings,
    ) -> tuple[str, Severity]:
        """Map an AHR999 value to a human-readable strategy and severity."""
        text = self._localized_text(settings)
        if ahr999 < 0.45:
            return (
                text["strategy_deep_value"],
                Severity.WARNING,
            )
        if ahr999 <= 1.2:
            return (
                text["strategy_dca"],
                Severity.INFO,
            )
        if ahr999 <= 5.0:
            return (
                text["strategy_caution"],
                Severity.WARNING,
            )
        return (
            text["strategy_take_profit"],
            Severity.CRITICAL,
        )

    def _build_ahr999_message(
        self,
        *,
        ahr999: float,
        current_price: float,
        gma200: float,
        estimated_price: float,
        strategy: str,
        settings: Settings,
    ) -> tuple[str, str]:
        """Build compact summary and detailed report content for AHR999."""
        text = self._localized_text(settings)
        summary = text["summary_template"].format(
            ahr999=ahr999,
            current_price=current_price,
        )
        details = (
            f"- {text['details_price'].format(value=current_price)}\n"
            f"- {text['details_gma200'].format(value=gma200)}\n"
            f"- {text['details_estimated'].format(value=estimated_price)}\n"
            f"- {text['details_ahr999'].format(value=ahr999)}\n"
            f"- {text['details_strategy'].format(value=strategy)}"
        )
        return summary, details

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


def build_ahr999_runner() -> MonitorRunner:
    """Build a runner configured with only the AHR999 factor."""
    settings = Settings(enabled_factors=["ahr999"])
    notifier = ConsoleBarkNotifier(
        bark_server=settings.bark_server,
        bark_device_key=settings.bark_device_key,
        report_format=settings.report_format,
        timeout_seconds=settings.ahr_http_timeout_seconds,
    )
    return MonitorRunner(
        factors=[AHR999Factor()],
        settings=settings,
        notifier=notifier,
    )


def run_once() -> None:
    """Run the AHR999 factor immediately."""
    build_ahr999_runner().run_once(factor_names=["ahr999"], force=True)


def run_monitor() -> None:
    """Start the shared monitoring loop with only the AHR999 factor."""
    build_ahr999_runner().run_forever(factor_names=["ahr999"])


if __name__ == "__main__":
    run_once()
