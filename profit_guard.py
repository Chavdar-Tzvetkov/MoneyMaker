# profit_guard.py
import os
import time
from typing import Dict, Optional, Tuple

import yfinance as yf

from dotenv import load_dotenv
load_dotenv()

from db.db_session import SessionLocal
from db.models import Position  # assuming your model is named Position
from mt5_api import (
    get_current_price as mt5_price,
    close_position_market as mt5_close,
    get_position as mt5_get_position,
)
from trading212_api import get_equity_position_qty, place_market_order

# ---------------------------
# ENV CONFIG (with defaults)
# ---------------------------
PG_ENABLED = os.getenv("PG_ENABLED", "1") == "1"

# Per-asset thresholds (fall back to shared defaults if per-asset not set)
PG_MIN_PROFIT_PCT_FX   = float(os.getenv("PG_MIN_PROFIT_PCT_FX", os.getenv("PG_MIN_PROFIT_PCT", "0.0003")))  # 0.03%
PG_TP_REMAIN_FRAC_FX   = float(os.getenv("PG_TP_REMAIN_FRAC_FX", os.getenv("PG_TP_REMAIN_FRAC", "0.40")))    # ≥40%

PG_MIN_PROFIT_PCT_EQ   = float(os.getenv("PG_MIN_PROFIT_PCT_EQ", os.getenv("PG_MIN_PROFIT_PCT", "0.0020")))  # 0.20%
PG_TP_REMAIN_FRAC_EQ   = float(os.getenv("PG_TP_REMAIN_FRAC_EQ", os.getenv("PG_TP_REMAIN_FRAC", "0.30")))    # ≥30%

PG_REQUIRE_NOT_BUY     = os.getenv("PG_REQUIRE_NOT_BUY", "1") == "1"
PG_MIN_POS_AGE_SEC     = int(os.getenv("PG_MIN_POS_AGE_SEC", "60"))
PG_MAX_EQUITY_YF_PER_CYCLE = int(os.getenv("PG_MAX_EQUITY_YF_PER_CYCLE", "12"))

# If your Position model differs, tweak the field names here
def _iter_open_db_positions():
    """Yield (symbol, qty, avg_price, tp, opened_at) for ALL open positions in DB."""
    sess = SessionLocal()
    try:
        rows = (
            sess.query(Position)
            .filter(Position.quantity != 0)  # open only
            .all()
        )
        for r in rows:
            # db names might differ—adjust if needed
            yield (
                r.symbol,
                float(r.quantity or 0.0),
                float(r.avg_price or 0.0),
                float(getattr(r, "take_profit", 0.0) or 0.0),  # 0 if none
                getattr(r, "opened_at", None),
            )
    finally:
        sess.close()

def _is_fx(sym: str) -> bool:
    s = sym.strip().replace("_", "")
    if s.endswith("=X"):
        return True
    # 6-letter uppercase like EURUSD, USDCHF, GBPUSD, etc.
    return len(s) == 6 and s.isalpha() and s.upper() == s


def _equity_live_qty(sym: str) -> float:
    # Uses your T212 live read
    return float(get_equity_position_qty(sym) or 0.0)

def _yf_price(sym: str) -> Optional[float]:
    try:
        t = yf.Ticker(sym)
        p = t.fast_info.last_price
        if p and p > 0:
            return float(p)
        # Fallback: last close
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None

def _unrealized_return(open_price: float, cur_price: float, qty: float) -> float:
    if open_price <= 0:
        return 0.0
    r = (cur_price - open_price) / open_price
    return r if qty > 0 else -r  # invert for shorts (MT5 can short; T212 equities cannot)

def _tp_remaining_fraction(side_is_long: bool, open_price: float, cur_price: float, tp_price: float) -> Optional[float]:
    """How much of the TP distance remains (0..1+). None if no TP."""
    if not tp_price or tp_price == 0.0:
        return None
    # Define the full TP distance as |tp - open|
    full = abs(tp_price - open_price)
    if full <= 0:
        return None
    remain = abs(tp_price - cur_price)
    # If TP already crossed or nonsensical, return 0
    if remain <= 0:
        return 0.0
    return remain / full

def _age_ok(opened_at) -> bool:
    if not opened_at:
        return True
    try:
        age = time.time() - opened_at.timestamp()
        return age >= PG_MIN_POS_AGE_SEC
    except Exception:
        return True

# outcome_map: optional latest AI outcome per symbol, e.g., {"AAPL": "BUY"|"SELL"|"HOLD"}
def run_profit_guard(outcome_map: Optional[Dict[str, str]] = None) -> None:
    if not PG_ENABLED:
        return

    outcome_map = outcome_map or {}
    yf_budget = PG_MAX_EQUITY_YF_PER_CYCLE
    closed: list[str] = []

    for sym, qty, avg_price, tp_price, opened_at in _iter_open_db_positions():
        try:
            if qty == 0:
                continue
            side_long = qty > 0

            # Skip very fresh positions
            if not _age_ok(opened_at):
                continue

            # Select per-asset thresholds (defaults are set in ENV block above)
            if _is_fx(sym):
                _pg_min_profit = PG_MIN_PROFIT_PCT_FX
                _pg_tp_remain  = PG_TP_REMAIN_FRAC_FX
            else:
                _pg_min_profit = PG_MIN_PROFIT_PCT_EQ
                _pg_tp_remain  = PG_TP_REMAIN_FRAC_EQ

            # Get live qty to ensure it's really open at broker
            if _is_fx(sym):
                pos = mt5_get_position(sym)
                live_qty = float(pos["volume"]) if pos else 0.0
                if live_qty == 0.0:
                    continue
                cur = mt5_price(sym)
            else:
                live_qty = _equity_live_qty(sym)
                if live_qty == 0.0:
                    continue
                cur = None
                if yf_budget > 0:
                    cur = _yf_price(sym)
                    yf_budget -= 1

            if cur is None or cur <= 0.0 or avg_price <= 0.0:
                continue

            # Positive if profitable (handles short MT5 positions by inverting)
            ur = _unrealized_return(avg_price, cur, qty)
            if ur < _pg_min_profit:
                continue

            # Only skim if the current AI stance isn't BUY (optional)
            if PG_REQUIRE_NOT_BUY:
                tag = (outcome_map.get(sym) or "").upper()
                if tag == "BUY":
                    continue

            # If far from TP (or no TP set), we’re allowed to skim
            tp_rem = _tp_remaining_fraction(side_long, avg_price, cur, tp_price)
            far_from_tp = (tp_rem is None) or (tp_rem >= _pg_tp_remain)
            if not far_from_tp:
                continue

            # --- Close logic ---
            if _is_fx(sym):
                ok, msg = mt5_close(sym)
                print(f"[PG] {sym}: close FX {'OK' if ok else 'FAIL'} — {msg} | ur={ur:.4%}, tp_rem={tp_rem}")
                if ok:
                    closed.append(sym)
            else:
                # Sell entire live qty to flatten (T212 cannot short)
                ok = place_market_order(sym, -abs(live_qty))
                print(f"[PG] {sym}: close EQ {'OK' if ok else 'FAIL'} — ur={ur:.4%}, tp_rem={tp_rem}")
                if ok:
                    closed.append(sym)

        except Exception as e:
            # Never let a single symbol break the skim pass
            print(f"[PG] {sym}: exception during skim attempt — {e!r}")

    if closed:
        print(f"[PG] Skimmed profits on: {', '.join(closed)}")


