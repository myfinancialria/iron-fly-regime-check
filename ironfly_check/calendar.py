"""NSE trading calendar + session-time helpers. All times are IST."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# The 09:15–09:20 opening 5-minute candle boundaries.
OPEN_CANDLE_START = time(9, 15)
OPEN_CANDLE_END = time(9, 20)

# NSE trading holidays. Extend as new exchange circulars land.
NSE_HOLIDAYS: set[date] = {
    date(2025, 2, 26), date(2025, 3, 14), date(2025, 3, 31), date(2025, 4, 10),
    date(2025, 4, 14), date(2025, 4, 18), date(2025, 5, 1), date(2025, 8, 15),
    date(2025, 8, 27), date(2025, 10, 2), date(2025, 10, 21), date(2025, 10, 22),
    date(2025, 11, 5), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 1, 26), date(2026, 3, 3), date(2026, 3, 21),
    date(2026, 4, 1), date(2026, 4, 14), date(2026, 5, 1), date(2026, 8, 15),
    date(2026, 10, 2), date(2026, 11, 10), date(2026, 12, 25),
}


def now_ist() -> datetime:
    return datetime.now(IST)


class NSECalendar:
    def __init__(self, holidays: set[date] | None = None) -> None:
        self.holidays = holidays if holidays is not None else NSE_HOLIDAYS

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def previous_trading_day(self, d: date) -> date:
        cur = d - timedelta(days=1)
        while not self.is_trading_day(cur):
            cur -= timedelta(days=1)
        return cur

    def is_expiry_day(self, d: date, expiry_weekday: int) -> bool:
        """True when ``d`` is the weekly-expiry weekday (and a trading day).

        If the natural expiry weekday is a holiday, NSE shifts expiry to the
        previous trading day — this handles that common case.
        """
        if not self.is_trading_day(d):
            return False
        if d.weekday() == expiry_weekday:
            return True
        # Expiry weekday fell on a holiday -> shifted to the prior trading day.
        nxt = d + timedelta(days=1)
        while nxt.weekday() != expiry_weekday:
            if nxt.weekday() < 5 and nxt not in self.holidays:
                return False
            nxt += timedelta(days=1)
        return nxt in self.holidays
