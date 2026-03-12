# db/models.py

from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from sqlalchemy import Date

Base = declarative_base()


class DailyPnL(Base):
    __tablename__ = 'DailyPnL'

    id = Column(Integer, primary_key=True)
    date = Column(Date, unique=True, nullable=False)
    pnl = Column(Float, nullable=False, default=0.0)

class TradeLog(Base):
    __tablename__ = 'TradeLogs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), nullable=False)
    action = Column(String(10), nullable=False)  # BUY or SELL
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    # Optional metadata for richer PnL analysis (not required by core loop)
    currency = Column(String(10), nullable=True)
    fees = Column(Float, nullable=True)
    realised_pnl = Column(Float, nullable=True)


class Position(Base):
    __tablename__ = 'Positions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(50), unique=True, nullable=False)
    quantity = Column(Float, nullable=False)
    average_price = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)
