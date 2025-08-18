# strategies/strategy_config.py
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Optional

from db.db_session import SessionLocal
from db.models import DailyPnL

# ---------------------------
# Public knobs
# ---------------------------

# Base strategy name used when things are normal; AI/meta-decider can still override per symbol.
ACTIVE_STRATEGY = "SMA"  # or "SCALPING"

# Switch to SCALPING if daily PnL <= DAILY_LOSS_LIMIT (e.g., -15%).
DAILY_LOSS_LIMIT = -0.15

# Hard circuit breaker: if daily PnL <= HALT_THRESHOLD, pause trading for HALT_MINUTES.
HALT_THRESHOLD = -0.20
HALT_MINUTES = 60  # pause for 60 minutes when breaker trips

# Avoid rapid flip-flopping: minimum time between SMA<->SCALPING switches.
COOLDOWN_BETWEEN_SWITCHES_SEC = 30 * 60  # 30 minutes

# ---------------------------
# Module state
# ---------------------------

_last_switch_utc: Optional[datetime] = None
_halt_until_utc: Optional[datetime] = None
_last_pnl_date: Optional[date] = None  # to detect day rollovers and clear halts automatically


# ---------------------------
# DB helpers
# ---------------------------

def get_today_pnl() -> float:
    """
    Read today's PnL from DB. If no row yet, returns 0.0
    """
    session = SessionLocal()
    try:
        today = date.today()
        pnl_entry = session.query(DailyPnL).filter(DailyPnL.date == today).first()
        return float(pnl_entry.pnl) if pnl_entry else 0.0
    except Exception as e:
        print(f"[Strategy][DB] Failed to read DailyPnL: {e}")
        return 0.0
    finally:
        session.close()


# ---------------------------
# State helpers
# ---------------------------

def _utcnow() -> datetime:
    return datetime.utcnow()

def is_trading_halted() -> bool:
    """
    True when the circuit breaker has been tripped and the pause window is still active.
    The pause automatically clears on a new UTC day (fresh PnL).
    """
    global _halt_until_utc, _last_pnl_date
    now = _utcnow()
    today = date.today()

    # Clear breaker on day change
    if _last_pnl_date is not None and _last_pnl_date != today:
        _clear_halt()
        _last_pnl_date = today

    return _halt_until_utc is not None and now < _halt_until_utc

def _trip_halt(minutes: int) -> None:
    global _halt_until_utc, _last_pnl_date
    _halt_until_utc = _utcnow() + timedelta(minutes=minutes)
    _last_pnl_date = date.today()
    print(f"[Strategy][HALT] Circuit breaker tripped → halting trading for {minutes} min (until {_halt_until_utc:%Y-%m-%d %H:%M:%S} UTC)")

def _clear_halt() -> None:
    global _halt_until_utc
    if _halt_until_utc is not None:
        print("[Strategy][HALT] Clearing trading halt.")
    _halt_until_utc = None

def _can_switch() -> bool:
    global _last_switch_utc
    if _last_switch_utc is None:
        return True
    return (_utcnow() - _last_switch_utc).total_seconds() >= COOLDOWN_BETWEEN_SWITCHES_SEC


# ---------------------------
# Public API (backward compatible)
# ---------------------------

def switch_strategy_if_needed() -> str:
    """
    Called by the main loop each pass.
    1) Trips/maintains a circuit breaker if PnL breaches HALT_THRESHOLD.
    2) Switches between SMA/SCALPING based on DAILY_LOSS_LIMIT with cooldown.
    Returns the current ACTIVE_STRATEGY (string).
    """
    global ACTIVE_STRATEGY, _last_switch_utc, _last_pnl_date

    pnl = get_today_pnl()
    _last_pnl_date = date.today()

    # 1) Circuit breaker
    if pnl <= HALT_THRESHOLD:
        if not is_trading_halted():
            _trip_halt(HALT_MINUTES)
        # When halted, we still return the current strategy name (loop will check is_trading_halted()).
        return ACTIVE_STRATEGY
    else:
        # If we've recovered above threshold, clear any prior halt.
        if is_trading_halted():
            _clear_halt()

    # 2) Strategy switching with cooldown
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
    halt = "ACTIVE" if is_trading_halted() else "OFF"
    until = _halt_until_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if _halt_until_utc else "-"
    last_sw = _last_switch_utc.strftime("%Y-%m-%d %H:%M:%S UTC") if _last_switch_utc else "-"
    return (
        f"Strategy={ACTIVE_STRATEGY} | "
        f"HALT={halt} (until {until}) | "
        f"SwitchCooldown={COOLDOWN_BETWEEN_SWITCHES_SEC}s | "
        f"LastSwitch={last_sw}"
    )
