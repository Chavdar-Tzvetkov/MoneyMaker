# utils/market_hours.py
"""
Trading hours and non-trading days for MT5 (forex) and Trading212 (US equities).
Respects official holidays and early-close days for both markets.
"""
from __future__ import annotations
from datetime import datetime, time
import pytz

from utils.market_calendar import (
    is_us_equity_holiday,
    is_us_equity_early_close,
    is_fx_holiday,
)


def is_market_open(symbol: str, *, as_of_utc: datetime | None = None) -> bool:
    """
    Returns True only when the given symbol is within official trading hours
    and the day is not a holiday/non-trading day.

    - Crypto: 24/7
    - Forex (MT5): 24/5 UTC (Sun 22:00 UTC → Fri 22:00 UTC), excluding FX holiday dates
    - Stocks (Trading212 / US): 09:30–16:00 US/Eastern Mon–Fri, excluding NYSE/NASDAQ holidays;
      on early-close days, trading allowed only until 13:00 ET.
    """
    symbol = (symbol or "").upper()
    if as_of_utc is not None:
        now_utc = as_of_utc if as_of_utc.tzinfo else as_of_utc.replace(tzinfo=pytz.UTC)
        now_utc = now_utc.astimezone(pytz.UTC)
    else:
        now_utc = datetime.now(pytz.UTC)
    tz_est = pytz.timezone("America/New_York")
    now_est = now_utc.astimezone(tz_est)

    # Crypto: always on
    if symbol in ("BTC-USD", "ETH-USD"):
        return True

    # Forex (treat '=X' or 6-letter pairs as FX)
    if symbol.endswith("=X") or (len(symbol) == 6 and symbol.isalpha()):
        if is_fx_holiday(now_utc.date()):
            return False
        weekday_utc = now_utc.weekday()
        if 0 <= weekday_utc <= 3:
            return True
        if weekday_utc == 4:
            return now_utc.time() <= time(22, 0)
        if weekday_utc == 6:
            return now_utc.time() >= time(22, 0)
        return False

    # US equities (Trading212: NYSE/NASDAQ hours and calendar)
    if is_us_equity_holiday(now_est.date()):
        return False
    if now_est.weekday() >= 5:
        return False
    # Regular hours 09:30–16:00 ET
    close_cutoff = time(16, 0)
    if is_us_equity_early_close(now_est.date()):
        close_cutoff = time(13, 0)
    return time(9, 30) <= now_est.time() <= close_cutoff


def is_forex_session_now(symbol: str) -> bool:
    """True if symbol is FX and within 24/5 + non-holiday (convenience wrapper)."""
    return is_market_open(symbol)


def is_us_equity_session_now(symbol: str) -> bool:
    """True if symbol is US equity and within market hours + not holiday (convenience wrapper)."""
    return is_market_open(symbol)
