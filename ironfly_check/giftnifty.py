"""GIFT NIFTY (ex-SGX Nifty) pre-market indication.

Upstox does **not** carry GIFT NIFTY (it trades on NSE IX / GIFT City), so the
Stage-1 expected-gap filter needs an external source. GIFT levels on the public
web are almost all JavaScript-rendered, which makes plain-``requests`` scraping
fragile. The design therefore prioritises a **manual override** and degrades
cleanly to ``None`` (unknown) when every scrape attempt fails — the scorecard
treats an unknown expected-gap as "cannot score that point" rather than guessing.

Resolution order:
    1. ``IFC_GIFT_NIFTY`` env var  (you paste the level each morning — always wins)
    2. A best-effort scrape of one or more public sources
    3. ``None`` with a human-readable reason
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 10.0
# Plausible NIFTY level band — reject anything outside it as a bad parse.
_MIN_LEVEL, _MAX_LEVEL = 10_000.0, 40_000.0


@dataclass(frozen=True)
class GiftNifty:
    value: float | None
    source: str          # "override" | scraper name | "unavailable"
    ok: bool
    note: str = ""


def _plausible(x: float) -> bool:
    return _MIN_LEVEL <= x <= _MAX_LEVEL


def _from_override() -> GiftNifty | None:
    raw = os.environ.get("IFC_GIFT_NIFTY", "").strip().replace(",", "")
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        return GiftNifty(None, "override", False, f"IFC_GIFT_NIFTY not numeric: {raw!r}")
    if not _plausible(v):
        return GiftNifty(None, "override", False, f"IFC_GIFT_NIFTY out of range: {v}")
    return GiftNifty(v, "override", True, "manual override")


def _scrape_investing() -> float | None:
    """Investing.com renders the last price into the page as a data attribute /
    span; grab the first plausible 5-digit number near the instrument id."""
    url = "https://www.investing.com/indices/gift-nifty"
    r = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    # Look for `data-test="instrument-price-last">25,123.45<` style markup.
    m = re.search(r'instrument-price-last"[^>]*>([\d,]+\.\d+)', r.text)
    if not m:
        # Fallback: any 5-digit,decimal number in the head of the doc.
        m = re.search(r'>(\d{2},\d{3}\.\d{2})<', r.text)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v if _plausible(v) else None


_SCRAPERS = (("investing.com", _scrape_investing),)


def fetch() -> GiftNifty:
    """Resolve GIFT NIFTY. Never raises — a failed fetch degrades to unknown."""
    override = _from_override()
    if override is not None:
        return override

    errors: list[str] = []
    for name, fn in _SCRAPERS:
        try:
            v = fn()
            if v is not None:
                return GiftNifty(v, name, True, "scraped")
            errors.append(f"{name}: no value parsed")
        except Exception as e:  # network / parse — degrade, don't crash the check
            errors.append(f"{name}: {type(e).__name__}")

    return GiftNifty(
        None, "unavailable", False,
        "no source resolved (set IFC_GIFT_NIFTY to override): " + "; ".join(errors),
    )
