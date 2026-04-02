"""
AI infrastructure portfolio monitoring factor.

[INPUT]: `MonitorContext` + daily VIX / ETF / equity series from `DailySeriesProvider` and
         optional earnings-calendar lookups from Yahoo Finance.
[OUTPUT]: `FactorResult` with market regime, per-position actions, and portfolio-specific
          risk-control guidance for the AI infrastructure basket.
[POS]: Concrete factor plugin in `sentrymode.factors`.
       Upstream: factor registry + `MonitorRunner`.
       Downstream: `sentrymode.market_data` daily-series seam and yfinance earnings metadata.

[PROTOCOL]:
1. Keep price-history access on the shared `DailySeriesProvider` seam; do not add ad-hoc quote
   fetching inside decision logic.
2. Treat earnings dates as a best-effort overlay: missing metadata should not fail the factor.
3. Preserve deterministic action rules so portfolio alerts stay stable and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

import yfinance

from sentrymode.market_data import DailyBar, DailySeriesProvider, YahooSeriesProvider
from sentrymode.monitoring import FactorResult, MonitorContext, Settings, Severity

MarketRegime = Literal["green", "yellow", "orange", "red", "extreme"]
Action = Literal["build", "add", "pause", "reduce", "exit_watch"]


@dataclass(slots=True, frozen=True)
class _HoldingSpec:
    symbol: str
    target_weight: int
    role_key: str


@dataclass(slots=True, frozen=True)
class _TickerSnapshot:
    symbol: str
    close: float
    sma20: float
    sma50: float
    sma200: float
    prev_close: float
    prev_sma20: float
    prev_sma50: float
    high10: float
    latest_date: date

    @property
    def above_sma20(
        self,
    ) -> bool:
        return self.close >= self.sma20

    @property
    def above_sma50(
        self,
    ) -> bool:
        return self.close >= self.sma50

    @property
    def above_sma200(
        self,
    ) -> bool:
        return self.close >= self.sma200

    @property
    def reclaimed_sma20(
        self,
    ) -> bool:
        return self.close >= self.sma20 and self.prev_close < self.prev_sma20

    @property
    def two_day_below_sma50(
        self,
    ) -> bool:
        return self.close < self.sma50 and self.prev_close < self.prev_sma50

    @property
    def extended_above_sma20(
        self,
    ) -> bool:
        return self.close > self.sma20 * 1.08

    @property
    def at_ten_day_high(
        self,
    ) -> bool:
        return self.close >= self.high10


@dataclass(slots=True, frozen=True)
class _MarketSnapshot:
    regime: MarketRegime
    vix_close: float
    qqq: _TickerSnapshot
    smh: _TickerSnapshot


@dataclass(slots=True, frozen=True)
class _Decision:
    symbol: str
    target_weight: int
    action: Action
    rationale: str
    tranche: str | None
    earnings_note: str | None
    held: bool
    close: float
    sma20: float
    sma50: float
    sma200: float


class EarningsDateProvider(Protocol):
    """Best-effort provider for the next earnings date of a ticker."""

    def get_next_earnings_date(
        self,
        symbol: str,
        *,
        as_of: date,
    ) -> date | None:
        """Return the next earnings date on or after `as_of`, when available."""


class YahooEarningsDateProvider:
    """Load next earnings dates from Yahoo Finance metadata."""

    def get_next_earnings_date(
        self,
        symbol: str,
        *,
        as_of: date,
    ) -> date | None:
        """Return the next known Yahoo earnings date on or after `as_of`."""
        calendar = yfinance.Ticker(symbol).calendar
        candidates = sorted(candidate for candidate in self._extract_dates(calendar) if candidate >= as_of)
        return candidates[0] if candidates else None

    def _extract_dates(
        self,
        payload: object,
    ) -> list[date]:
        if payload is None:
            return []

        direct_date = self._coerce_date(payload)
        if direct_date is not None:
            return [direct_date]

        if isinstance(payload, dict):
            dates: list[date] = []
            for value in payload.values():
                dates.extend(self._extract_dates(value))
            return dates

        if isinstance(payload, (list, tuple, set)):
            dates: list[date] = []
            for value in payload:
                dates.extend(self._extract_dates(value))
            return dates

        to_dict = getattr(payload, "to_dict", None)
        if callable(to_dict):
            return self._extract_dates(to_dict())

        to_list = getattr(payload, "tolist", None)
        if callable(to_list):
            return self._extract_dates(to_list())

        return []

    def _coerce_date(
        self,
        raw_value: object,
    ) -> date | None:
        if isinstance(raw_value, datetime):
            return raw_value.date()
        if isinstance(raw_value, date):
            return raw_value

        to_pydatetime = getattr(raw_value, "to_pydatetime", None)
        if callable(to_pydatetime):
            converted = to_pydatetime()
            if isinstance(converted, datetime):
                return converted.date()

        if isinstance(raw_value, str):
            candidate = raw_value.strip()
            if not candidate:
                return None
            candidate = candidate.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(candidate).date()
            except ValueError:
                return None
        return None


@dataclass(slots=True)
class AIPortfolioFactor:
    """Monitor a fixed AI infrastructure portfolio with daily risk-control actions."""

    _LOCALIZED_TEXT = {
        "en": {
            "display_name": "AI Infrastructure Portfolio",
            "title_prefix": "AI portfolio monitor",
            "summary_template": "{regime} | build={build} add={add} pause={pause} reduce={reduce} | {cash}",
            "market_header": "Market regime",
            "action_header": "Daily actions",
            "manual_review": (
                "Manual review still required for earnings guidance, cloud/data-center commentary, "
                "and ASML policy headlines; this factor automates price, volatility, and earnings-window rules only."
            ),
            "cash_green": "keep cash/T-bills near 15%",
            "cash_yellow": "trial positions only; keep cash/T-bills near 15%",
            "cash_orange": "pause heavy adds; keep cash/T-bills near 15%",
            "cash_red": "cut high-beta risk by 25%-33%",
            "cash_extreme": "raise cash/T-bills toward 35%-40%",
            "regime_green": "green",
            "regime_yellow": "yellow",
            "regime_orange": "orange",
            "regime_red": "red",
            "regime_extreme": "extreme",
            "action_build": "BUILD",
            "action_add": "ADD",
            "action_pause": "PAUSE",
            "action_reduce": "REDUCE",
            "action_exit_watch": "EXIT/WATCH",
            "holding_yes": "held",
            "holding_no": "not held",
            "earnings_in_days": "earnings in {days} day(s)",
            "role_quality": "quality ballast",
            "role_compute": "AI compute leader",
            "role_memory": "HBM / memory lever",
            "role_bottleneck": "equipment bottleneck",
            "role_cloud": "cloud AI right-side entry",
            "role_power": "power diversification",
            "build_tranche": "open 1/3 of target ({weight:.2f}% NAV)",
            "add_tranche": "add 1/3 of target ({weight:.2f}% NAV)",
            "reduce_tranche": "trim 25%-33% of current position",
            "market_template": (
                "VIX={vix:.2f}; QQQ={qqq:.2f} vs SMA20/SMA50/SMA200={qqq20:.2f}/{qqq50:.2f}/{qqq200:.2f}; "
                "SMH={smh:.2f} vs SMA20/SMA50/SMA200={smh20:.2f}/{smh50:.2f}/{smh200:.2f}"
            ),
            "reason_goog_build": "Green/yellow market and GOOG is above SMA50.",
            "reason_goog_orange_build": "Orange regime allows only a small GOOG starter while the stock stays above SMA50.",
            "reason_goog_add": "Trend support held near SMA20/SMA50 while the market is still constructive.",
            "reason_goog_pause": "Wait while GOOG stays below SMA50 or QQQ weakens.",
            "reason_nvda_build": "Only buy NVDA in a green regime and avoid entries >8% above SMA20.",
            "reason_nvda_add": "Green regime plus SMH confirmation and NVDA strength support another tranche.",
            "reason_nvda_pause": "Wait for a green regime and a cleaner NVDA setup.",
            "reason_nvda_reduce": "Two closes below SMA50 or a red/extreme regime calls for de-risking.",
            "reason_mu_build": "MU is above SMA50 and the market is at least yellow.",
            "reason_mu_add": "Trend is intact and MU can scale further with a profitable base.",
            "reason_mu_pause": "Wait for MU back above SMA50 and a healthier SMH tape.",
            "reason_mu_reduce": "MU lost SMA50 while SMH also weakened, so trim risk.",
            "reason_asml_build": "ASML only earns new exposure in a green regime above SMA50.",
            "reason_asml_add": "Green tape plus trend support allows a measured add.",
            "reason_asml_pause": "Pause until the regime turns green again and policy headlines stay calm.",
            "reason_asml_reduce": "Reduce ASML when the market moves to red/extreme risk.",
            "reason_orcl_build": "ORCL should be bought on a right-side reclaim of SMA20 in green/yellow tape.",
            "reason_orcl_add": "Trend reclaimed above SMA20 and the existing position is working.",
            "reason_orcl_pause": "Do not bottom-fish ORCL without a clear right-side reclaim.",
            "reason_orcl_reduce": "Red/extreme risk means protecting cloud-beta exposure first.",
            "reason_nlr_build": "NLR can open only when VIX stays below 22 and the ETF is above SMA50.",
            "reason_nlr_add": "Theme is still trending and market risk is not red.",
            "reason_nlr_pause": "Wait for VIX below 22 and NLR above SMA50.",
            "reason_nlr_reduce": "In red/extreme tape, trim the thematic ETF before core cash-flow names.",
        },
        "zh": {
            "display_name": "AI 基建组合监控",
            "title_prefix": "AI 组合监控",
            "summary_template": "{regime} | 建仓={build} 加仓={add} 暂停={pause} 减仓={reduce} | {cash}",
            "market_header": "市场状态",
            "action_header": "每日动作",
            "manual_review": (
                "财报正文、Cloud/数据中心指引、以及 ASML 政策新闻仍需人工复核；本因子只自动化价格、波动率和财报窗口规则。"
            ),
            "cash_green": "现金/T-Bill 维持约 15%",
            "cash_yellow": "仅允许试单，现金/T-Bill 维持约 15%",
            "cash_orange": "暂停大幅加仓，现金/T-Bill 维持约 15%",
            "cash_red": "高 beta 仓位减 25%-33%",
            "cash_extreme": "现金/T-Bill 提高到 35%-40%",
            "regime_green": "绿灯",
            "regime_yellow": "黄灯",
            "regime_orange": "橙色",
            "regime_red": "红灯",
            "regime_extreme": "极端风控",
            "action_build": "建仓",
            "action_add": "加仓",
            "action_pause": "暂停",
            "action_reduce": "减仓",
            "action_exit_watch": "清仓观察",
            "holding_yes": "已持有",
            "holding_no": "未持有",
            "earnings_in_days": "{days} 天内有财报",
            "role_quality": "质量压舱石",
            "role_compute": "AI 算力龙头",
            "role_memory": "HBM/存储弹性",
            "role_bottleneck": "设备瓶颈",
            "role_cloud": "云 AI 右侧机会",
            "role_power": "电力分散因子",
            "build_tranche": "首笔买入目标仓位的 1/3（约 {weight:.2f}% NAV）",
            "add_tranche": "再加目标仓位的 1/3（约 {weight:.2f}% NAV）",
            "reduce_tranche": "减当前持仓的 25%-33%",
            "market_template": (
                "VIX={vix:.2f}；QQQ={qqq:.2f}，相对 SMA20/SMA50/SMA200={qqq20:.2f}/{qqq50:.2f}/{qqq200:.2f}；"
                "SMH={smh:.2f}，相对 SMA20/SMA50/SMA200={smh20:.2f}/{smh50:.2f}/{smh200:.2f}"
            ),
            "reason_goog_build": "市场处于绿灯或黄灯，且 GOOG 站在 50 日线上方。",
            "reason_goog_orange_build": "橙色状态下只允许 GOOG 小起始仓，前提是仍站在 50 日线上方。",
            "reason_goog_add": "GOOG 在 20/50 日线附近获得支撑，市场仍可接受。",
            "reason_goog_pause": "GOOG 跌回 50 日线下方或 QQQ 走弱，先观察。",
            "reason_nvda_build": "NVDA 只在绿灯市场建仓，且不能追高到高于 20 日线 8% 以上。",
            "reason_nvda_add": "绿灯环境下，SMH 同步走强，NVDA 可再加一档。",
            "reason_nvda_pause": "先等市场回到绿灯，或等 NVDA 出现更干净的位置。",
            "reason_nvda_reduce": "连续两天跌破 50 日线，或市场转红，需要先降风险。",
            "reason_mu_build": "MU 站上 50 日线，且市场至少不是橙色以下。",
            "reason_mu_add": "趋势仍完整，已有盈利底仓时可以继续放大。",
            "reason_mu_pause": "等 MU 重新回到 50 日线上方，且 SMH 修复。",
            "reason_mu_reduce": "MU 跌破 50 日线且 SMH 同步走坏，应先减仓。",
            "reason_asml_build": "ASML 只在绿灯市场且站稳 50 日线时建仓。",
            "reason_asml_add": "绿灯环境下，趋势仍在，可小幅加仓。",
            "reason_asml_pause": "先等市场回到绿灯，并继续观察政策消息。",
            "reason_asml_reduce": "市场进入红灯或极端风控时，先降低设备链风险。",
            "reason_orcl_build": "ORCL 只做右侧，需重新站回 20 日线且市场不是风险模式。",
            "reason_orcl_add": "ORCL 重新站稳 20 日线，且已有仓位运行良好。",
            "reason_orcl_pause": "没有明确右侧回归前，不做接飞刀抄底。",
            "reason_orcl_reduce": "红灯或极端风控时，应先保护云基建高 beta 敞口。",
            "reason_nlr_build": "只有 VIX 低于 22 且 NLR 在 50 日线上方时才开仓。",
            "reason_nlr_add": "主题趋势仍在，且市场未进入红灯。",
            "reason_nlr_pause": "等 VIX 回到 22 以下，并确认 NLR 仍在 50 日线上方。",
            "reason_nlr_reduce": "市场进入红灯或极端风控时，先减主题 ETF。",
        },
    }

    _PORTFOLIO = (
        _HoldingSpec("GOOG", 20, "quality"),
        _HoldingSpec("NVDA", 18, "compute"),
        _HoldingSpec("MU", 15, "memory"),
        _HoldingSpec("ASML", 12, "bottleneck"),
        _HoldingSpec("ORCL", 10, "cloud"),
        _HoldingSpec("NLR", 10, "power"),
    )

    provider: DailySeriesProvider = field(default_factory=YahooSeriesProvider)
    earnings_provider: EarningsDateProvider = field(default_factory=YahooEarningsDateProvider)
    name: str = "ai_portfolio"
    display_name: str = "AI Infrastructure Portfolio"

    def localized_display_name(
        self,
        settings: Settings,
    ) -> str:
        """Return the localized display name used by the runner on failures."""
        return self._localized_text(settings)["display_name"]

    def should_evaluate(
        self,
        context: MonitorContext,
    ) -> bool:
        """Evaluate once per configured post-close slot unless forced."""
        if context.force_run:
            return True

        timezone = self._get_timezone(context.settings)
        local_now = context.now.astimezone(timezone)
        if (
            local_now.hour != context.settings.portfolio_run_hour
            or local_now.minute != context.settings.portfolio_run_minute
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
        """Evaluate the AI portfolio and return one structured alert bundle."""
        market = self._build_market_snapshot(context.settings)
        decisions = [
            self._evaluate_holding(
                spec=spec,
                market=market,
                settings=context.settings,
            )
            for spec in self._PORTFOLIO
        ]

        title, summary, details = self._build_message(market, decisions, context.settings)
        return FactorResult(
            factor_name=self.name,
            display_name=self.localized_display_name(context.settings),
            severity=self._severity_for_regime(market.regime),
            title=title,
            summary=summary,
            details=details,
            metrics={
                "regime": market.regime,
                "vix_close": round(market.vix_close, 2),
                "qqq_close": round(market.qqq.close, 2),
                "qqq_sma50": round(market.qqq.sma50, 2),
                "qqq_sma200": round(market.qqq.sma200, 2),
                "smh_close": round(market.smh.close, 2),
                "smh_sma50": round(market.smh.sma50, 2),
                "build_count": self._count_actions(decisions, "build"),
                "add_count": self._count_actions(decisions, "add"),
                "pause_count": self._count_actions(decisions, "pause"),
                "reduce_count": self._count_actions(decisions, "reduce"),
            },
        )

    def _get_timezone(
        self,
        settings: Settings,
    ) -> ZoneInfo:
        return ZoneInfo(settings.portfolio_run_timezone)

    def _build_market_snapshot(
        self,
        settings: Settings,
    ) -> _MarketSnapshot:
        vix_bars = self.provider.get_series("vix", settings)
        qqq = self._build_ticker_snapshot("QQQ", self.provider.get_series("ticker:QQQ", settings), settings)
        smh = self._build_ticker_snapshot("SMH", self.provider.get_series("ticker:SMH", settings), settings)

        if not vix_bars:
            raise ValueError("AI portfolio factor requires at least one VIX data point.")

        vix_close = vix_bars[-1].close
        regime = self._classify_market_regime(vix_close=vix_close, qqq=qqq, smh=smh, settings=settings)
        return _MarketSnapshot(
            regime=regime,
            vix_close=vix_close,
            qqq=qqq,
            smh=smh,
        )

    def _classify_market_regime(
        self,
        *,
        vix_close: float,
        qqq: _TickerSnapshot,
        smh: _TickerSnapshot,
        settings: Settings,
    ) -> MarketRegime:
        if vix_close > settings.portfolio_vix_extreme_min or not qqq.above_sma200:
            return "extreme"
        if vix_close > settings.portfolio_vix_orange_max or (not qqq.above_sma50 and not smh.above_sma50):
            return "red"
        if vix_close >= settings.portfolio_vix_yellow_max or not qqq.above_sma50:
            return "orange"
        if (
            vix_close < settings.portfolio_vix_green_max
            and qqq.above_sma20
            and qqq.above_sma50
            and smh.above_sma20
            and smh.above_sma50
        ):
            return "green"
        return "yellow"

    def _evaluate_holding(
        self,
        *,
        spec: _HoldingSpec,
        market: _MarketSnapshot,
        settings: Settings,
    ) -> _Decision:
        snapshot = self._build_ticker_snapshot(
            spec.symbol,
            self.provider.get_series(f"ticker:{spec.symbol}", settings),
            settings,
        )
        held = spec.symbol in settings.portfolio_current_positions
        cost_basis = settings.portfolio_cost_basis.get(spec.symbol)
        profitable = cost_basis is None or snapshot.close >= cost_basis
        earnings_note = self._earnings_note(symbol=spec.symbol, as_of=snapshot.latest_date, settings=settings)
        earnings_guard_active = earnings_note is not None

        if market.regime == "extreme":
            if spec.symbol in {"NVDA", "MU", "ASML", "ORCL"} and held:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="reduce",
                    rationale_key=f"reason_{spec.symbol.lower()}_reduce",
                    settings=settings,
                )
            if spec.symbol == "NLR" and held:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="reduce",
                    rationale_key="reason_nlr_reduce",
                    settings=settings,
                    earnings_note=earnings_note,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key=f"reason_{spec.symbol.lower()}_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if market.regime == "red":
            if spec.symbol in {"NVDA", "MU", "ASML", "ORCL", "NLR"} and held:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="reduce",
                    rationale_key=f"reason_{spec.symbol.lower()}_reduce",
                    settings=settings,
                    earnings_note=earnings_note,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key=f"reason_{spec.symbol.lower()}_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "GOOG":
            if market.regime in {"green", "yellow"} and snapshot.above_sma50 and not earnings_guard_active:
                action: Action = "add" if held and profitable else "build"
                rationale_key = "reason_goog_add" if action == "add" else "reason_goog_build"
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action=action,
                    rationale_key=rationale_key,
                    settings=settings,
                )
            if market.regime == "orange" and not held and snapshot.above_sma50 and not earnings_guard_active:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="build",
                    rationale_key="reason_goog_orange_build",
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_goog_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "NVDA":
            if snapshot.two_day_below_sma50 and held:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="reduce",
                    rationale_key="reason_nvda_reduce",
                    settings=settings,
                    earnings_note=earnings_note,
                )
            if (
                market.regime == "green"
                and snapshot.above_sma50
                and not snapshot.extended_above_sma20
                and not earnings_guard_active
            ):
                action = (
                    "add" if held and profitable and (snapshot.at_ten_day_high or market.smh.above_sma20) else "build"
                )
                rationale_key = "reason_nvda_add" if action == "add" else "reason_nvda_build"
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action=action,
                    rationale_key=rationale_key,
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_nvda_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "MU":
            if snapshot.two_day_below_sma50 and not market.smh.above_sma50 and held:
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="reduce",
                    rationale_key="reason_mu_reduce",
                    settings=settings,
                    earnings_note=earnings_note,
                )
            if market.regime in {"green", "yellow"} and snapshot.above_sma50 and not earnings_guard_active:
                action = "add" if held and profitable else "build"
                rationale_key = "reason_mu_add" if action == "add" else "reason_mu_build"
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action=action,
                    rationale_key=rationale_key,
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_mu_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "ASML":
            if market.regime == "green" and snapshot.above_sma50 and not earnings_guard_active:
                action = "add" if held and profitable else "build"
                rationale_key = "reason_asml_add" if action == "add" else "reason_asml_build"
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action=action,
                    rationale_key=rationale_key,
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_asml_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "ORCL":
            if (
                held
                and market.regime in {"green", "yellow"}
                and snapshot.above_sma20
                and profitable
                and not earnings_guard_active
            ):
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="add",
                    rationale_key="reason_orcl_add",
                    settings=settings,
                )
            if (
                not held
                and market.regime in {"green", "yellow"}
                and snapshot.reclaimed_sma20
                and not earnings_guard_active
            ):
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action="build",
                    rationale_key="reason_orcl_build",
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_orcl_pause",
                settings=settings,
                earnings_note=earnings_note,
            )

        if spec.symbol == "NLR":
            if market.vix_close < settings.portfolio_nlr_vix_build_max and snapshot.above_sma50:
                action = "add" if held and profitable and market.regime in {"green", "yellow"} else "build"
                rationale_key = "reason_nlr_add" if action == "add" else "reason_nlr_build"
                return self._decision(
                    spec,
                    snapshot,
                    held=held,
                    action=action,
                    rationale_key=rationale_key,
                    settings=settings,
                )
            return self._decision(
                spec,
                snapshot,
                held=held,
                action="pause",
                rationale_key="reason_nlr_pause",
                settings=settings,
            )

        return self._decision(
            spec,
            snapshot,
            held=held,
            action="pause",
            rationale_key="reason_goog_pause",
            settings=settings,
            earnings_note=earnings_note,
        )

    def _build_ticker_snapshot(
        self,
        symbol: str,
        bars: list[DailyBar],
        settings: Settings,
    ) -> _TickerSnapshot:
        required_points = max(
            settings.portfolio_long_window,
            settings.portfolio_medium_window + 1,
            settings.portfolio_short_window + 1,
            settings.portfolio_breakout_window,
        )
        if len(bars) < required_points:
            raise ValueError(f"{symbol} requires at least {required_points} daily points for portfolio monitoring.")

        closes = [bar.close for bar in bars]
        return _TickerSnapshot(
            symbol=symbol,
            close=closes[-1],
            sma20=self._simple_moving_average(closes, settings.portfolio_short_window),
            sma50=self._simple_moving_average(closes, settings.portfolio_medium_window),
            sma200=self._simple_moving_average(closes, settings.portfolio_long_window),
            prev_close=closes[-2],
            prev_sma20=self._simple_moving_average(closes[:-1], settings.portfolio_short_window),
            prev_sma50=self._simple_moving_average(closes[:-1], settings.portfolio_medium_window),
            high10=max(closes[-settings.portfolio_breakout_window :]),
            latest_date=bars[-1].date,
        )

    def _simple_moving_average(
        self,
        closes: list[float],
        window: int,
    ) -> float:
        if len(closes) < window:
            raise ValueError(f"Need at least {window} closes to compute the requested moving average.")
        return mean(closes[-window:])

    def _earnings_note(
        self,
        *,
        symbol: str,
        as_of: date,
        settings: Settings,
    ) -> str | None:
        try:
            earnings_date = self.earnings_provider.get_next_earnings_date(symbol, as_of=as_of)
        except Exception:
            return None

        if earnings_date is None:
            return None

        days_until = (earnings_date - as_of).days
        if 0 <= days_until <= settings.portfolio_earnings_guard_days:
            text = self._localized_text(settings)
            return text["earnings_in_days"].format(days=days_until)
        return None

    def _decision(
        self,
        spec: _HoldingSpec,
        snapshot: _TickerSnapshot,
        *,
        held: bool,
        action: Action,
        rationale_key: str,
        settings: Settings,
        earnings_note: str | None = None,
    ) -> _Decision:
        text = self._localized_text(settings)
        tranche = None
        if action == "build":
            tranche = text["build_tranche"].format(weight=spec.target_weight / 3)
        elif action == "add":
            tranche = text["add_tranche"].format(weight=spec.target_weight / 3)
        elif action == "reduce":
            tranche = text["reduce_tranche"]

        return _Decision(
            symbol=spec.symbol,
            target_weight=spec.target_weight,
            action=action,
            rationale=text[rationale_key],
            tranche=tranche,
            earnings_note=earnings_note,
            held=held,
            close=snapshot.close,
            sma20=snapshot.sma20,
            sma50=snapshot.sma50,
            sma200=snapshot.sma200,
        )

    def _build_message(
        self,
        market: _MarketSnapshot,
        decisions: list[_Decision],
        settings: Settings,
    ) -> tuple[str, str, str]:
        text = self._localized_text(settings)
        regime_label = text[f"regime_{market.regime}"]
        summary = text["summary_template"].format(
            regime=regime_label,
            build=self._count_actions(decisions, "build"),
            add=self._count_actions(decisions, "add"),
            pause=self._count_actions(decisions, "pause"),
            reduce=self._count_actions(decisions, "reduce"),
            cash=text[f"cash_{market.regime}"],
        )
        title = f"{text['title_prefix']}: {regime_label}"

        action_lines = []
        for decision in decisions:
            holding_key = "holding_yes" if decision.held else "holding_no"
            line = (
                f"- {decision.symbol} ({decision.target_weight}%): {text[f'action_{decision.action}']} | "
                f"{text[holding_key]} | "
                f"close={decision.close:.2f}, SMA20={decision.sma20:.2f}, "
                f"SMA50={decision.sma50:.2f}, SMA200={decision.sma200:.2f} | {decision.rationale}"
            )
            if decision.tranche:
                line = f"{line} | {decision.tranche}"
            if decision.earnings_note:
                line = f"{line} | {decision.earnings_note}"
            action_lines.append(line)

        details = "\n".join(
            [
                f"{text['market_header']}: {regime_label} | {text[f'cash_{market.regime}']}",
                text["market_template"].format(
                    vix=market.vix_close,
                    qqq=market.qqq.close,
                    qqq20=market.qqq.sma20,
                    qqq50=market.qqq.sma50,
                    qqq200=market.qqq.sma200,
                    smh=market.smh.close,
                    smh20=market.smh.sma20,
                    smh50=market.smh.sma50,
                    smh200=market.smh.sma200,
                ),
                "",
                f"{text['action_header']}:",
                *action_lines,
                "",
                text["manual_review"],
            ]
        ).rstrip()

        return title, summary, details

    def _severity_for_regime(
        self,
        regime: MarketRegime,
    ) -> Severity:
        if regime in {"red", "extreme"}:
            return Severity.CRITICAL
        if regime in {"yellow", "orange"}:
            return Severity.WARNING
        return Severity.INFO

    def _localized_text(
        self,
        settings: Settings,
    ) -> dict[str, str]:
        language = settings.report_language.strip().lower()
        return self._LOCALIZED_TEXT.get(language, self._LOCALIZED_TEXT["en"])

    def _count_actions(
        self,
        decisions: list[_Decision],
        action: Action,
    ) -> int:
        return sum(1 for decision in decisions if decision.action == action)
