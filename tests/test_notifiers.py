from __future__ import annotations

import httpx

from sentrymode.monitoring.notifiers import ConsoleBarkNotifier


class _DummyResponse:
    def __init__(
        self,
        status_code: int,
    ) -> None:
        self.status_code = status_code


def test_notifier_send_plain_success_push(
    monkeypatch,
    capsys,
) -> None:
    calls: list[tuple[str, float]] = []

    def fake_get(
        url: str,
        *,
        timeout: float,
    ) -> _DummyResponse:
        calls.append((url, timeout))
        return _DummyResponse(200)

    monkeypatch.setattr(httpx, "get", fake_get)

    notifier = ConsoleBarkNotifier(
        bark_server="https://bark.example.com/",
        bark_device_key="device-key",
        report_format="plain",
        timeout_seconds=3.5,
    )

    notifier.send("Hello Title", "hello body")
    captured = capsys.readouterr()

    assert "Hello Title" in captured.out
    assert "Bark push succeeded" in captured.out
    assert len(calls) == 1
    assert calls[0][1] == 3.5
    assert calls[0][0].startswith("https://bark.example.com/device-key/")


def test_notifier_send_plain_non_200_push(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, *, timeout,: _DummyResponse(503))
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format="plain")

    notifier.send("t", "b")
    captured = capsys.readouterr()

    assert "HTTP 503" in captured.out


def test_notifier_send_plain_push_exception(
    monkeypatch,
    capsys,
) -> None:
    def fake_get(
        url: str,
        *,
        timeout: float,
    ) -> _DummyResponse:
        raise RuntimeError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format="plain")

    notifier.send("t", "b")
    captured = capsys.readouterr()

    assert "Bark push failed: boom" in captured.out


def test_notifier_send_plain_skips_http_without_server(
    monkeypatch,
    capsys,
) -> None:
    called = False

    def fake_get(
        url: str,
        *,
        timeout: float,
    ) -> _DummyResponse:
        nonlocal called
        called = True
        return _DummyResponse(200)

    monkeypatch.setattr(httpx, "get", fake_get)
    notifier = ConsoleBarkNotifier("", "", report_format="plain")

    notifier.send("Title", "Body")
    captured = capsys.readouterr()

    assert "Title" in captured.out
    assert called is False


def test_notifier_send_dispatches_to_markdown(
    monkeypatch,
) -> None:
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format=" MARKDOWN ")
    observed: list[tuple[str, str]] = []

    def fake_send_markdown(
        title: str,
        body: str,
    ) -> None:
        observed.append((title, body))

    monkeypatch.setattr(notifier, "send_markdown", fake_send_markdown)

    notifier.send("title", "body")

    assert observed == [("title", "body")]


def test_notifier_send_markdown_success(
    monkeypatch,
    capsys,
) -> None:
    calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def fake_post(
        url: str,
        *,
        json: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> _DummyResponse:
        calls.append((url, json, headers, timeout))
        return _DummyResponse(200)

    monkeypatch.setattr(httpx, "post", fake_post)

    notifier = ConsoleBarkNotifier(
        "https://bark.example.com/",
        "device-1",
        report_format="markdown",
        timeout_seconds=5.0,
    )
    notifier.send_markdown("Report", "Body")
    captured = capsys.readouterr()

    assert "# Report" in captured.out
    assert "Bark markdown push succeeded" in captured.out
    assert calls == [
        (
            "https://bark.example.com/push",
            {"device_key": "device-1", "markdown": "# Report\n\nBody"},
            {"Content-Type": "application/json"},
            5.0,
        )
    ]


def test_notifier_send_markdown_non_200(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs,: _DummyResponse(500))
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format="markdown")

    notifier.send_markdown("t", "b")
    captured = capsys.readouterr()

    assert "HTTP 500" in captured.out


def test_notifier_send_markdown_exception(
    monkeypatch,
    capsys,
) -> None:
    def fake_post(
        url: str,
        *,
        json: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> _DummyResponse:
        raise RuntimeError("post failed")

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format="markdown")

    notifier.send_markdown("t", "b")
    captured = capsys.readouterr()

    assert "Bark markdown push failed: post failed" in captured.out


def test_notifier_send_markdown_skips_http_without_device(
    monkeypatch,
) -> None:
    called = False

    def fake_post(
        url: str,
        *,
        json: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> _DummyResponse:
        nonlocal called
        called = True
        return _DummyResponse(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = ConsoleBarkNotifier("https://bark.example.com", "", report_format="markdown")

    notifier.send_markdown("t", "b")

    assert called is False


def test_notifier_should_use_markdown_checks_normalized_format() -> None:
    notifier = ConsoleBarkNotifier("https://bark.example.com", "k", report_format=" markdown ")

    assert notifier._should_use_markdown() is True
