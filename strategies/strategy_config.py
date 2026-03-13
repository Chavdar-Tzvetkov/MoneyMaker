# strategies/strategy_config.py
from __future__ import annotations

import os
from datetime import datetime, date, timedelta
from typing import Optional

import pytz
from sqlalchemy import text
from db.db_session import SessionLocal
from db.models import DailyPnL
import config
from utils.symbols import is_forex

# When DailyPnL table lacks pnl_fx/pnl_equity columns we use legacy reads (only pnl). Set to True on first 42S22.
_daily_pnl_legacy: Optional[bool] = None
_daily_pnl_legacy_logged: bool = False

# ---------------------------
# Public knobs
# ---------------------------

# Base strategy name used when things are normal; AI/meta-decider can still override per symbol.
ACTIVE_STRATEGY = "SMA"  # or "SCALPING"

# Switch to SCALPING if daily PnL (as fraction of equity) <= DAILY_LOSS_LIMIT (e.g., -15%).
DAILY_LOSS_LIMIT = -0.15

# Hard circuit breaker: if daily PnL (as fraction of equity) <= HALT_THRESHOLD, pause for HALT_MINUTES.
# Override in .env (e.g. CIRCUIT_BREAKER_HALT_THRESHOLD=-0.35 to only halt at -35%).
HALT_THRESHOLD = float(os.getenv("CIRCUIT_BREAKER_HALT_THRESHOLD", "-0.20"))
HALT_MINUTES = int(os.getenv("CIRCUIT_BREAKER_HALT_MINUTES", "60"))

# Circuit breaker can be disabled (e.g. for testing). When disabled, is_trading_halted() is always False.
CIRCUIT_BREAKER_ENABLED = os.getenv("CIRCUIT_BREAKER_ENABLED", "1").strip().lower() in ("1", "true", "yes")
# Clear any existing halt on startup (one-shot per process). Useful after a restart to resume trading.
CLEAR_HALT_ON_START = os.getenv("CLEAR_HALT_ON_START", "0").strip().lower() in ("1", "true", "yes")

# Avoid rapid flip-flopping: minimum time between SMA<->SCALPING switches.
COOLDOWN_BETWEEN_SWITCHES_SEC = 30 * 60  # 30 minutes

# ---------------------------
# Module state
# ---------------------------

_last_switch_utc: Optional[datetime] = None
_halt_until_utc_fx: Optional[datetime] = None
_halt_until_utc_equity: Optional[datetime] = None
_last_pnl_date: Optional[date] = None  # to detect day rollovers and clear halts automatically
_cleared_halt_on_start: bool = False  # one-shot for CLEAR_HALT_ON_START


# ---------------------------
# DB helpers
# ---------------------------

def get_today_pnl() -> float:
    """Today's total PnL (fx + equity). 'Today' is BASE_TIMEZONE calendar day."""
    session = SessionLocal()
    try:
        tz = pytz.timezone(getattr(config, "BASE_TIMEZONE", "Europe/Sofia"))
        today = datetime.now(tz).date()
        row = session.query(DailyPnL).filter(DailyPnL.date == today).first()
        return float(row.pnl) if row else 0.0
    except Exception as e:
        print(f"[Strategy][DB] Failed to read DailyPnL: {e}")
        return 0.0
    finally:
        session.close()


def get_today_pnl_fx() -> float:
    """Today's FX (MT5) PnL only. For per-account circuit breaker."""
    session = SessionLocal()
    try:
        tz = pytz.timezone(getattr(config, "BASE_TIMEZONE", "Europe/Sofia"))
        today = datetime.now(tz).date()
        row = session.query(DailyPnL).filter(DailyPnL.date == today).first()
        if not row:
            return 0.0
        return float(getattr(row, "pnl_fx", None) or 0.0)
    except Exception as e:
        print(f"[Strategy][DB] Failed to read DailyPnL pnl_fx: {e}")
        return 0.0
    finally:
        session.close()


