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
    Set today's DailyPnL row to 0. Returns True if a row was updated or created.
    Use when you want to clear the circuit breaker's "today" loss (e.g. after a bad run or data fix).
    """
    s = SessionLocal()
    try:
        today = _today_user()
        row = s.query(DailyPnL).filter(DailyPnL.date == today).first()
        if row:
            row.pnl = 0.0
        else:
            s.add(DailyPnL(date=today, pnl=0.0))
        s.commit()
        return True
    except SQLAlchemyError:
        s.rollback()
        return False
    finally:
        s.close()


def add_to_daily_pnl(delta: float) -> None:
    """
    Low-level helper: add realized PnL to today's aggregate row in DailyPnL.
    This function is the single writer for the DailyPnL table.
    """
    s = SessionLocal()
    try:
        row = s.query(DailyPnL).filter(DailyPnL.date == date.today()).first()
        if not row:
            row = DailyPnL(date=date.today(), pnl=0.0)
            s.add(row)
        row.pnl = float(row.pnl or 0.0) + float(delta or 0.0)
        s.commit()
    except SQLAlchemyError:
        s.rollback()
    finally:
        s.close()


def record_fx_close_profit(realized_profit: float) -> float:
    """
    Record realized FX PnL (as reported by MT5) into DailyPnL.

    `realized_profit` is expected to be the broker's net profit for the
    closed position, already in account currency (i.e., MT5 deal.profit).
    Returns the value actually added for convenience.
    """
    profit = float(realized_profit or 0.0)
    if profit != 0.0:
        add_to_daily_pnl(profit)
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
        add_to_daily_pnl(net)

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
