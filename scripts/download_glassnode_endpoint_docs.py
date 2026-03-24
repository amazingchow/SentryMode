"""Download Glassnode Basic API endpoint category pages as markdown."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from tqdm import tqdm

MENU_ITEMS = [
    "Addresses",
    "Bridges",
    "Blockchain",
    "Breakdowns",
    "DeFi",
    "Derivatives",
    "Distribution",
    "Entities",
    "ETH 2.0",
    "Fees",
    "Indicators",
    "Institutions",
    "Lightning",
    "Market",
    "Mempool",
    "Mining",
    "Options",
    "Point-In-Time",
    "Protocols",
    "Signals",
    "Supply",
    "Transactions",
    "Treasuries",
]

BASE_URL = "https://docs.glassnode.com/basic-api/endpoints/"
OUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "glassnode" / "endpoints"
TIMEOUT = 60.0
HEADERS = {"User-Agent": "SentryMode-docs-fetch/1.0"}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []

    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        for name in tqdm(MENU_ITEMS, desc="Downloading", unit="endpoint"):
            if name == "ETH 2.0":
                name = "eth2"
            elif name == "Point-In-Time":
                name = "pit"
            name = name.lower()
            slug = quote(name, safe="")
            url = f"{BASE_URL}{slug}.md"
            out_path = OUT_DIR / f"{name}.md"
            try:
                r = client.get(url)
                r.raise_for_status()
                out_path.write_bytes(r.content)
            except httpx.HTTPError as e:
                tqdm.write(f"FAIL {name} ({url}): {e}", file=sys.stderr)
                failed.append(name)

    if failed:
        print(f"Failed ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
