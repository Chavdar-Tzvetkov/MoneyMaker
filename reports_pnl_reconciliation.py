from __future__ import annotations

"""
Simple PnL reconciliation helper.

Usage (example):
    from reports_pnl_reconciliation import dump_daily_pnl
    dump_daily_pnl()

This will print the contents of the DailyPnL table ordered by date so you
can compare against MT5 / Trading212 statements for the same period.
"""

from typing import Optional, Iterable, Tuple
from datetime import date

from db.db_session import SessionLocal
from db.models import DailyPnL


def iter_daily_pnl(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Iterable[Tuple[date, float]]:
    """
    Yield (date, pnl) tuples for rows in DailyPnL between start and end
    (inclusive). If start/end are omitted, all rows are returned.
    """
    s = SessionLocal()
    try:
        q = s.query(DailyPnL)
        if start is not None:
            q = q.filter(DailyPnL.date >= start)
        if end is not None:
            q = q.filter(DailyPnL.date <= end)
        q = q.order_by(DailyPnL.date.asc())
        for row in q.all():
            yield (row.date, float(row.pnl or 0.0))
    finally:
        s.close()


def dump_daily_pnl(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> None:
    """
    Print a simple CSV-style report of DailyPnL, e.g.:
        2026-03-01, 125.43
        2026-03-02, -45.10

    You can then align this with broker statements day-by-day.
    """
    for d, pnl in iter_daily_pnl(start=start, end=end):
        print(f"{d.isoformat()}, {pnl:.2f}")

