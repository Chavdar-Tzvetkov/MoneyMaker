from __future__ import annotations

"""
Simple PnL reconciliation helper.

Usage (example):
    from reports_pnl_reconciliation import dump_daily_pnl
    dump_daily_pnl()

This will print the contents of the DailyPnL table ordered by date so you
can compare against MT5 / Trading212 statements for the same period.
"""

from typing import Optional, Iterable, Tuple, Dict, Any
from datetime import date

from db.db_session import SessionLocal
from db.models import DailyPnL


def iter_daily_pnl(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Iterable[Tuple[date, float, float, float]]:
    """
    Yield (date, pnl_total, pnl_fx, pnl_equity) tuples for rows in DailyPnL between start and end
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
            pnl_total = float(row.pnl or 0.0)
            pnl_fx = float(getattr(row, "pnl_fx", 0.0) or 0.0)
            pnl_equity = float(getattr(row, "pnl_equity", 0.0) or 0.0)
            yield (row.date, pnl_total, pnl_fx, pnl_equity)
    finally:
        s.close()


def dump_daily_pnl(
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> None:
    """
    Print a CSV-style report of DailyPnL split by platform:
        2026-03-01, total=125.43, fx=90.10, equity=35.33, recon_error=0.00
        2026-03-02, total=-45.10, fx=-20.00, equity=-25.10, recon_error=0.00

    You can then align this with broker statements day-by-day.
    """
    for d, total, pnl_fx, pnl_eq in iter_daily_pnl(start=start, end=end):
        recon_error = total - (pnl_fx + pnl_eq)
        print(
            f"{d.isoformat()}, total={total:.2f}, fx={pnl_fx:.2f}, "
            f"equity={pnl_eq:.2f}, recon_error={recon_error:.2f}"
        )


def summarize_quality(
    start: Optional[date] = None,
    end: Optional[date] = None,
    *,
    profit_factor_min: float = 1.10,
    max_daily_drawdown_limit: float = 0.0,
    max_recon_error_abs: float = 1e-6,
) -> Dict[str, Any]:
    """
    Build acceptance-gate quality metrics from DailyPnL history.
    """
    rows = list(iter_daily_pnl(start=start, end=end))
    if not rows:
        return {
            "rows": 0,
            "profit_factor": 0.0,
            "max_daily_drawdown": 0.0,
            "max_recon_error_abs": 0.0,
            "pass_profit_factor": False,
            "pass_drawdown": False,
            "pass_reconciliation": False,
            "all_pass": False,
        }

    gross_profit = sum(t for _, t, _, _ in rows if t > 0.0)
    gross_loss = -sum(t for _, t, _, _ in rows if t < 0.0)
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    max_daily_drawdown = min((t for _, t, _, _ in rows), default=0.0)
    max_recon_error = max(abs(t - (fx + eq)) for _, t, fx, eq in rows)

    pass_pf = profit_factor >= profit_factor_min
    pass_dd = max_daily_drawdown >= -abs(max_daily_drawdown_limit)
    pass_recon = max_recon_error <= max_recon_error_abs

    return {
        "rows": len(rows),
        "profit_factor": profit_factor,
        "max_daily_drawdown": max_daily_drawdown,
        "max_recon_error_abs": max_recon_error,
        "pass_profit_factor": pass_pf,
        "pass_drawdown": pass_dd,
        "pass_reconciliation": pass_recon,
        "all_pass": pass_pf and pass_dd and pass_recon,
    }


def dump_quality_report(
    start: Optional[date] = None,
    end: Optional[date] = None,
    *,
    profit_factor_min: float = 1.10,
    max_daily_drawdown_limit: float = 0.0,
    max_recon_error_abs: float = 1e-6,
) -> None:
    """
    Print acceptance-gate quality metrics and pass/fail status.
    """
    m = summarize_quality(
        start=start,
        end=end,
        profit_factor_min=profit_factor_min,
        max_daily_drawdown_limit=max_daily_drawdown_limit,
        max_recon_error_abs=max_recon_error_abs,
    )
    print(
        f"rows={m['rows']}, profit_factor={m['profit_factor']:.4f}, "
        f"max_daily_drawdown={m['max_daily_drawdown']:.2f}, "
        f"max_recon_error_abs={m['max_recon_error_abs']:.6f}"
    )
    print(
        f"PASS profit_factor({profit_factor_min})={m['pass_profit_factor']} | "
        f"drawdown({-abs(max_daily_drawdown_limit):.2f})={m['pass_drawdown']} | "
        f"reconciliation({max_recon_error_abs})={m['pass_reconciliation']} | "
        f"ALL={m['all_pass']}"
    )