def get_today_pnl_equity() -> float:
    """Today's equity (T212) PnL only. For per-account circuit breaker."""
    session = SessionLocal()
    try:
        tz = pytz.timezone(getattr(config, "BASE_TIMEZONE", "Europe/Sofia"))
        today = datetime.now(tz).date()
        row = session.query(DailyPnL).filter(DailyPnL.date == today).first()
        if not row:
            return 0.0
        return float(getattr(row, "pnl_equity", None) or 0.0)
    except Exception as e:
        print(f"[Strategy][DB] Failed to read DailyPnL pnl_equity: {e}")
        return 0.0
    finally:
        session.close()


# ---------------------------
# State helpers
# ---------------------------

def _utcnow() -> datetime:
    return datetime.utcnow()


def _today_user() -> date:
    """Calendar day in user's base timezone (e.g. Europe/Sofia for Bulgaria)."""
    try:
        tz = pytz.timezone(getattr(config, "BASE_TIMEZONE", "Europe/Sofia"))
        return datetime.now(tz).date()
    except Exception:
        return date.today()


def _halt_active_fx() -> bool:
    global _halt_until_utc_fx, _last_pnl_date
    if not CIRCUIT_BREAKER_ENABLED:
        return False
    now = _utcnow()
    today = _today_user()
    if _last_pnl_date is not None and _last_pnl_date != today:
        _clear_halt_fx()
        _last_pnl_date = today
    return _halt_until_utc_fx is not None and now < _halt_until_utc_fx


def _halt_active_equity() -> bool:
    global _halt_until_utc_equity, _last_pnl_date
    if not CIRCUIT_BREAKER_ENABLED:
        return False
    now = _utcnow()
    today = _today_user()
    if _last_pnl_date is not None and _last_pnl_date != today:
        _clear_halt_equity()
        _last_pnl_date = today
    return _halt_until_utc_equity is not None and now < _halt_until_utc_equity


def is_trading_halted(symbol: Optional[str] = None) -> bool:
    """
    True if the relevant circuit breaker is active for this symbol.
    FX symbols → MT5 halt. Equity symbols → T212 halt. No symbol → True if either halted.
    """
    if symbol is None:
        return _halt_active_fx() or _halt_active_equity()
    return _halt_active_fx() if is_forex(symbol) else _halt_active_equity()


def is_trading_halted_fx() -> bool:
    """True when MT5 (FX) circuit breaker is active."""
    return _halt_active_fx()


def is_trading_halted_equity() -> bool:
    """True when T212 (equity) circuit breaker is active."""
    return _halt_active_equity()


def _trip_halt_fx(minutes: int) -> None:
    global _halt_until_utc_fx, _last_pnl_date
    _halt_until_utc_fx = _utcnow() + timedelta(minutes=minutes)
    _last_pnl_date = _today_user()
    print(f"[Strategy][HALT] MT5 (FX) circuit breaker → halting FX for {minutes} min (until {_halt_until_utc_fx:%Y-%m-%d %H:%M:%S} UTC)")


def _trip_halt_equity(minutes: int) -> None:
    global _halt_until_utc_equity, _last_pnl_date
    _halt_until_utc_equity = _utcnow() + timedelta(minutes=minutes)
    _last_pnl_date = _today_user()
    print(f"[Strategy][HALT] T212 (equity) circuit breaker → halting equity for {minutes} min (until {_halt_until_utc_equity:%Y-%m-%d %H:%M:%S} UTC)")


def _clear_halt_fx() -> None:
    global _halt_until_utc_fx
    if _halt_until_utc_fx is not None:
        print("[Strategy][HALT] Clearing MT5 (FX) halt.")
    _halt_until_utc_fx = None


def _clear_halt_equity() -> None:
    global _halt_until_utc_equity
    if _halt_until_utc_equity is not None:
        print("[Strategy][HALT] Clearing T212 (equity) halt.")
    _halt_until_utc_equity = None


def _clear_halt() -> None:
    _clear_halt_fx()
    _clear_halt_equity()

def _can_switch() -> bool:
    global _last_switch_utc
    if _last_switch_utc is None:
        return True
    return (_utcnow() - _last_switch_utc).total_seconds() >= COOLDOWN_BETWEEN_SWITCHES_SEC


# ---------------------------
# Public API (backward compatible)
# ---------------------------

