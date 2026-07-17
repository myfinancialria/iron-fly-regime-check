"""Command-line entry point.

    python -m ironfly_check login [url|<code-or-redirect-url>]
    python -m ironfly_check premarket [--date YYYY-MM-DD]   # Stage 1, run 08:45–09:10
    python -m ironfly_check confirm  [--date YYYY-MM-DD]    # Stage 2, run after 09:20
    python -m ironfly_check selftest                        # offline logic check
    python -m ironfly_check show                            # print the latest signal.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from . import config as cfg
from . import login as login_mod
from .calendar import NSECalendar, now_ist
from .scorecard import Scorecard
from .signal import build_signal, write_signal
from .stage1 import score_premarket
from .stage2 import score_opening

ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "docs"      # GitHub Pages serves from /docs
DATA_DIR = ROOT / "data"

C = {"green": "\033[92m", "amber": "\033[93m", "red": "\033[91m",
     "neutral": "\033[90m", "bold": "\033[1m", "end": "\033[0m"}


def _color(text: str, key: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{C.get(key, '')}{text}{C['end']}"


def _token() -> str:
    env = login_mod.read_env()
    token = env.get("UPSTOX_TOKEN", "")
    if not token:
        raise SystemExit(
            "No UPSTOX_TOKEN. Run `python -m ironfly_check login url`, then "
            "`python -m ironfly_check login <redirect-url>`."
        )
    return token


def _print_scorecard(sc: Scorecard) -> None:
    title = "PRE-MARKET (Stage 1)" if sc.stage == "premarket" else "09:20 CONFIRMATION (Stage 2)"
    print(_color(f"\n── {title} ──", "bold"))
    for c in sc.conditions:
        mark = "✓" if c.passed else ("·" if c.passed is None else "✗")
        print(f"  {_color(mark, c.color)} {c.name:<34} {c.detail}")
    print(f"  Score: {_color(f'{sc.score}/{sc.max_score}', 'bold')}")
    if sc.hard_red:
        for h in sc.hard_red:
            print(f"  {_color('HARD-RED', 'red')} {h}")
    status_col = ("green" if sc.status in ("GREEN", "STANDARD_ENTRY")
                  else "red" if sc.status in ("RED", "SKIP")
                  else "amber")
    print(f"  → {_color(sc.status, status_col)}: {sc.action}")


def _emit(sig, wrote: Path) -> None:
    print(_color(f"\n══ DECISION: {sig.decision} ══", "bold"))
    if sig.structure and sig.grade != "—":
        print(f"  Grade {sig.grade}: {sig.structure['structure']}")
        print(f"    {sig.structure['legs']}")
        print(f"    {sig.structure['hedge_rule']}")
    if sig.sizing:
        s = sig.sizing
        print(f"  Sizing: risk ₹{s['planned_risk_rupees']:,} "
              f"({s['planned_risk_pct']:.2f}% of ₹{int(s['capital']):,}), "
              f"daily stop ₹{s['max_daily_loss_rupees']:,}")
    print(_color(f"\nWrote {wrote}", "neutral"))


def cmd_premarket(args: argparse.Namespace) -> int:
    from .data import fetch_premarket
    from .upstox_client import UpstoxClient

    conf = cfg.Config.from_env()
    trade_date = _parse_date(args.date)
    with UpstoxClient(_token()) as client:
        pm = fetch_premarket(client, trade_date, conf)
    sc = score_premarket(pm, conf)
    _print_scorecard(sc)
    sig = build_signal(trade_date, sc, None, conf)
    wrote = write_signal(sig, SITE_DIR, DATA_DIR)
    _emit(sig, wrote)
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    from .data import fetch_opening, fetch_premarket
    from .upstox_client import UpstoxClient

    conf = cfg.Config.from_env()
    trade_date = _parse_date(args.date)
    with UpstoxClient(_token()) as client:
        pm = fetch_premarket(client, trade_date, conf)
        pm_sc = score_premarket(pm, conf)
        op = fetch_opening(client, trade_date, conf, DATA_DIR, premarket=pm)
    op_sc = score_opening(op, pm_sc.status, conf)
    _print_scorecard(pm_sc)
    _print_scorecard(op_sc)
    sig = build_signal(trade_date, pm_sc, op_sc, conf)
    wrote = write_signal(sig, SITE_DIR, DATA_DIR)
    _emit(sig, wrote)
    return 0


def cmd_selftest(_args: argparse.Namespace) -> int:
    from .selftest import run_selftest
    return run_selftest()


def cmd_show(_args: argparse.Namespace) -> int:
    p = SITE_DIR / "signal.json"
    if not p.exists():
        print("No signal.json yet — run premarket/confirm first.")
        return 1
    print(json.dumps(json.loads(p.read_text()), indent=2))
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    arg = args.arg or "url"
    login_mod._cli([arg])
    return 0


def _parse_date(s: str | None) -> date:
    if s:
        return date.fromisoformat(s)
    d = now_ist().date()
    cal = NSECalendar()
    if not cal.is_trading_day(d):
        print(_color(f"Warning: {d} is not an NSE trading day.", "amber"))
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ironfly_check", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="Upstox OAuth token (daily)")
    sp.add_argument("arg", nargs="?", help="'url' or the redirect URL / code")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("premarket", help="Stage 1 pre-market regime check")
    sp.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    sp.set_defaults(func=cmd_premarket)

    sp = sub.add_parser("confirm", help="Stage 2 09:20 confirmation")
    sp.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    sp.set_defaults(func=cmd_confirm)

    sp = sub.add_parser("selftest", help="offline logic check (no network)")
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser("show", help="print the latest signal.json")
    sp.set_defaults(func=cmd_show)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
