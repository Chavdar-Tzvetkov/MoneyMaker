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


def minutes_until_us_equity_session_end(symbol: str, *, as_of_utc: datetime | None = None) -> float | None:
    """
    Minutes until the scheduled US cash equity session close (16:00 US/Eastern,
    or 13:00 on early-close days). Only defined while the symbol is in regular
    US equity hours (09:30–close); returns None for FX/crypto, weekends/holidays,
    pre-market, or after the closing time.

    Used to flatten or block new risk before the bell and avoid weekend gap
    exposure when the bot cannot manage software stops.
    """
    from utils.symbols import is_crypto, is_forex

    symbol = (symbol or "").upper()
    if is_forex(symbol) or is_crypto(symbol):
        return None

    if as_of_utc is not None:
        now_utc = as_of_utc if as_of_utc.tzinfo else as_of_utc.replace(tzinfo=pytz.UTC)
        now_utc = now_utc.astimezone(pytz.UTC)
    else:
        now_utc = datetime.now(pytz.UTC)
    tz_est = pytz.timezone("America/New_York")
    now_est = now_utc.astimezone(tz_est)

    if is_us_equity_holiday(now_est.date()):
        return None
    if now_est.weekday() >= 5:
        return None

    close_cutoff = time(16, 0)
    if is_us_equity_early_close(now_est.date()):
        close_cutoff = time(13, 0)

    t = now_est.time()
    if t < time(9, 30) or t > close_cutoff:
        return None

    close_est = tz_est.localize(datetime.combine(now_est.date(), close_cutoff))
    return max(0.0, (close_est - now_est).total_seconds() / 60.0)


def minutes_until_fx_weekend_close(symbol: str, *, as_of_utc: datetime | None = None) -> float | None:
    """
    Minutes until the standard **Friday 22:00 UTC** FX week rollover used by
    `is_market_open` (24/5 model). Only non-negative on **Friday UTC** while the
    synthetic session is still open (before 22:00); otherwise None.

    Use this to flatten MT5 positions *before* weekend liquidity drops and
    Sunday gaps, while quotes/orders may still work.
    """
    from utils.symbols import is_forex

    symbol = (symbol or "").upper()
    if not is_forex(symbol):
        return None

    if as_of_utc is not None:
        now_utc = as_of_utc if as_of_utc.tzinfo else as_of_utc.replace(tzinfo=pytz.UTC)
        now_utc = now_utc.astimezone(pytz.UTC)
    else:
        now_utc = datetime.now(pytz.UTC)

    if is_fx_holiday(now_utc.date()):
        return None
    if now_utc.weekday() != 4:
        return None

    close_utc = datetime(now_utc.year, now_utc.month, now_utc.day, 22, 0, 0, tzinfo=pytz.UTC)
    if now_utc >= close_utc:
        return None
    return max(0.0, (close_utc - now_utc).total_seconds() / 60.0)


def is_forex_session_now(symbol: str) -> bool:
    """True if symbol is FX and within 24/5 + non-holiday (convenience wrapper)."""
    return is_market_open(symbol)


def is_us_equity_session_now(symbol: str) -> bool:
    """True if symbol is US equity and within market hours + not holiday (convenience wrapper)."""
    return is_market_open(symbol)