def switch_strategy_if_needed(
    mt5_equity: Optional[float] = None,
    t212_equity: Optional[float] = None,
) -> str:
    """
    Per-account circuit breakers: MT5 and T212 are separate.
    1) Trip FX breaker when daily FX PnL / MT5 equity <= HALT_THRESHOLD.
    2) Trip equity breaker when daily equity PnL / T212 equity <= HALT_THRESHOLD.
    3) SMA/SCALPING switch uses combined PnL and combined equity for one global strategy.
    Returns the current ACTIVE_STRATEGY (string).
    """
    global ACTIVE_STRATEGY, _last_switch_utc, _last_pnl_date, _cleared_halt_on_start

    _last_pnl_date = _today_user()

    # Clear both halts once on start if requested
    if CLEAR_HALT_ON_START and not _cleared_halt_on_start and (_halt_until_utc_fx is not None or _halt_until_utc_equity is not None):
        _clear_halt()
        _cleared_halt_on_start = True

    pnl_fx = get_today_pnl_fx()
    pnl_equity = get_today_pnl_equity()
    pnl_total = get_today_pnl()

    # 1) FX circuit breaker (MT5 account only)
    mt5_eq = float(mt5_equity or 0.0) if mt5_equity is not None else 0.0
    if CIRCUIT_BREAKER_ENABLED and mt5_eq > 0:
        pnl_fx_frac = pnl_fx / mt5_eq
        if pnl_fx_frac <= HALT_THRESHOLD:
            if not _halt_active_fx():
                print(f"[Strategy][HALT] MT5: daily FX PnL {pnl_fx:.2f} USD = {pnl_fx_frac*100:.1f}% of {mt5_eq:.0f} → halting FX {HALT_MINUTES} min")
                _trip_halt_fx(HALT_MINUTES)
        else:
            if _halt_active_fx():
                _clear_halt_fx()

    # 2) Equity circuit breaker (T212 account only)
    t212_eq = float(t212_equity or 0.0) if t212_equity is not None else 0.0
    if CIRCUIT_BREAKER_ENABLED and t212_eq > 0:
        pnl_equity_frac = pnl_equity / t212_eq
        if pnl_equity_frac <= HALT_THRESHOLD:
            if not _halt_active_equity():
                print(f"[Strategy][HALT] T212: daily equity PnL {pnl_equity:.2f} USD = {pnl_equity_frac*100:.1f}% of {t212_eq:.0f} → halting equity {HALT_MINUTES} min")
                _trip_halt_equity(HALT_MINUTES)
        else:
            if _halt_active_equity():
                _clear_halt_equity()

    # 3) Strategy switching (SMA/SCALPING) uses combined PnL and combined equity
    combined_eq = mt5_eq + t212_eq
    pnl = (pnl_total / combined_eq) if combined_eq > 0 else 0.0
    if pnl <= DAILY_LOSS_LIMIT and ACTIVE_STRATEGY != "SCALPING":
        if _can_switch():
            ACTIVE_STRATEGY = "SCALPING"
            _last_switch_utc = _utcnow()
            print(f"[Strategy] Switching to SCALPING due to daily loss ({pnl*100:.2f}%)")
    elif pnl > 0 and ACTIVE_STRATEGY != "SMA":
        if _can_switch():
            ACTIVE_STRATEGY = "SMA"
            _last_switch_utc = _utcnow()
            print(f"[Strategy] Switching back to SMA (PnL {pnl*100:.2f}%)")

    return ACTIVE_STRATEGY


def describe_state() -> str:
    """
    Human-readable snapshot of the strategy controller.
    """
    halt_fx = "ACTIVE" if _halt_active_fx() else "OFF"
    halt_eq = "ACTIVE" if _halt_active_equity() else "OFF"
    until_fx = _halt_until_utc_fx.strftime("%Y-%m-%d %H:%M UTC") if _halt_until_utc_fx else "-"
    until_eq = _halt_until_utc_equity.strftime("%Y-%m-%d %H:%M UTC") if _halt_until_utc_equity else "-"
    last_sw = _last_switch_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if _last_switch_utc else "-"
    return (
        f"Strategy={ACTIVE_STRATEGY} | "
        f"HALT_MT5={halt_fx} (until {until_fx}) | HALT_T212={halt_eq} (until {until_eq}) | "
        f"LastSwitch={last_sw}"
    )
