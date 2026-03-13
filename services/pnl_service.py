# services/pnl_service.py
from datetime import date
from typing import Optional

import pytz
from sqlalchemy.exc import SQLAlchemyError

from db.db_session import SessionLocal
from db.models import DailyPnL, TradeLog


def _today_user() -> date:
    """Calendar day in user's base timezone (for consistency with strategy_config)."""
    try:
        import config
        tz = pytz.timezone(getattr(config, "BASE_TIMEZONE", "Europe/Sofia"))
        from datetime import datetime
        return datetime.now(tz).date()
    except Exception:
        return date.today()


def reset_today_pnl() -> bool:
    """
    Set today's DailyPnL row to 0 (pnl, pnl_fx, pnl_equity). Returns True if a row was updated or created.
    """
    s = SessionLocal()
    try:
        today = _today_user()
        row = s.query(DailyPnL).filter(DailyPnL.date == today).first()
        if row:
            row.pnl = 0.0
            if hasattr(row, "pnl_fx"):
                row.pnl_fx = 0.0
            if hasattr(row, "pnl_equity"):
                row.pnl_equity = 0.0
        else:
            row = DailyPnL(date=today, pnl=0.0, pnl_fx=0.0, pnl_equity=0.0)
            s.add(row)
        s.commit()
        return True
    except SQLAlchemyError:
        s.rollback()
        return False
    finally:
        s.close()


def _ensure_row(s, today: date):
    row = s.query(DailyPnL).filter(DailyPnL.date == today).first()
    if not row:
        row = DailyPnL(date=today, pnl=0.0, pnl_fx=0.0, pnl_equity=0.0)
        s.add(row)
    return row


def add_to_daily_pnl(delta: float) -> None:
    """
    Low-level: add to today's total pnl only (legacy). Prefer add_to_daily_pnl_fx / add_to_daily_pnl_equity.
    """
    s = SessionLocal()
    try:
        today = _today_user()
        row = _ensure_row(s, today)
        # Only update total pnl; fx/equity are updated by add_to_daily_pnl_fx/equity
        row.pnl = float(row.pnl or 0.0) + float(delta or 0.0)
        s.commit()
    except SQLAlchemyError:
        s.rollback()
    finally:
        s.close()


def add_to_daily_pnl_fx(delta: float) -> None:
    """Add realized FX (MT5) PnL to today's row. Keeps pnl_fx and pnl (total) in sync."""
    s = SessionLocal()
    try:
        today = _today_user()
        row = _ensure_row(s, today)
        pnl_fx = getattr(row, "pnl_fx", None)
        row.pnl_fx = float(pnl_fx or 0.0) + float(delta or 0.0)
        row.pnl = float(row.pnl or 0.0) + float(delta or 0.0)
        s.commit()
    except SQLAlchemyError:
        s.rollback()
    finally:
        s.close()


def add_to_daily_pnl_equity(delta: float) -> None:
    """Add realized equity (T212) PnL to today's row. Keeps pnl_equity and pnl (total) in sync."""
    s = SessionLocal()
    try:
        today = _today_user()
        row = _ensure_row(s, today)
        pnl_eq = getattr(row, "pnl_equity", None)
        row.pnl_equity = float(pnl_eq or 0.0) + float(delta or 0.0)
        row.pnl = float(row.pnl or 0.0) + float(delta or 0.0)
        s.commit()
    except SQLAlchemyError:
        s.rollback()
    finally:
        s.close()


def record_fx_close_profit(realized_profit: float) -> float:
    """
    Record realized FX PnL (MT5) into DailyPnL (pnl_fx + pnl).
    """
    profit = float(realized_profit or 0.0)
    if profit != 0.0:
        add_to_daily_pnl_fx(profit)
    return profit


def record_equity_close(
    symbol: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    *,
    fees: float = 0.0,
    currency: Optional[str] = None,
) -> float:
    """
    Centralized equity realized PnL computation and aggregation.

    - `entry_price` and `exit_price` should be in the same currency.
    - `quantity` is positive for a long position being closed.
    - `fees` is total cost (commissions, transaction fees, etc.) expressed
      in the same currency as prices.
    - `currency` is reserved for future cross-currency conversion; it is
      currently informational only.

    Returns the net PnL (after fees) that was added to DailyPnL.
    """
    qty = float(quantity or 0.0)
    if qty == 0.0:
        return 0.0

    entry = float(entry_price or 0.0)
    close = float(exit_price or 0.0)
    if entry <= 0.0 or close <= 0.0:
        return 0.0

    gross = (close - entry) * qty
    net = gross - float(fees or 0.0)

    if net != 0.0:
        add_to_daily_pnl_equity(net)

    # Best-effort enrichment of TradeLog for later analysis (no hard dependency).
    try:
        s = SessionLocal()
        try:
            log = TradeLog(
                symbol=symbol,
                action="SELL",
                price=close,
                quantity=int(qty),
                currency=currency,
                fees=float(fees or 0.0) or None,
                realised_pnl=net,
            )
            s.add(log)
            s.commit()
        except SQLAlchemyError:
            s.rollback()
        finally:
            s.close()
    except Exception:
        # Logging enrichment must never break trading.
        pass

    return net
