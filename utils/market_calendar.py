# utils/market_calendar.py
"""
Trading calendar: US equity (NYSE/NASDAQ) and FX holiday/closure dates.
Used by market_hours to block trading on official non-trading days.
Update US_EQUITY_CLOSED and FX_CLOSED annually or load from a file.
"""
from __future__ import annotations
from datetime import date

# US stock market full closures (NYSE/NASDAQ) — add future years as needed
US_EQUITY_CLOSED: set[date] = {
    # 2025
    date(2025, 1, 1),    # New Year's Day
    date(2025, 1, 20),   # Martin Luther King Jr. Day
    date(2025, 2, 17),   # Washington's Birthday
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 26),   # Memorial Day
    date(2025, 6, 19),   # Juneteenth
    date(2025, 7, 4),    # Independence Day
    date(2025, 9, 1),    # Labor Day
    date(2025, 11, 27),  # Thanksgiving
    date(2025, 11, 28),  # Day After Thanksgiving
    date(2025, 12, 25),  # Christmas
    # 2026
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Presidents' Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 11, 27),  # Day After Thanksgiving
    date(2026, 12, 25),  # Christmas
    # 2027 (sample)
    date(2027, 1, 1),
    date(2027, 12, 25),
}

# Early close days (market closes 13:00 ET) — optional: treat as open but you could restrict later
US_EQUITY_EARLY_CLOSE: set[date] = {
    date(2025, 7, 3),    # Independence Day eve
    date(2025, 12, 24),  # Christmas Eve
    date(2026, 12, 24),  # Christmas Eve
}

# Forex: many brokers close or liquidity is very thin on these days (UTC date)
FX_CLOSED: set[date] = {
    date(2025, 1, 1), date(2026, 1, 1), date(2027, 1, 1),
    date(2025, 12, 25), date(2025, 12, 26),
    date(2026, 12, 25), date(2026, 12, 26),
    date(2027, 12, 25), date(2027, 12, 26),
}


def is_us_equity_holiday(d: date | None = None) -> bool:
    """True if US equity markets are fully closed that day."""
    d = d or date.today()
    return d in US_EQUITY_CLOSED


def is_us_equity_early_close(d: date | None = None) -> bool:
    """True if US equity markets have early close that day."""
    d = d or date.today()
    return d in US_EQUITY_EARLY_CLOSE


def is_fx_holiday(d: date | None = None) -> bool:
    """True if we treat FX as closed (e.g. Christmas, New Year)."""
    d = d or date.today()
    return d in FX_CLOSED
