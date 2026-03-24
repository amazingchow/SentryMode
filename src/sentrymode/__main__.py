"""
SentryMode CLI composition entrypoint.

[INPUT]: CLI argv tokens from console script wrapper or tests.
[OUTPUT]: Command dispatch to factor listing, one-shot execution, or shared monitor loop.
[POS]: Located at package entrypoint.
       Upstream: `project.scripts.sentrymode`.
       Downstream: `sentrymode.factors` registry + `sentrymode.monitoring` runner/notifier wiring.

[PROTOCOL]:
1. Keep command parsing and process I/O here; factor math belongs in `sentrymode.factors`.
2. Sync this docstring when commands, wiring dependencies, or dispatch flow changes.
"""

from __future__ import annotations

import argparse
import sys

from sentrymode.factors import create_factors, list_factor_names
from sentrymode.monitoring import ConsoleBarkNotifier, MonitorRunner, Settings


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(
        prog="sentrymode",
        description="SentryMode multi-factor monitoring CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-factors", help="List all available monitoring factors.")

    run_once_parser = subparsers.add_parser(
        "run-once",
        help="Run selected factors immediately and send one aggregated report.",
    )
    run_once_parser.add_argument(
        "--factor",
        action="append",
        dest="factors",
        help="Factor name to run. Can be passed multiple times.",
    )

    run_monitor_parser = subparsers.add_parser(
        "run-monitor",
        help="Start the shared monitoring loop.",
    )
    run_monitor_parser.add_argument(
        "--factor",
        action="append",
        dest="factors",
        help="Factor name to monitor. Can be passed multiple times.",
    )

    return parser


def build_runner() -> MonitorRunner:
    """Create the default application runner."""
    settings = Settings()
    notifier = ConsoleBarkNotifier(
        bark_server=settings.bark_server,
        bark_device_key=settings.bark_device_key,
        report_format=settings.report_format,
        timeout_seconds=settings.ahr_http_timeout_seconds,
    )
    return MonitorRunner(
        factors=create_factors(),
        settings=settings,
        notifier=notifier,
    )


def print_factor_list() -> None:
    """Print the registered factor names."""
    settings = Settings()
    enabled = set(settings.enabled_factors)
    print("Available factors:")
    for factor_name in list_factor_names():
        suffix = " (enabled)" if factor_name in enabled else ""
        print(f"- {factor_name}{suffix}")


def main(
    argv: list[str] | None = None,
) -> None:
    """Run the project CLI.

    When invoked as a console script, the setuptools/uv wrapper calls ``main()``
    with no arguments; in that case we parse ``sys.argv[1:]``. Pass an explicit
    ``argv`` (e.g. ``[]``) in tests to avoid coupling to the host process argv.
    """
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        print("SentryMode: multi-factor monitoring toolkit.")
        parser.print_help()
        return

    if args.command == "list-factors":
        print_factor_list()
        return

    runner = build_runner()

    if args.command == "run-once":
        runner.run_once(factor_names=args.factors, force=True)
        return

    if args.command == "run-monitor":
        runner.run_forever(factor_names=args.factors)
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main(sys.argv[1:])
