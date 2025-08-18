# services/pnl_service.py
from datetime import date
from sqlalchemy.exc import SQLAlchemyError
from db.db_session import SessionLocal
from db.models import DailyPnL

def add_to_daily_pnl(delta: float) -> None:
    """
    Add realized PnL to today's aggregate row in DailyPnL.
    Safe (fail-soft) and idempotent enough for per-close usage.
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
