"""NIFTY 50 constituents and their Upstox instrument keys, for the breadth filter.

Rather than hard-code 50 ISIN-based instrument keys (brittle, easy to get wrong on
an index reconstitution), we keep the stable list of trading *symbols* and resolve
them to Upstox ``NSE_EQ|<ISIN>`` keys from Upstox's public instrument master, which
is downloaded once per day and cached under ``data/``. If the master can't be
fetched, breadth degrades to "unavailable" and its scorecard point is skipped.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import requests

# NIFTY 50 trading symbols (NSE). Review on each index reconstitution.
NIFTY50_SYMBOLS: tuple[str, ...] = (
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC",
    "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA",
    "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "ETERNAL",
)

_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_HEADERS = {"User-Agent": "iron-fly-regime-check/0.1"}


def _cache_path(data_dir: Path, day: str) -> Path:
    return data_dir / f"nse_master_{day}.json.gz"


def _download_master(dest: Path) -> None:
    r = requests.get(_MASTER_URL, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)


def resolve_keys(data_dir: str | Path, day: str) -> dict[str, str]:
    """Return ``{symbol: instrument_key}`` for the NIFTY-50 equities.

    ``day`` is an ISO date string used to cache the master once per day. Returns
    an empty dict on any failure (breadth then degrades to unavailable).
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(data_dir, day)
    try:
        if not cache.exists():
            # Clean up yesterday's masters to avoid unbounded growth.
            for old in data_dir.glob("nse_master_*.json.gz"):
                try:
                    old.unlink()
                except OSError:
                    pass
            _download_master(cache)
        with gzip.open(cache, "rt", encoding="utf-8") as fh:
            instruments = json.load(fh)
    except Exception:
        return {}

    wanted = set(NIFTY50_SYMBOLS)
    out: dict[str, str] = {}
    for inst in instruments:
        seg = inst.get("segment") or inst.get("exchange")
        itype = inst.get("instrument_type") or ""
        tsym = inst.get("trading_symbol") or inst.get("tradingsymbol") or ""
        if tsym in wanted and (seg == "NSE_EQ" or itype in ("EQ", "")):
            key = inst.get("instrument_key") or inst.get("instrumentKey")
            if key and tsym not in out:
                out[tsym] = key
    return out
