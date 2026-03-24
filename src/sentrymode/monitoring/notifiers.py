"""
Console and Bark notification adapters.

[INPUT]: Report title/body strings from `MonitorRunner` + Bark connection settings.
[OUTPUT]: Console output and optional HTTP push requests to Bark endpoints.
[POS]: Side-effect adapter layer in `sentrymode.monitoring`.
       Upstream: `MonitorRunner`.
       Downstream: stdout and `httpx` network calls.

[PROTOCOL]:
1. Keep notification transport concerns in this module; avoid leaking transport code into runner/factors.
2. Handle push failures defensively and preserve runner continuity.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

import httpx
from colorama import Fore, Style, init

init(autoreset=True)


class ConsoleBarkNotifier:
    """Notifier that prints to stdout and optionally pushes to Bark."""

    def __init__(
        self,
        bark_server: str,
        bark_device_key: str,
        report_format: str = "plain",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._bark_server = bark_server
        self._bark_device_key = bark_device_key
        self._report_format = report_format
        self._timeout_seconds = timeout_seconds

    def send(
        self,
        title: str,
        body: str,
    ) -> None:
        """Send a formatted report and push it to Bark if configured."""
        if self._should_use_markdown():
            self.send_markdown(title, body)
            return

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = Fore.CYAN + "-" * 50 + Style.RESET_ALL

        print(separator)
        print(f"{Fore.YELLOW}[{current_time}] {title}{Style.RESET_ALL}\n")
        print(body)
        print(separator)

        if not self._bark_server or not self._bark_device_key:
            return

        try:
            push_url = f"{self._bark_server.rstrip('/')}/{self._bark_device_key}/{quote(title)}/{quote(body)}"
            response = httpx.get(push_url, timeout=self._timeout_seconds)
            if response.status_code == 200:
                print(f"{Fore.GREEN}Bark push succeeded.{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}Bark push returned HTTP {response.status_code}.{Style.RESET_ALL}")
        except Exception as exc:
            print(f"{Fore.YELLOW}Bark push failed: {exc}{Style.RESET_ALL}")

    def send_markdown(
        self,
        title: str,
        body: str,
    ) -> None:
        """Send a markdown formatted report and push it to Bark if configured."""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        separator = Fore.CYAN + "-" * 50 + Style.RESET_ALL
        markdown_body = f"# {title}\n\n{body}"

        print(separator)
        print(f"{Fore.YELLOW}[{current_time}] {title}{Style.RESET_ALL}\n")
        print(markdown_body)
        print(separator)

        if not self._bark_server or not self._bark_device_key:
            return

        try:
            push_url = f"{self._bark_server.rstrip('/')}/push"
            response = httpx.post(
                push_url,
                json={
                    "device_key": self._bark_device_key,
                    "markdown": markdown_body,
                },
                headers={"Content-Type": "application/json"},
                timeout=self._timeout_seconds,
            )
            if response.status_code == 200:
                print(f"{Fore.GREEN}Bark markdown push succeeded.{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}Bark markdown push returned HTTP {response.status_code}.{Style.RESET_ALL}")
        except Exception as exc:
            print(f"{Fore.YELLOW}Bark markdown push failed: {exc}{Style.RESET_ALL}")

    def _should_use_markdown(
        self,
    ) -> bool:
        """Return whether Bark push should use the markdown endpoint."""
        return self._report_format.strip().lower() == "markdown"
