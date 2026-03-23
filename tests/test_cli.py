from __future__ import annotations

from sentrymode import __version__
from sentrymode.__main__ import main


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_output(
    capsys,
) -> None:
    main([])
    captured = capsys.readouterr()
    assert "SentryMode" in captured.out
