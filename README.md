A multi-factor monitoring toolkit for market signals. It is built around a small, extensible core: each factor owns its evaluation logic, a shared runner handles scheduling, and a unified notifier emits one aggregated report per execution cycle.

The project currently ships with five factors:

- `ai_portfolio`: AI infrastructure portfolio monitoring with VIX/QQQ/SMH regime control
- `ahr999`: BTC valuation and regime monitoring
- `btc_realized_pl_ratio_90d`: BTC cycle confirmation from the realized P/L ratio 90-day SMA (Glassnode-backed, opt-in)
- `us10y`: US10Y dual-MA trend monitoring with VIX/SPY overlay
- `vix`: VIX risk-light monitoring with SPY confirmation

## Why SentryMode

- Multi-factor friendly: add new factors without rewriting the runner.
- Shared scheduling model: one loop, each factor decides whether it should run.
- Unified notifications: one execution produces one aggregated report.
- Configuration-first: runtime behavior is driven by environment variables via `pydantic-settings`.
- Practical developer workflow: `uv`, `ruff`, `pytest`, `pre-commit`, and `Makefile` commands are already wired in.

## Quick Start

### Requirements

- Python `3.12+`
- [`uv`](https://docs.astral.sh/uv/)

### Installation

```bash
git clone https://github.com/amazingchow/SentryMode.git
cd SentryMode
make install
```

Or, if you prefer raw `uv` commands:

```bash
uv sync --all-extras --dev
```

### First Commands

List all registered factors:

```bash
sentrymode list-factors
```

Run all enabled factors once:

```bash
sentrymode run-once
```

Run only AHR999 once:

```bash
sentrymode run-once --factor ahr999
```

Run only VIX once:

```bash
sentrymode run-once --factor vix
```

Run only BTC realized P/L ratio SMA90 once:

```bash
sentrymode run-once --factor btc_realized_pl_ratio_90d
```

Run only the AI infrastructure portfolio monitor once:

```bash
sentrymode run-once --factor ai_portfolio
```

Start the shared monitor loop:

```bash
sentrymode run-monitor
```

Show CLI help:

```bash
sentrymode --help
```

### Command Behavior

- `list-factors`: print all registered factors and mark the enabled ones
- `run-once`: force an immediate evaluation and send one aggregated report
- `run-monitor`: start the shared polling loop; each factor decides whether it should execute on a given tick

## Configuration

Runtime settings use the `SENTRYMODE_` environment prefix and optional `.env` file (`pydantic-settings`). See `.env.example` for every variable, defaults, descriptions, data-source notes, and a copy-paste example block. The `ai_portfolio` factor adds schedule, ticker-history, and optional current-position/cost-basis settings for tranche-aware alerts. The Glassnode-backed `btc_realized_pl_ratio_90d` factor also requires `SENTRYMODE_GLASSNODE_API_KEY` when enabled.

## Project Layout

```text
.
|-- src/sentrymode/
|   |-- __main__.py
|   |-- monitoring/
|   |-- market_data.py
|   `-- factors/
|       |-- ai_portfolio.py
|       |-- ahr999.py
|       |-- btc_realized_pl_ratio_90d.py
|       |-- us10y.py
|       `-- vix.py
|-- tests/
|-- scripts/
|-- Makefile
`-- pyproject.toml
```

## Adding a New Factor

The project is already structured for factor expansion.

1. Add a new module under `src/sentrymode/factors/`.
2. Implement a factor class with:
   - `name`
   - `display_name`
   - `should_evaluate(context) -> bool`
   - `evaluate(context) -> FactorResult`
3. Register the factor in `src/sentrymode/factors/__init__.py`.
4. Enable it through `SENTRYMODE_ENABLED_FACTORS`.

The runner and notifier layers do not need to change for a normal factor addition.

## Development

Run the full local quality pipeline:

```bash
make check
```

## Operational Notes

- `run-once` is useful for cron jobs, manual checks, and debugging a single factor.
- `run-monitor` is intended for long-running processes.
- Factor failures are isolated into report entries; one factor error should not crash the whole runner.
- In network-restricted environments, market data fetches may fail gracefully and be reported as factor execution errors.
- The `ai_portfolio`, `vix`, `us10y`, and `btc_realized_pl_ratio_90d` factors are intentionally opt-in by default. Add them to `SENTRYMODE_ENABLED_FACTORS` when you want them included in shared runs.
- The `ai_portfolio` factor is opinionated: it monitors a fixed AI infrastructure basket (`GOOG`, `NVDA`, `MU`, `ASML`, `ORCL`, `NLR`) and combines VIX, QQQ, SMH, moving averages, and optional earnings windows into build/add/pause/reduce alerts.
- The `btc_realized_pl_ratio_90d` factor requires a valid Glassnode API key and computes the 90-day SMA locally from daily `Realized P/L Ratio` data.

## Roadmap

- Add more BTC and macro factors
- Support richer notification channels
- Add persistent state and historical snapshots
- Expand automated test coverage for factor scheduling and calculations

## License

This project is licensed under the MIT License. See `LICENSE`.
