from __future__ import annotations
from config_forex import (
    FOREX_ALLOWED_SYMBOLS, FOREX_BLOCKED_SYMBOLS, USE_BROKER_SESSIONS,
    MIN_RR, TIME_STOP_MIN, MIN_PROGRESS_R, MAX_CONCURRENT_FOREX, FORCE_FLAT_AT_SESSION_END,
    FOREX_REDUCED_RISK_SYMBOLS, FOREX_REDUCED_RISK_MULT,
)
# --- robust .env loader (handles Windows-1252 smart chars etc.) --------------
# override=False so start_bot.bat (or shell) env vars win over .env (e.g. LLM_ENABLED=1 in bat)
from dotenv import load_dotenv, find_dotenv
def _init_env():
    path = find_dotenv(usecwd=True)
    if not path:
        return
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin1"):
        try:
            load_dotenv(dotenv_path=path, override=False, encoding=enc)
            return
        except UnicodeDecodeError:
            continue
_init_env()
# -----------------------------------------------------------------------------

import os
import time
from datetime import datetime
from typing import Optional, Dict, Tuple, Any, Callable, List

import requests

from strategies.sma_strategy import analyze_sma
from strategies.scalping_strategy import analyze_scalping
from strategies.strategy_config import (
    ACTIVE_STRATEGY,
    switch_strategy_if_needed,
    is_trading_halted,
    get_today_pnl_fx,
    get_today_pnl_equity,
)

from utils.market_data import get_last_price, load_recent_bars
from utils.market_hours import is_market_open
from utils.symbols import is_forex, normalize_symbol, to_mt5_symbol

from ai.meta_controller import MetaController
from ai.llm_decider import llm_decide, combine_llm_with_quant

# Extra strategies
from strategies.rsi_reversion import analyze_rsi
from strategies.donchian_breakout import analyze_donchian_breakout
from strategies.supertrend_trend import analyze_supertrend
from strategies.macd_trend import analyze_macd
from strategies.range_band_mr import analyze_range_mr
from strategies.bollinger_strategy import analyze_bollinger
from strategies.ema_crossover import analyze_ema_crossover
from strategies.breakout_strategy import analyze_breakout
from strategies.zscore_mean_reversion import analyze_zscore

from mt5_api import (
    get_current_price as mt5_get_price,
    place_market_order as mt5_place_order,
    get_position as mt5_get_position,
    close_position_market as mt5_close_position,
    modify_position_sl_tp as mt5_modify_sl_tp,
    is_symbol_tradable_now as mt5_is_tradable,
    get_account_equity as mt5_get_equity,
    sync_new_mm_deals_to_pnl as mt5_sync_mm_deals_to_pnl,
)

from trading212_api import (
    get_current_price as t212_get_price,  # currently unused
    place_market_order as t212_place_order,
    get_account_info,
    get_equity_position_qty,
    list_open_positions,
    reconcile_t212_portfolio_to_db,
    debug_dump_portfolio_map,
    invalidate_portfolio_cache,
)

from services.position_service import (
    get_position as db_get_position,
    upsert_position as db_update_position,
)
from services.pnl_service import add_to_daily_pnl, record_equity_close, reset_today_pnl

from config import (
    INSTRUMENTS,
    FOREX_SYMBOLS,
    TRADE_QUANTITY,
    TAKE_PROFIT_PERCENT,
    STOP_LOSS_PERCENT,
    FX_RISK_PER_TRADE_FRAC,
    EQ_RISK_PER_TRADE_FRAC,
    MAX_FX_LOTS_PER_ORDER,
    REFERENCE_EQUITY_MT5,
    REFERENCE_EQUITY_T212,
    BASE_TIMEZONE,
    MAX_POSITIONS_PER_SYMBOL,
    REENTRY_COOLDOWN_SEC,
    REENTRY_DELTA_PCT,
    REENTRY_COOLDOWN_SEC_EQUITY,
    REENTRY_DELTA_PCT_EQUITY,
    EQUITY_MIN_HOLD_MINUTES,
    EQUITY_SELL_CONFIRM_CYCLES,
    RATE_LIMIT,
    TRAILING_STOP_ENABLED,
    TRAILING_STOP_DISTANCE_PCT,
    TRAILING_STEP_PCT,
    BREAKEVEN_AFTER_PCT,
    # Equity software stops/trailing
    EQUITY_STOPS_ENABLED,
    EQUITY_TAKE_PROFIT_PERCENT,
    EQUITY_STOP_LOSS_PERCENT,
    EQUITY_TRAILING_ENABLED,
    EQUITY_TRAILING_DISTANCE_PCT,
    EQUITY_TRAILING_STEP_PCT,
    EQUITY_BREAKEVEN_AFTER_PCT,
    # Spike-fade
    SPIKE_FADE_ENABLED,
    SPIKE_FADE_ATR_MULT,
    SPIKE_FADE_MIN_RET_PCT,
    SPIKE_FADE_COOLDOWN_SEC,
    # Profit-oriented (profitability not guaranteed)
    PROFIT,
)

# ==============================================================================
# OpenAI logic toggles (environment)
# ==============================================================================
LLM_ENABLED = bool(int(os.getenv("LLM_ENABLED", "0")))
LLM_MODE = os.getenv("LLM_MODE", "TIE_BREAK").upper()
LLM_MIN_CONF = float(os.getenv("LLM_MIN_CONF", "0.65"))

# =============================================================================
# Feature flags / limits
# =============================================================================
USE_META_DECIDER = bool(int(os.getenv("USE_META_DECIDER", "1")))
MAX_TRADES_PER_HOUR = int(os.getenv("MAX_TRADES_PER_HOUR", str(RATE_LIMIT.get("MAX_TRADES_PER_HOUR", 5))))
MAX_ACCEPTABLE_UNCERTAINTY = float(os.getenv("MAX_ACCEPTABLE_UNCERTAINTY", "0.95"))

# Bar interval for AI context
AI_BAR_INTERVAL = os.getenv("AI_BAR_INTERVAL", "5m")

# =============================================================================
# Hedge settings (FX only)
# =============================================================================
# Default off: hedges add margin load and amplified losses when wrong; enable via HEDGE_ENABLED=1 if needed.
HEDGE_ENABLED = bool(int(os.getenv("HEDGE_ENABLED", "0")))
HEDGE_RATIO = float(os.getenv("HEDGE_RATIO", "0.5"))
HEDGE_TP_PCT = float(os.getenv("HEDGE_TP_PCT", "0.004"))
HEDGE_SL_PCT = float(os.getenv("HEDGE_SL_PCT", "0.004"))
HEDGE_COOLDOWN_SEC = float(os.getenv("HEDGE_COOLDOWN_SEC", "60"))

# --- Pre-trade confirmation (trend+vol floor) ---
PRECONFIRM_ENABLED = bool(int(os.getenv("PRECONFIRM_ENABLED", "1")))
# Allow per-asset tuning (FX should be stricter; equities can be looser).
PRECONFIRM_ATR_MIN_FX = float(os.getenv("PRECONFIRM_ATR_MIN_FX", os.getenv("PRECONFIRM_ATR_MIN", "0.00025")))
PRECONFIRM_ATR_MIN_EQ = float(os.getenv("PRECONFIRM_ATR_MIN_EQ", os.getenv("PRECONFIRM_ATR_MIN", "0.0015")))
PRECONFIRM_STRICT_FX  = bool(int(os.getenv("PRECONFIRM_STRICT_FX", os.getenv("PRECONFIRM_STRICT", "1"))))
PRECONFIRM_STRICT_EQ  = bool(int(os.getenv("PRECONFIRM_STRICT_EQ", os.getenv("PRECONFIRM_STRICT", "1"))))
PRECONFIRM_GRACE_BPS_FX = float(os.getenv("PRECONFIRM_GRACE_BPS_FX", os.getenv("PRECONFIRM_GRACE_BPS", "15")))
PRECONFIRM_GRACE_BPS_EQ = float(os.getenv("PRECONFIRM_GRACE_BPS_EQ", os.getenv("PRECONFIRM_GRACE_BPS", "15")))

# --- Decisive Mode (nudge after HOLD streak) ---
DECISIVE_MODE = bool(int(os.getenv("DECISIVE_MODE", "1")))
DECISIVE_MODE_FX = bool(int(os.getenv("DECISIVE_MODE_FX", "0")))  # default off for FX (reduces chop)
DECISIVE_MODE_EQ = bool(int(os.getenv("DECISIVE_MODE_EQ", "1")))
HOLD_STREAK_TRIGGER = int(os.getenv("HOLD_STREAK_TRIGGER", "3"))
NUDGE_WITHIN_GRACE_BPS = float(os.getenv("NUDGE_WITHIN_GRACE_BPS", "60"))
NUDGE_MIN_ATR_FRAC = float(os.getenv("NUDGE_MIN_ATR_FRAC", "0.5"))

# --- Profit Guard (per-asset) -------------------------------------------------
PG_ENABLED = bool(int(os.getenv("PG_ENABLED", "1")))
PG_MIN_PROFIT_PCT_FX = float(os.getenv("PG_MIN_PROFIT_PCT_FX", "0.0003"))  # 0.03%
PG_TP_REMAIN_FRAC_FX = float(os.getenv("PG_TP_REMAIN_FRAC_FX", "0.30"))
PG_MIN_PROFIT_PCT_EQ = float(os.getenv("PG_MIN_PROFIT_PCT_EQ", "0.0060"))  # 0.60% min profit before PG can skim equity
PG_TP_REMAIN_FRAC_EQ = float(os.getenv("PG_TP_REMAIN_FRAC_EQ", "0.50"))   # require 50% of TP remaining
PG_REQUIRE_NOT_BUY   = bool(int(os.getenv("PG_REQUIRE_NOT_BUY", "1")))
PG_MIN_POS_AGE_SEC   = int(os.getenv("PG_MIN_POS_AGE_SEC", "0"))

# Re-entry & pacing state
_last_entry: Dict[str, Dict] = {}
_last_t212_order_ts: float = 0.0
T212_MIN_ORDER_INTERVAL_SEC = float(os.getenv("T212_MIN_ORDER_INTERVAL_SEC", "1.2"))

# Track when we last opened a hedge per symbol to avoid rapid re-hedging
_last_hedge_open_ts: Dict[str, float] = {}
# Track when we last spike-flipped per symbol
_last_spike_flip_ts: Dict[str, float] = {}
# Per-symbol order timestamps for rate limiting
_order_times: Dict[str, List[float]] = {}
# Equity trailing state (software trailing on T212)
_eq_trail_sl: Dict[str, float] = {}
# Track AI arm (strategy) per symbol to log changes
_last_ai_arm: Dict[str, str] = {}
# Which meta-controller action last opened a position (for delayed reward on close)
_last_open_action: Dict[str, str] = {}
# Equity: time when position was opened (for min-hold check)
_equity_position_open_ts: Dict[str, float] = {}
# Equity: consecutive SELL signals before we allow close (sell confirmation)
_equity_sell_streak: Dict[str, int] = {}
# HOLD streak tracker
_hold_streak: Dict[str, int] = {}

# Auto risk switching (dynamic sizing)
AUTO_RISK_SWITCH_ENABLED = bool(int(os.getenv("AUTO_RISK_SWITCH_ENABLED", "1")))
AUTO_RISK_DD_SOFT = float(os.getenv("AUTO_RISK_DD_SOFT", "0.03"))   # 3% drawdown -> reduced risk
AUTO_RISK_DD_HARD = float(os.getenv("AUTO_RISK_DD_HARD", "0.06"))   # 6% drawdown -> defensive risk
AUTO_RISK_MULT_SOFT = float(os.getenv("AUTO_RISK_MULT_SOFT", "0.70"))
AUTO_RISK_MULT_HARD = float(os.getenv("AUTO_RISK_MULT_HARD", "0.40"))
AUTO_RISK_UP_PNL_FRAC = float(os.getenv("AUTO_RISK_UP_PNL_FRAC", "0.01"))  # +1% daily pnl -> small upshift
AUTO_RISK_MULT_UP = float(os.getenv("AUTO_RISK_MULT_UP", "1.10"))

_fx_risk_frac_live = float(FX_RISK_PER_TRADE_FRAC or 0.0)
_eq_risk_frac_live = float(EQ_RISK_PER_TRADE_FRAC or 0.0)
_fx_risk_ref_eq: float | None = float(REFERENCE_EQUITY_MT5) if REFERENCE_EQUITY_MT5 and REFERENCE_EQUITY_MT5 > 0 else None
_eq_risk_ref_eq: float | None = float(REFERENCE_EQUITY_T212) if REFERENCE_EQUITY_T212 and REFERENCE_EQUITY_T212 > 0 else None
_last_risk_profile_fx: str = ""
_last_risk_profile_eq: str = ""

# =============================================================================
# Strategy runners used by the AI decision
# =============================================================================
def _run_rsi(symbol: str, params: dict) -> Optional[str]:
    return analyze_rsi(
        symbol,
        lookback=params.get("lookback", "10d"),
        interval=params.get("interval", "15m"),
        rsi_len=int(params.get("rsi_len", 14)),
        overbought=float(params.get("overbought", 70.0)),
        oversold=float(params.get("oversold", 30.0)),
        trend_sma=int(params.get("trend_sma", 50)),
        buffer_bps=float(params.get("buffer_bps", 3.0)),
    )

def _run_donchian(symbol: str, params: dict) -> Optional[str]:
    return analyze_donchian_breakout(
        symbol,
        lookback=params.get("lookback", "20d"),
        interval=params.get("interval", "30m"),
        ch_len=int(params.get("ch_len", 20)),
        atr_len=int(params.get("atr_len", 14)),
        min_range_bps=float(params.get("min_range_bps", 12.0)),
        buffer_atr=float(params.get("buffer_atr", 0.25)),
    )

def _run_supertrend(symbol: str, params: dict) -> Optional[str]:
    return analyze_supertrend(
        symbol,
        lookback=params.get("lookback", "20d"),
        interval=params.get("interval", "15m"),
        atr_len=int(params.get("atr_len", 10)),
        mult=float(params.get("mult", 3.0)),
    )

def _run_macd(symbol: str, params: dict) -> Optional[str]:
    return analyze_macd(
        symbol,
        lookback=params.get("lookback", "20d"),
        interval=params.get("interval", "15m"),
        fast=int(params.get("fast", 12)),
        slow=int(params.get("slow", 26)),
        signal=int(params.get("signal", 9)),
        slope_len=int(params.get("slope_len", 50)),
    )

def _run_range_mr(symbol: str, params: dict):
    return analyze_range_mr(
        symbol,
        lookback=params.get("lookback", "3d"),
        interval=params.get("interval", "1m"),
        length=int(params.get("length", 60)),
        z_entry=float(params.get("z_entry", 1.2)),
        z_exit=float(params.get("z_exit", 0.2)),
        slope_thr=float(params.get("slope_thr", 0.0004)),
        min_bw=float(params.get("min_bw", 0.0008)),
        max_bw=float(params.get("max_bw", 0.0040)),
    )

def _run_bollinger(symbol: str, params: dict) -> Optional[str]:
    return analyze_bollinger(
        symbol,
        lookback=params.get("lookback", "20d"),
        interval=params.get("interval", "15m"),
        window=int(params.get("window", 20)),
        num_std=float(params.get("num_std", 2.0)),
        buffer_pct=float(params.get("buffer_pct", 0.001)),
    )

def _run_ema_crossover(symbol: str, params: dict) -> Optional[str]:
    return analyze_ema_crossover(
        symbol,
        lookback=params.get("lookback", "20d"),
        interval=params.get("interval", "15m"),
        fast=int(params.get("fast", 9)),
        slow=int(params.get("slow", 21)),
        require_price_side=params.get("require_price_side", True),
    )

def _run_breakout(symbol: str, params: dict) -> Optional[str]:
    return analyze_breakout(
        symbol,
        lookback=params.get("lookback", "30d"),
        interval=params.get("interval", "15m"),
        n_days=int(params.get("n_days", 20)),
        min_range_pct=float(params.get("min_range_pct", 0.002)),
    )

def _run_zscore(symbol: str, params: dict) -> Optional[str]:
    return analyze_zscore(
        symbol,
        lookback=params.get("lookback", "15d"),
        interval=params.get("interval", "15m"),
        length=int(params.get("length", 50)),
        entry_z=float(params.get("entry_z", 2.0)),
    )

STRATEGY_RUNNERS: Dict[str, Callable[[str, Dict[str, Any]], Optional[str]]] = {
    "SMA":       lambda s, p: analyze_sma(s),
    "SCALPING":  lambda s, p: analyze_scalping(s),
    "SCALP":     lambda s, p: analyze_scalping(s),
    "RSI_MR":    _run_rsi,
    "DONCHIAN":  _run_donchian,
    "SUPER":     _run_supertrend,
    "MACD":      _run_macd,
    "RANGE_MR":  _run_range_mr,
    "BOLLINGER": _run_bollinger,
    "EMA_CROSS": _run_ema_crossover,
    "BREAKOUT":  _run_breakout,
    "ZSCORE":    _run_zscore,
    "HOLD":      lambda _s, _p: "HOLD",
}

# =============================================================================
# Routing and helpers
# =============================================================================

def _route_get_price(symbol: str) -> Optional[float]:
    if is_forex(symbol):
        return mt5_get_price(to_mt5_symbol(symbol))
    return get_last_price(symbol)


def _rr_from_percents(tp_pct: float | None, sl_pct: float | None) -> float | None:
    """Compute reward:risk ratio from TP and SL percents."""
    if not tp_pct or not sl_pct or sl_pct <= 0:
        return None
    return float(tp_pct) / float(sl_pct)


def _route_open(symbol: str, quantity: float) -> Tuple[bool, str]:
    global _last_t212_order_ts

    if is_forex(symbol):
        mt5_sym = to_mt5_symbol(symbol)
        # Broker-side TP/SL percents for FX
        tp = float(TAKE_PROFIT_PERCENT or 0.0) or None
        sl = abs(float(STOP_LOSS_PERCENT or 0.0)) or None

        # -------------------- FOREX gates --------------------
        if FOREX_ALLOWED_SYMBOLS and symbol not in FOREX_ALLOWED_SYMBOLS:
            return False, f"[FOREX] {symbol} not in allowlist"
        if symbol in FOREX_BLOCKED_SYMBOLS:
            return False, f"[FOREX] {symbol} is blocked"
        if USE_BROKER_SESSIONS and not mt5_is_tradable(mt5_sym):
            return False, f"[FOREX] {symbol} broker session closed"
        try:
            from mt5_api import count_open_positions as _mt5_count
            if _mt5_count() >= MAX_CONCURRENT_FOREX:
                return False, "[FOREX] concurrency limit reached"
        except Exception:
            pass
        rr = _rr_from_percents(tp, sl)
        if rr is not None and rr < MIN_RR:
            return False, f"[FOREX] skip — RR {rr:.2f} < {MIN_RR:.2f}"
        return mt5_place_order(mt5_sym, quantity, tp_pct=tp, sl_pct=sl)

    # -------------------- Stocks (T212) --------------------
    now = time.time()
    delta = now - _last_t212_order_ts
    if delta < T212_MIN_ORDER_INTERVAL_SEC:
        time.sleep(T212_MIN_ORDER_INTERVAL_SEC - delta)

    ok = t212_place_order(symbol, quantity)
    _last_t212_order_ts = time.time()
    return (ok, "T212 order placed" if ok else "T212 order failed or not configured")


def _route_close(symbol: str) -> Tuple[bool, str, float]:
    """Returns (success, message, realized_pnl). For T212, realized_pnl is 0 (handled by SELL path)."""
    if is_forex(symbol):
        ok, msg, realized = mt5_close_position(to_mt5_symbol(symbol))
        return (ok, msg, float(realized or 0.0))
    return (False, "T212 close handled by SELL order", 0.0)

def _analyze_classic(symbol: str) -> Optional[str]:
    return analyze_sma(symbol) if ACTIVE_STRATEGY == "SMA" else analyze_scalping(symbol)

def _can_reenter(symbol: str, side: str, price: float) -> bool:
    info = _last_entry.get(symbol)
    if not info:
        return True
    cooldown = REENTRY_COOLDOWN_SEC_EQUITY if not is_forex(symbol) else REENTRY_COOLDOWN_SEC
    delta_pct = REENTRY_DELTA_PCT_EQUITY if not is_forex(symbol) else REENTRY_DELTA_PCT
    if time.time() - info["time"] < cooldown:
        return False
    delta = (price - info["price"]) / info["price"]
    return abs(delta) >= delta_pct

def _remember_entry(symbol: str, side: str, price: float):
    _last_entry[symbol] = {"side": side, "price": price, "time": time.time()}

# ------------------------- FX trailing (broker-side) -------------------------
def _manage_trailing(symbol: str, price: float):
    if not TRAILING_STOP_ENABLED or not is_forex(symbol):
        return
    mt5_sym = to_mt5_symbol(symbol)
    pos = mt5_get_position(mt5_sym)
    if not pos:
        return

    side = "LONG" if pos["type"] == 0 else "SHORT"
    entry = float(pos["price_open"])
    cur_sl = float(pos.get("sl", 0.0) or 0.0)

    pnl = (price - entry) / entry if side == "LONG" else (entry - price) / entry
    if pnl < BREAKEVEN_AFTER_PCT:
        return

    new_sl = max(entry, cur_sl) if side == "LONG" else min(entry, cur_sl if cur_sl else entry * 10)
    trail = TRAILING_STOP_DISTANCE_PCT
    candidate = (price - price * trail) if side == "LONG" else (price + price * trail)

    if side == "LONG":
        candidate = max(candidate, entry)
        if new_sl == 0.0 or candidate - new_sl >= price * TRAILING_STEP_PCT:
            new_sl = max(new_sl, candidate)
    else:
        candidate = min(candidate, entry)
        if new_sl == 0.0 or new_sl - candidate >= price * TRAILING_STEP_PCT:
            new_sl = min(new_sl if new_sl else candidate, candidate)

    if new_sl and (
        (side == "LONG" and (cur_sl == 0.0 or new_sl > cur_sl)) or
        (side == "SHORT" and (cur_sl == 0.0 or new_sl < cur_sl))
    ):
        ok, msg = mt5_modify_sl_tp(mt5_sym, sl=new_sl, tp=None)
        print(f"[TRAIL] {symbol}: {msg}")



def _manage_time_stop(symbol: str, price: float, meta=None):
    """Close FX trades that stagnate beyond TIME_STOP_MIN without MIN_PROGRESS_R progress in R."""
    if not is_forex(symbol) or TIME_STOP_MIN <= 0:
        return

    pos = mt5_get_position(to_mt5_symbol(symbol))
    if not pos:
        return

    # --- normalize MT5 open_time to datetime ---
    from datetime import datetime, timezone
    open_time_raw = pos.get("time") or pos.get("time_msc")  # either epoch seconds or datetime
    if isinstance(open_time_raw, (int, float)):
        open_time = datetime.fromtimestamp(open_time_raw, tz=timezone.utc)
    elif hasattr(open_time_raw, "timestamp"):
        open_time = open_time_raw if open_time_raw.tzinfo else open_time_raw.replace(tzinfo=timezone.utc)
    else:
        return  # unknown type

    entry = float(pos.get("price_open") or 0.0)
    if entry <= 0.0:
        return

    side = "LONG" if int(pos.get("type", 0)) == 0 else "SHORT"

    # Derive risk per trade from configured stop percent (fractions, not %)
    sl_pct = abs(STOP_LOSS_PERCENT) if STOP_LOSS_PERCENT and STOP_LOSS_PERCENT < 0 else None
    if not sl_pct or sl_pct <= 0.0:
        return  # cannot compute R without stop distance

    # Progress in R
    risk = entry * sl_pct
    if risk <= 0:
        return
    if side == "LONG":
        progress = (price - entry) / risk
    else:
        progress = (entry - price) / risk

    now = datetime.now(tz=open_time.tzinfo) if getattr(open_time, "tzinfo", None) else datetime.utcnow().replace(tzinfo=timezone.utc)
    age_min = (now - open_time).total_seconds() / 60.0

    if age_min >= TIME_STOP_MIN and progress < MIN_PROGRESS_R:
        ok, msg, realized = mt5_close_position(to_mt5_symbol(symbol))
        print(f"[TIME-STOP] {symbol}: {'CLOSED' if ok else 'FAILED'} — age={age_min:.1f}m, progress={progress:.2f}R | {msg}")
        if ok:
            add_to_daily_pnl(0.0)  # accounting handled by position close capture
            if meta and realized != 0.0:
                _feed_close_reward(meta, symbol, realized, is_fx=True)


# -------------------- Equity software stops / trailing -----------------------
def _equity_position_age_minutes(symbol: str) -> float:
    """Minutes since current equity position was opened (0 if unknown)."""
    ts = _equity_position_open_ts.get(symbol) or _equity_position_open_ts.get(normalize_symbol(symbol), 0.0)
    if ts <= 0:
        return 999.0
    return (time.time() - ts) / 60.0


def _equity_manage_soft_stops(symbol: str, price: float, meta=None) -> bool:
    if not EQUITY_STOPS_ENABLED:
        return False

    qty_live = get_equity_position_qty(symbol) or 0.0
    if qty_live <= 0.0:
        _eq_trail_sl.pop(symbol, None)
        return False

    key = normalize_symbol(symbol)
    db_pos = db_get_position(key)
    entry = float(getattr(db_pos, "avg_price", 0.0) or 0.0)
    if entry <= 0.0:
        return False

    pnl = (price - entry) / entry
    age_min = _equity_position_age_minutes(symbol)
    min_hold_ok = age_min >= float(EQUITY_MIN_HOLD_MINUTES)

    # Hard SL (always allowed)
    if EQUITY_STOP_LOSS_PERCENT and pnl <= EQUITY_STOP_LOSS_PERCENT:
        ok, info = _route_open(symbol, -qty_live)
        print(f"[EQ SL] {symbol}: {info} @ pnl={pnl:.4f}")
        if ok:
            realized = record_equity_close(symbol, entry, price, qty_live)
            invalidate_portfolio_cache()
            db_update_position(key, 0.0, 0.0, overwrite=True)
            _eq_trail_sl.pop(symbol, None)
            _equity_position_open_ts.pop(key, None)
            _equity_position_open_ts.pop(symbol, None)
            if meta:
                _feed_close_reward(meta, symbol, realized, is_fx=False)
        return bool(ok)

    # Hard TP only after min-hold (avoid closing too soon)
    if min_hold_ok and EQUITY_TAKE_PROFIT_PERCENT and pnl >= EQUITY_TAKE_PROFIT_PERCENT:
        ok, info = _route_open(symbol, -qty_live)
        print(f"[EQ TP] {symbol}: {info} @ pnl={pnl:.4f}")
        if ok:
            realized = record_equity_close(symbol, entry, price, qty_live)
            invalidate_portfolio_cache()
            db_update_position(key, 0.0, 0.0, overwrite=True)
            _eq_trail_sl.pop(symbol, None)
            _equity_position_open_ts.pop(key, None)
            _equity_position_open_ts.pop(symbol, None)
            if meta:
                _feed_close_reward(meta, symbol, realized, is_fx=False)
        return bool(ok)

    # Breakeven + trailing (only after min-hold)
    if not EQUITY_TRAILING_ENABLED:
        return False
    if pnl < EQUITY_BREAKEVEN_AFTER_PCT:
        return False

    candidate = max(entry, price * (1.0 - EQUITY_TRAILING_DISTANCE_PCT))
    prev = _eq_trail_sl.get(symbol, entry)
    if candidate - prev >= price * EQUITY_TRAILING_STEP_PCT:
        _eq_trail_sl[symbol] = candidate
        if os.getenv("T212_DEBUG", "0") == "1":
            print(f"[EQ TRAIL] {symbol}: raise SL → {candidate:.4f}")

    sl = _eq_trail_sl.get(symbol, None)
    if min_hold_ok and sl and price <= sl:
        ok, info = _route_open(symbol, -qty_live)
        print(f"[EQ TRAIL STOP] {symbol}: {info} | price={price:.4f} <= SL={sl:.4f}")
        if ok:
            realized = record_equity_close(symbol, entry, price, qty_live)
            invalidate_portfolio_cache()
            db_update_position(key, 0.0, 0.0, overwrite=True)
            _eq_trail_sl.pop(symbol, None)
            _equity_position_open_ts.pop(key, None)
            _equity_position_open_ts.pop(symbol, None)
            if meta:
                _feed_close_reward(meta, symbol, realized, is_fx=False)
        return bool(ok)

    return False

# =============================================================================
# Profit Guard (skim open profits while far from TP)
# =============================================================================
def _pnl_for_side(entry: float, cur: float, qty: float) -> float:
    if entry <= 0.0 or cur <= 0.0 or qty == 0.0:
        return 0.0
    r = (cur - entry) / entry
    return r if qty > 0 else -r

def _configured_tp_pct(symbol: str) -> float:
    if is_forex(symbol):
        return float(TAKE_PROFIT_PERCENT or 0.0)
    return float(EQUITY_TAKE_PROFIT_PERCENT or 0.0)

def _pg_thresholds(symbol: str) -> Tuple[float, float]:
    if is_forex(symbol):
        return PG_MIN_PROFIT_PCT_FX, PG_TP_REMAIN_FRAC_FX
    return PG_MIN_PROFIT_PCT_EQ, PG_TP_REMAIN_FRAC_EQ

def _age_ok_for_pg(db_pos) -> bool:
    if PG_MIN_POS_AGE_SEC <= 0:
        return True
    ts = None
    for attr in ("opened_at", "created_at", "updated_at"):
        ts = getattr(db_pos, attr, None)
        if ts:
            break
    try:
        if isinstance(ts, datetime):
            return (time.time() - ts.timestamp()) >= PG_MIN_POS_AGE_SEC
    except Exception:
        pass
    return True

def _profit_guard_run(all_symbols: List[str], outcome_map: Optional[Dict[str, str]] = None, meta=None) -> None:
    if not PG_ENABLED:
        return

    closed_syms: List[str] = []

    for symbol in all_symbols:
        try:
            live_qty = _current_position_qty(symbol)
            if live_qty == 0.0:
                continue

            key = normalize_symbol(symbol)
            db_pos = db_get_position(key)
            if not db_pos:
                continue
            if not _age_ok_for_pg(db_pos):
                continue

            entry = float(getattr(db_pos, "avg_price", 0.0) or 0.0)
            if entry <= 0.0:
                continue

            cur = _route_get_price(symbol)
            if cur is None or cur <= 0.0:
                continue

            ur = _pnl_for_side(entry, cur, live_qty)

            min_profit, remain_frac_req = _pg_thresholds(symbol)
            if ur < min_profit:
                continue

            if PG_REQUIRE_NOT_BUY and outcome_map:
                if (outcome_map.get(symbol, "") or "").upper() == "BUY":
                    continue

            tp_pct = _configured_tp_pct(symbol)
            far_from_tp = True
            remain_frac = None
            if tp_pct and tp_pct > 0.0:
                achieved = max(0.0, min(1.0, ur / tp_pct))
                remain_frac = 1.0 - achieved
                far_from_tp = remain_frac >= remain_frac_req

            if not far_from_tp:
                continue

            if is_forex(symbol):
                ok, msg, realized = mt5_close_position(to_mt5_symbol(symbol))
                print(f"[PG] {symbol}: FX close {'OK' if ok else 'FAIL'} — {msg} | ur={ur:.4%}, rem={remain_frac}")
                if ok:
                    db_update_position(key, 0.0, 0.0, overwrite=True)
                    if meta and realized != 0.0:
                        _feed_close_reward(meta, symbol, realized, is_fx=True)
                    closed_syms.append(symbol)
            else:
                qty_live = float(get_equity_position_qty(symbol) or 0.0)
                if qty_live <= 0.0:
                    continue
                # Don't PG-close equity before min-hold (let positions run)
                age_min = _equity_position_age_minutes(symbol)
                if age_min < float(EQUITY_MIN_HOLD_MINUTES):
                    continue
                ok, info = _route_open(symbol, -abs(qty_live))
                print(f"[PG] {symbol}: EQ close {'OK' if ok else 'FAIL'} — {info} | ur={ur:.4%}, rem={remain_frac}")
                if ok:
                    realized = record_equity_close(symbol, entry, cur, qty_live)
                    invalidate_portfolio_cache()
                    db_update_position(key, 0.0, 0.0, overwrite=True)
                    _eq_trail_sl.pop(symbol, None)
                    _equity_position_open_ts.pop(key, None)
                    _equity_position_open_ts.pop(symbol, None)
                    if meta:
                        _feed_close_reward(meta, symbol, realized, is_fx=False)
                    closed_syms.append(symbol)

        except Exception as e:
            print(f"[PG ERROR] {symbol}: {e}")

    if closed_syms:
        print(f"[PG] Skimmed profits on: {', '.join(closed_syms)}")

# =============================================================================
# Lightweight reward + helpers
# =============================================================================
def _atr_percent(df, n: int = 14) -> float:
    try:
        h = df["High"].astype(float)
        l = df["Low"].astype(float)
        c = df["Close"].astype(float)
        prev_c = c.shift(1)
        tr = (h - l).abs().combine((h - prev_c).abs(), max).combine((l - prev_c).abs(), max)
        atr = tr.rolling(n).mean().iloc[-1]
        last_c = float(c.iloc[-1])
        if last_c > 0 and atr is not None:
            return float(atr) / last_c
    except Exception:
        pass
    try:
        c = df["Close"].astype(float)
        if len(c) > 5 and float(c.iloc[-1]) != 0.0:
            return float(c.pct_change().rolling(20).std().iloc[-1] or 0.0)
    except Exception:
        pass
    return 0.0

def _estimate_reward(df, outcome: Optional[str]) -> float:
    if outcome is None:
        return -0.05
    try:
        c = df["Close"].astype(float)
        if len(c) < 3:
            return 0.0
        ret = (float(c.iloc[-1]) - float(c.iloc[-2])) / max(float(c.iloc[-2]), 1e-12)
        atrp = _atr_percent(df)
        scale = atrp if atrp > 1e-6 else 1.0
        base = ret / scale
        if outcome == "BUY":
            r = base
        elif outcome == "SELL":
            r = -base
        elif outcome == "HOLD":
            r = -abs(base) * 0.1
        else:
            r = 0.0
        return float(max(-1.0, min(1.0, r)))
    except Exception:
        return 0.0

# --------------------------- Pre-trade confirmation --------------------------
def _pretrade_filter(symbol: str, outcome: Optional[str], df=None) -> Optional[str]:
    if outcome not in ("BUY", "SELL"):
        return outcome

    # Min risk:reward: skip opening if configured TP/SL ratio is below threshold (profit-oriented)
    min_rr = float(PROFIT.get("MIN_RISK_REWARD_RATIO", 0.0))
    if min_rr > 0:
        if is_forex(symbol):
            tp, sl = abs(TAKE_PROFIT_PERCENT), abs(STOP_LOSS_PERCENT)
        else:
            tp, sl = abs(EQUITY_TAKE_PROFIT_PERCENT), abs(EQUITY_STOP_LOSS_PERCENT)
        if sl > 0:
            rr = tp / sl
            if rr < min_rr:
                print(f"[PRECHECK] {symbol}: block {outcome} (R:R {rr:.2f} < {min_rr:.2f})")
                return "HOLD"

    if not PRECONFIRM_ENABLED:
        return outcome

    try:
        if df is None or df.empty or "Close" not in df.columns:
            df = load_recent_bars(symbol, lookback="3d", interval="5m")
        if df is None or df.empty:
            print(f"[PRECHECK] {symbol}: block {outcome} (no data)")
            return "HOLD"

        c = df["Close"].astype(float)
        if len(c) < 50:
            print(f"[PRECHECK] {symbol}: block {outcome} (insufficient bars)")
            return "HOLD"

        price = float(c.iloc[-1])
        sma20 = float(c.rolling(20).mean().iloc[-1])
        sma50 = float(c.rolling(50).mean().iloc[-1])

        atrp = _atr_percent(df)
        atr_min = PRECONFIRM_ATR_MIN_FX if is_forex(symbol) else PRECONFIRM_ATR_MIN_EQ
        if atrp < atr_min:
            print(f"[PRECHECK] {symbol}: block {outcome} (ATR {atrp:.4f} < {atr_min:.4f})")
            return "HOLD"

        grace_bps = PRECONFIRM_GRACE_BPS_FX if is_forex(symbol) else PRECONFIRM_GRACE_BPS_EQ
        grace = (price * grace_bps) / 10000.0

        strict = PRECONFIRM_STRICT_FX if is_forex(symbol) else PRECONFIRM_STRICT_EQ
        if strict:
            ok_buy  = (price > sma20 > sma50)
            ok_sell = (price < sma20 < sma50)
        else:
            ok_buy  = (price + grace >= sma20) and (sma20 >= sma50)
            ok_sell = (price - grace <= sma20) and (sma20 <= sma50)

        if outcome == "BUY" and not ok_buy:
            print(f"[PRECHECK] {symbol}: block BUY (trend misaligned: "
                  f"price={price:.5f} sma20={sma20:.5f} sma50={sma50:.5f} grace={grace:.5f})")
            return "HOLD"

        if outcome == "SELL" and not ok_sell:
            print(f"[PRECHECK] {symbol}: block SELL (trend misaligned: "
                  f"price={price:.5f} sma20={sma20:.5f} sma50={sma50:.5f} grace={grace:.5f})")
            return "HOLD"

        return outcome

    except Exception as e:
        print(f"[PRECHECK] {symbol}: exception during precheck ({e}); allowing {outcome}")
        return outcome

# --------------------------- Spike-fade overlay ------------------------------
def _spike_fade_adjust(symbol: str, df, outcome: Optional[str]) -> Optional[str]:
    if not SPIKE_FADE_ENABLED or outcome not in ("BUY", "SELL"):
        return outcome
    if df is None or df.empty or "Close" not in df.columns or len(df) < 3:
        return outcome

    try:
        c = df["Close"].astype(float)
        last = float(c.iloc[-1])
        prev = float(c.iloc[-2]) if float(c.iloc[-2]) != 0.0 else last
        ret = (last - prev) / max(prev, 1e-12)
        atrp = _atr_percent(df)
        big_move = abs(ret) >= max(SPIKE_FADE_MIN_RET_PCT, SPIKE_FADE_ATR_MULT * atrp)

        now = time.time()
        last_ts = _last_spike_flip_ts.get(symbol, 0.0)
        cooled = (now - last_ts) >= SPIKE_FADE_COOLDOWN_SEC

        if big_move and cooled:
            if (ret > 0 and outcome == "BUY") or (ret < 0 and outcome == "SELL"):
                flipped = "SELL" if outcome == "BUY" else "BUY"
                _last_spike_flip_ts[symbol] = now
                print(f"[SPIKE-FADE] {symbol}: last_ret={ret:.4f}, atr%={atrp:.4f} => flip {outcome}→{flipped}")
                return flipped
    except Exception:
        pass

    return outcome

# --------------------------- Decisive Mode (nudge) ---------------------------
def _decisive_nudge(symbol: str, outcome: Optional[str], df) -> Optional[str]:
    if outcome != "HOLD":
        return outcome
    if not DECISIVE_MODE:
        return outcome
    if is_forex(symbol) and not DECISIVE_MODE_FX:
        return outcome
    if (not is_forex(symbol)) and not DECISIVE_MODE_EQ:
        return outcome
    if df is None or df.empty or "Close" not in df.columns or len(df) < 50:
        return outcome

    try:
        c = df["Close"].astype(float)
        price = float(c.iloc[-1])
        sma20 = float(c.rolling(20).mean().iloc[-1])
        sma50 = float(c.rolling(50).mean().iloc[-1])

        atrp = _atr_percent(df)
        atr_min = PRECONFIRM_ATR_MIN_FX if is_forex(symbol) else PRECONFIRM_ATR_MIN_EQ
        if atrp < max(1e-9, atr_min * NUDGE_MIN_ATR_FRAC):
            return outcome

        grace = (price * NUDGE_WITHIN_GRACE_BPS) / 10000.0
        if sma20 >= sma50 and price + grace >= sma20:
            print(f"[NUDGE] {symbol}: HOLD→BUY (near-uptrend, grace={NUDGE_WITHIN_GRACE_BPS}bps)")
            return "BUY"
        if sma20 <= sma50 and price - grace <= sma20:
            print(f"[NUDGE] {symbol}: HOLD→SELL (near-downtrend, grace={NUDGE_WITHIN_GRACE_BPS}bps)")
            return "SELL"
    except Exception:
        pass
    return outcome

# =============================================================================
# FX-only hedge controller
# =============================================================================
def _maybe_hedge_fx(symbol: str, sma_signal: Optional[str]) -> None:
    if not HEDGE_ENABLED or not is_forex(symbol):
        return
    try:
        mt5_sym = to_mt5_symbol(symbol)
        pos = mt5_get_position(mt5_sym)
        cur_qty = 0.0

        if pos:
            vol = float(pos.get("volume") or 0.0)
            if vol > 0:
                cur_side = "LONG" if int(pos.get("type", 0)) == 0 else "SHORT"
                cur_qty = vol if cur_side == "LONG" else -vol

        if cur_qty == 0.0 or not sma_signal or sma_signal not in ("BUY", "SELL"):
            return

        need_short_hedge = (cur_qty > 0.0 and sma_signal == "SELL")
        need_long_hedge  = (cur_qty < 0.0 and sma_signal == "BUY")
        if not (need_short_hedge or need_long_hedge):
            return

        now = time.time()
        last_ts = _last_hedge_open_ts.get(symbol, 0.0)
        if (now - last_ts) < HEDGE_COOLDOWN_SEC:
            return

        hedge_qty = max(0.0, abs(cur_qty) * HEDGE_RATIO)
        if hedge_qty <= 0.0:
            return

        side_qty = -hedge_qty if need_short_hedge else +hedge_qty
        ok, info = mt5_place_order(
            mt5_sym,
            side_qty,
            tp_pct=HEDGE_TP_PCT if HEDGE_TP_PCT > 0 else None,
            sl_pct=HEDGE_SL_PCT if HEDGE_SL_PCT > 0 else None,
        )
        if ok:
            _last_hedge_open_ts[symbol] = now
            print(f"[HEDGE] {symbol}: opened {'SHORT' if need_short_hedge else 'LONG'} hedge qty={hedge_qty:.3f} (ratio={HEDGE_RATIO:.2f}) via SMA={sma_signal}. {info}")
        else:
            print(f"[HEDGE] {symbol}: hedge order failed. {info}")
    except Exception as e:
        print(f"[HEDGE ERROR] {symbol}: {e}")

# =============================================================================
# Rate limiting (per symbol)
# =============================================================================
def _rate_limit_ok(symbol: str) -> bool:
    now = time.time()
    window = 3600.0
    q = _order_times.setdefault(symbol, [])
    while q and (now - q[0]) > window:
        q.pop(0)
    limit = RATE_LIMIT.get("EQUITY_MAX_TRADES_PER_HOUR", MAX_TRADES_PER_HOUR) if not is_forex(symbol) else MAX_TRADES_PER_HOUR
    return len(q) < limit

def _rate_mark(symbol: str) -> None:
    _order_times.setdefault(symbol, []).append(time.time())


def _feed_close_reward(meta, symbol: str, realized_pnl: float, is_fx: bool) -> None:
    """
    Feed delayed reward into the meta-controller when a position closes.
    Uses the action that opened the position (stored in _last_open_action) so
    the AI learns from actual PnL, not just next-bar return.
    """
    if meta is None or realized_pnl == 0.0:
        return
    key = normalize_symbol(symbol)
    action = _last_open_action.pop(key, None) or _last_open_action.pop(symbol, None)
    if not action:
        return
    try:
        if is_fx:
            eq = mt5_get_equity()
        else:
            info = get_account_info() or {}
            eq = float(info.get("totalValue") or info.get("investedValue") or info.get("freeCash") or 5000.0)
        scale = max(eq * 0.01, 1.0)
        reward = float(realized_pnl) / scale
        reward = max(-2.0, min(2.0, reward))
        # Profit bias: scale up positive rewards so the bandit leans toward profitable arms
        profit_bias = float(PROFIT.get("REWARD_PROFIT_BIAS", 1.0))
        if profit_bias != 1.0 and reward > 0:
            reward = max(-2.0, min(2.0, reward * profit_bias))
        df = load_recent_bars(symbol, lookback="2d", interval=AI_BAR_INTERVAL)
        if df is not None and not df.empty:
            meta.learn(df, action, reward, symbol=symbol)
    except Exception as e:
        print(f"[AI REWARD] skip feed for {symbol}: {e}")


def _pick_risk_multiplier(drawdown_frac: float, pnl_frac: float) -> Tuple[float, str]:
    if drawdown_frac >= AUTO_RISK_DD_HARD:
        return max(0.0, AUTO_RISK_MULT_HARD), "DEFENSIVE_HARD"
    if drawdown_frac >= AUTO_RISK_DD_SOFT:
        return max(0.0, AUTO_RISK_MULT_SOFT), "DEFENSIVE_SOFT"
    if pnl_frac >= AUTO_RISK_UP_PNL_FRAC and drawdown_frac <= max(0.0, AUTO_RISK_DD_SOFT * 0.5):
        return max(0.0, AUTO_RISK_MULT_UP), "OFFENSIVE"
    return 1.0, "BASE"


def _refresh_dynamic_risk(mt5_eq: float, t212_eq: float) -> None:
    """Update live risk fractions once per loop based on drawdown and daily pnl."""
    global _fx_risk_frac_live, _eq_risk_frac_live
    global _fx_risk_ref_eq, _eq_risk_ref_eq
    global _last_risk_profile_fx, _last_risk_profile_eq

    base_fx = float(FX_RISK_PER_TRADE_FRAC or 0.0)
    base_eq = float(EQ_RISK_PER_TRADE_FRAC or 0.0)

    if not AUTO_RISK_SWITCH_ENABLED:
        _fx_risk_frac_live = base_fx
        _eq_risk_frac_live = base_eq
        return

    if _fx_risk_ref_eq is None and mt5_eq > 0:
        _fx_risk_ref_eq = mt5_eq
    if _eq_risk_ref_eq is None and t212_eq > 0:
        _eq_risk_ref_eq = t212_eq

    try:
        pnl_fx = float(get_today_pnl_fx() or 0.0)
    except Exception:
        pnl_fx = 0.0
    try:
        pnl_eq = float(get_today_pnl_equity() or 0.0)
    except Exception:
        pnl_eq = 0.0

    # FX profile
    if mt5_eq > 0 and (_fx_risk_ref_eq or 0) > 0:
        fx_ref = float(_fx_risk_ref_eq or mt5_eq)
        fx_dd = max(0.0, (fx_ref - mt5_eq) / max(fx_ref, 1e-9))
        fx_pnl_frac = pnl_fx / mt5_eq
        fx_mult, fx_profile = _pick_risk_multiplier(fx_dd, fx_pnl_frac)
    else:
        fx_mult, fx_profile = 1.0, "BASE"
    _fx_risk_frac_live = base_fx * fx_mult

    # Equity profile
    if t212_eq > 0 and (_eq_risk_ref_eq or 0) > 0:
        eq_ref = float(_eq_risk_ref_eq or t212_eq)
        eq_dd = max(0.0, (eq_ref - t212_eq) / max(eq_ref, 1e-9))
        eq_pnl_frac = pnl_eq / t212_eq
        eq_mult, eq_profile = _pick_risk_multiplier(eq_dd, eq_pnl_frac)
    else:
        eq_mult, eq_profile = 1.0, "BASE"
    _eq_risk_frac_live = base_eq * eq_mult

    # Log only when profile changes to avoid noise.
    if fx_profile != _last_risk_profile_fx:
        print(f"[RISK PROFILE][FX] {fx_profile} | frac={_fx_risk_frac_live:.6f} (base={base_fx:.6f})")
        _last_risk_profile_fx = fx_profile
    if eq_profile != _last_risk_profile_eq:
        print(f"[RISK PROFILE][EQ] {eq_profile} | frac={_eq_risk_frac_live:.6f} (base={base_eq:.6f})")
        _last_risk_profile_eq = eq_profile


def _compute_risk_based_quantity(symbol: str, price: float) -> float:
    """
    Compute a position size based on configured per-trade risk fractions.

    Falls back to TRADE_QUANTITY when required inputs are missing. For FX,
    we use MT5 account equity and STOP_LOSS_PERCENT; for equities we use
    T212 account info (if available) and EQUITY_STOP_LOSS_PERCENT.
    """
    try:
        base_qty = float(TRADE_QUANTITY)
    except Exception:
        base_qty = 0.0

    if price <= 0.0:
        return base_qty

    if is_forex(symbol):
        # FX sizing: risk = equity * FX_RISK_PER_TRADE_FRAC (MT5 budget; use REFERENCE_EQUITY_MT5 if set)
        # per-lot risk ≈ price * |STOP_LOSS_PERCENT|
        eq = float(REFERENCE_EQUITY_MT5) if REFERENCE_EQUITY_MT5 and REFERENCE_EQUITY_MT5 > 0 else mt5_get_equity()
        if eq is not None:
            eq = float(eq or 0.0)
        else:
            eq = 0.0
        sl_frac = abs(float(STOP_LOSS_PERCENT or 0.0))
        if eq <= 0.0 or sl_frac <= 0.0:
            return base_qty or 0.1
        risk_per_trade = eq * float(_fx_risk_frac_live or 0.0)
        if symbol in (FOREX_REDUCED_RISK_SYMBOLS or []):
            risk_per_trade *= float(FOREX_REDUCED_RISK_MULT or 1.0)
        if risk_per_trade <= 0.0:
            return base_qty or 0.1
        per_lot_risk_est = price * sl_frac
        if per_lot_risk_est <= 0.0:
            return base_qty or 0.1
        lots = risk_per_trade / per_lot_risk_est
        cap = float(MAX_FX_LOTS_PER_ORDER or 0.0)
        if cap <= 0:
            cap = 0.35
        # Hard cap per order + floor; MT5 API also caps by margin and applies same MAX_FX_LOTS cap.
        out = max(0.01, min(lots, cap))
        if lots > cap + 1e-6:
            print(f"[RISK] {symbol}: requested lots {lots:.3f} capped to {out:.3f} (MAX_FX_LOTS_PER_ORDER)")
        return out

    # Equity sizing: risk = equity * EQ_RISK_PER_TRADE_FRAC (T212 budget; use REFERENCE_EQUITY_T212 if set)
    # per-share risk ≈ price * |EQUITY_STOP_LOSS_PERCENT|
    if REFERENCE_EQUITY_T212 and REFERENCE_EQUITY_T212 > 0:
        eq_val = float(REFERENCE_EQUITY_T212)
    else:
        try:
            info = get_account_info() or {}
            eq_val = float(
                info.get("totalValue")
                or info.get("investedValue")
                or info.get("freeCash")
                or 5000.0
            )
        except Exception:
            eq_val = 5000.0

    sl_frac_eq = abs(float(EQUITY_STOP_LOSS_PERCENT or 0.0))
    if eq_val <= 0.0 or sl_frac_eq <= 0.0:
        return base_qty or 1.0

    risk_per_trade_eq = eq_val * float(_eq_risk_frac_live or 0.0)
    if risk_per_trade_eq <= 0.0:
        return base_qty or 1.0

    per_share_risk = price * sl_frac_eq
    if per_share_risk <= 0.0:
        return base_qty or 1.0

    shares = risk_per_trade_eq / per_share_risk
    return max(0.1, min(shares, eq_val / max(price, 1e-6)))

def _current_position_qty(symbol: str) -> float:
    if is_forex(symbol):
        mt5_sym = to_mt5_symbol(symbol)
        mtp = mt5_get_position(mt5_sym)
        if not mtp:
            return 0.0
        vol = float(mtp["volume"])
        return vol if mtp["type"] == 0 else -vol
    else:
        return float(get_equity_position_qty(symbol) or 0.0)


def _reconcile_live_positions(all_symbols: List[str], *, reason: str = "cycle") -> None:
    """
    Reconcile DB position rows with broker/live quantities.
    Runs each cycle and once again during shutdown to avoid stale OPEN rows.
    """
    for symbol in all_symbols:
        try:
            key = normalize_symbol(symbol)
            live_qty = _current_position_qty(symbol)
            db_pos = db_get_position(key)
            db_qty = float(db_pos.quantity) if db_pos else 0.0

            if abs(live_qty - db_qty) > 1e-9:
                print(f"[RECON:{reason}] {symbol}: DB={db_qty} → LIVE={live_qty} — syncing.")
                price = 0.0 if live_qty == 0.0 else (_route_get_price(symbol) or 0.0)
                db_update_position(key, live_qty, price, overwrite=True)

                if live_qty == 0.0:
                    had_state = key in _last_entry or key in _equity_position_open_ts or key in _equity_sell_streak
                    _last_entry.pop(key, None)
                    _eq_trail_sl.pop(symbol, None)
                    _equity_position_open_ts.pop(key, None)
                    _equity_position_open_ts.pop(symbol, None)
                    _equity_sell_streak.pop(key, None)
                    if had_state:
                        print(f"[RECON:{reason}] {symbol}: flat → cooldown/equity state cleared.")
        except Exception as rec_err:
            print(f"[RECON:{reason} ERROR] {symbol}: {rec_err}")

# =============================================================================
# Main loop
# =============================================================================
def run_live_trading():
    print("\n==================================================")
    print(f"Starting trading cycle ({'AI' if USE_META_DECIDER else 'classic'}) with {ACTIVE_STRATEGY} default")
    all_symbols = list(FOREX_SYMBOLS) + list(INSTRUMENTS)
    print(f"Tracking {len(all_symbols)} symbols")
    print(f"[AI-KNOBS] min_margin={os.getenv('AI_MIN_UCB_MARGIN','0.00')} ucb_floor={os.getenv('AI_UCB_FLOOR','-1.00')} uncertainty_max={MAX_ACCEPTABLE_UNCERTAINTY}")
    print(f"[LLM-KNOBS] enabled={int(LLM_ENABLED)} mode={LLM_MODE} min_conf={LLM_MIN_CONF}")
    print(
        f"[PRECHECK-KNOBS] FX(atr_min={PRECONFIRM_ATR_MIN_FX}, strict={int(PRECONFIRM_STRICT_FX)}, grace_bps={PRECONFIRM_GRACE_BPS_FX}) "
        f"| EQ(atr_min={PRECONFIRM_ATR_MIN_EQ}, strict={int(PRECONFIRM_STRICT_EQ)}, grace_bps={PRECONFIRM_GRACE_BPS_EQ}) "
        f"| DECISIVE(FX={int(DECISIVE_MODE_FX)}, EQ={int(DECISIVE_MODE_EQ)})"
    )
    print(f"[USER] base_tz={BASE_TIMEZONE} | MT5_ref={REFERENCE_EQUITY_MT5 or 'live'} T212_ref={REFERENCE_EQUITY_T212 or 'live'}")
    print(
        f"[RISK-AUTO] enabled={int(AUTO_RISK_SWITCH_ENABLED)} "
        f"dd_soft={AUTO_RISK_DD_SOFT:.2%} dd_hard={AUTO_RISK_DD_HARD:.2%} "
        f"mult(soft/hard/up)=({AUTO_RISK_MULT_SOFT:.2f}/{AUTO_RISK_MULT_HARD:.2f}/{AUTO_RISK_MULT_UP:.2f})"
    )
    print("==================================================\n")

    # One-time T212 probe & reconciliation (single portfolio fetch to avoid 429 at startup)
    try:
        acct = get_account_info()
        print("[T212] Account OK" if acct else "[T212] Account info not available.")
        try:
            updated, skipped = reconcile_t212_portfolio_to_db(force_refresh=True)
            print(f"[T212 RECON] DB updated for {updated} equity symbols (skipped {skipped}).")
            pos = list_open_positions() or []  # use cache from reconcile, no extra GET
            tickers = [f"{p.get('ticker')}={p.get('quantity')}" for p in pos]
            print(f"[T212 RAW] {len(pos)} items → " + ", ".join(tickers))
        except Exception as e:
            print(f"[T212 RECON] Failed: {e}")
        try:
            debug_dump_portfolio_map()
        except Exception as e:
            pass
    except Exception as e:
        print(f"[T212] Skipping account info due to error: {e}")

    # Optional: zero today's PnL in DB once so circuit breaker doesn't trip on stale data (set RESET_DAILY_PNL_ON_START=1 in .env)
    if os.getenv("RESET_DAILY_PNL_ON_START", "0").strip().lower() in ("1", "true", "yes"):
        try:
            if reset_today_pnl():
                print("[PnL] Today's DailyPnL reset to 0 (RESET_DAILY_PNL_ON_START=1). Set to 0 after this run if you don't want it every start.")
        except Exception as e:
            print(f"[PnL] Reset today PnL failed: {e}")

    # Instantiate AI decider
    meta = MetaController(
        alpha=0.6, d=11,
        min_ucb_margin=float(os.getenv("AI_MIN_UCB_MARGIN", "0.00")),
        ucb_floor=float(os.getenv("AI_UCB_FLOOR", "-1.00")),
        flip_cooldown_sec=int(os.getenv("AI_FLIP_COOLDOWN_SEC", "60")),
    )

    try:
        while True:
            # Ensure any new MM-tagged MT5 deals (including SL/TP or manual closes)
            # are reflected in DailyPnL even if they didn't go through the explicit
            # close_position_market() path.
            try:
                mt5_sync_mm_deals_to_pnl()
            except Exception as e:
                print(f"[MT5 PNL SYNC] skipped this cycle: {e}")

            # --------------------------- Auto-reconciliation -------------------
            _reconcile_live_positions(all_symbols, reason="cycle")

            # Strategy switcher: separate MT5 and T212 (per-account circuit breakers)
            try:
                mt5_eq = float(REFERENCE_EQUITY_MT5) if REFERENCE_EQUITY_MT5 and REFERENCE_EQUITY_MT5 > 0 else None
                if mt5_eq is None:
                    e = mt5_get_equity()
                    mt5_eq = float(e or 0.0) if e is not None else 0.0
                t212_eq = float(REFERENCE_EQUITY_T212) if REFERENCE_EQUITY_T212 and REFERENCE_EQUITY_T212 > 0 else None
                if t212_eq is None:
                    try:
                        info = get_account_info() or {}
                        t212_eq = float(info.get("totalValue") or info.get("investedValue") or info.get("freeCash") or 0.0)
                    except Exception:
                        t212_eq = 0.0
                if mt5_eq <= 0:
                    mt5_eq = 5000.0
                if t212_eq <= 0:
                    t212_eq = 5000.0
            except Exception:
                mt5_eq = 5000.0
                t212_eq = 5000.0
            switch_strategy_if_needed(mt5_equity=mt5_eq, t212_equity=t212_eq)
            _refresh_dynamic_risk(mt5_eq=mt5_eq, t212_eq=t212_eq)

            # --------------------------- Trading pass --------------------------
            latest_outcomes: Dict[str, str] = {}

            for symbol in all_symbols:
                try:
                    # Per-account circuit breaker: skip FX if MT5 halted, skip equity if T212 halted.
                    if is_trading_halted(symbol):
                        latest_outcomes[symbol] = "HOLD"
                        continue

                    if not is_market_open(symbol):
                        latest_outcomes[symbol] = "HOLD"
                        continue

                    price = _route_get_price(symbol)
                    if price is None:
                        latest_outcomes[symbol] = "HOLD"
                        continue

                    # Manage stops/trailing
                    _manage_trailing(symbol, price)
                    _manage_time_stop(symbol, price, meta=meta)
                    # Optionally force-flat at end of broker session (FOREX only)
                    if FORCE_FLAT_AT_SESSION_END and is_forex(symbol):
                        mt5_sym = to_mt5_symbol(symbol)
                        pos = mt5_get_position(mt5_sym)
                        if pos and not mt5_is_tradable(mt5_sym):
                            ok, msg, realized = mt5_close_position(mt5_sym)
                            print(f"[SESSION-FLAT] {symbol}: {'CLOSED' if ok else 'FAILED'} — {msg}")
                            if ok and meta and realized != 0.0:
                                _feed_close_reward(meta, symbol, realized, is_fx=True)
      # FX broker-side
                    if not is_forex(symbol) and _equity_manage_soft_stops(symbol, price, meta=meta):
                        latest_outcomes[symbol] = "HOLD"
                        continue

                    # ======= Decision: AI or classic =======
                    decision_action = None
                    decision_strategy = None
                    decision_params: Dict[str, Any] = {}
                    decision_uncertainty = 0.0
                    outcome = None
                    df = None

                    if USE_META_DECIDER:
                        df = load_recent_bars(symbol, lookback="2d", interval=AI_BAR_INTERVAL)
                        if df is None or df.empty:
                            outcome = _analyze_classic(symbol)
                            decision_action = "CLASSIC_EMPTY_DATA"
                            decision_strategy = ACTIVE_STRATEGY
                            decision_params = {}
                        else:
                            md = meta.decide(df, symbol=symbol)
                            decision_action = md.action
                            decision_strategy = md.strategy
                            decision_params = md.params or {}
                            decision_uncertainty = md.uncertainty

                            prev_arm = _last_ai_arm.get(symbol)
                            if prev_arm != decision_strategy:
                                print(f"[AI-ARM] {symbol}: {prev_arm or '-'} → {decision_strategy}")
                                _last_ai_arm[symbol] = decision_strategy

                            if decision_strategy == "HOLD" or decision_uncertainty > MAX_ACCEPTABLE_UNCERTAINTY:
                                fallback = analyze_sma(symbol)
                                if fallback and fallback != "HOLD":
                                    outcome = fallback
                                    print(f"[AI-FALLBACK] {symbol}: using SMA due to "
                                          f"{'strategy=HOLD' if decision_strategy=='HOLD' else f'uncertainty {decision_uncertainty:.2f} > {MAX_ACCEPTABLE_UNCERTAINTY:.2f}'} ⇒ {outcome}")
                                    decision_action = "SMA_conservative"
                                    decision_strategy = "SMA"
                                    decision_params = {"note": "fallback"}
                                else:
                                    outcome = "HOLD"
                            else:
                                runner = STRATEGY_RUNNERS.get(decision_strategy, STRATEGY_RUNNERS["HOLD"])
                                outcome = runner(symbol, decision_params)

                            reward = _estimate_reward(df, outcome)
                            meta.learn(df, decision_action, reward, symbol=symbol)

                            print(f"[AI] {symbol} → strat={decision_strategy} params={decision_params} u={decision_uncertainty:.2f} ⇒ {outcome}")
                    else:
                        outcome = _analyze_classic(symbol)
                        decision_action = "CLASSIC"
                        decision_strategy = ACTIVE_STRATEGY
                        decision_params = {}

                    # Pre-trade filter
                    outcome = _pretrade_filter(symbol, outcome, df)

                    # LLM tie-break / veto / primary
                    if LLM_ENABLED:
                        if df is None:
                            df = load_recent_bars(symbol, lookback="2d", interval="5m")
                        if df is not None and not df.empty:
                            quant_hint = {"quant_outcome": outcome,
                                          "strategy": decision_strategy,
                                          "uncertainty": decision_uncertainty}
                            llm_suggestion = llm_decide(symbol, df, candidate_from_quant=quant_hint)
                            if llm_suggestion:
                                prev = outcome
                                outcome = combine_llm_with_quant(prev, llm_suggestion, mode=LLM_MODE, min_conf=LLM_MIN_CONF)
                                tag = f"LLM/{LLM_MODE}"
                                if outcome == "HOLD" and prev != "HOLD":
                                    print(f"[{tag}] {symbol}: → HOLD (conf={llm_suggestion.get('confidence'):.2f}, prev={prev})")
                                elif outcome != prev:
                                    print(f"[{tag}] {symbol}: changed {prev} → {outcome} (conf={llm_suggestion.get('confidence'):.2f})")
                                else:
                                    print(f"[{tag}] {symbol}: kept {outcome} (conf={llm_suggestion.get('confidence'):.2f})")

                    # Spike-fade
                    if SPIKE_FADE_ENABLED and outcome in ("BUY", "SELL"):
                        if df is None:
                            df = load_recent_bars(symbol, lookback="1d", interval="5m")
                        outcome = _spike_fade_adjust(symbol, df, outcome)

                    # Decisive mode
                    if outcome == "HOLD":
                        _hold_streak[symbol] = _hold_streak.get(symbol, 0) + 1
                        if _hold_streak[symbol] >= HOLD_STREAK_TRIGGER:
                            if df is None:
                                df = load_recent_bars(symbol, lookback="2d", interval="5m")
                            nudged = _decisive_nudge(symbol, outcome, df)
                            if nudged != "HOLD":
                                outcome = nudged
                                _hold_streak[symbol] = 0
                    else:
                        _hold_streak[symbol] = 0

                    latest_outcomes[symbol] = outcome or "HOLD"

                    if not outcome or outcome == "HOLD":
                        _equity_sell_streak.pop(normalize_symbol(symbol), None)
                        sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                        _maybe_hedge_fx(symbol, sma_trend)
                        continue

                    cur_qty = _current_position_qty(symbol)
                    qty = _compute_risk_based_quantity(symbol, price)
                    key = normalize_symbol(symbol)

                    db_pos = db_get_position(key)
                    db_qty = float(db_pos.quantity) if db_pos else 0.0
                    print(f"[POSCHK] {symbol}: LIVE={cur_qty} (src={'MT5' if is_forex(symbol) else 'T212'}) | DB={db_qty} | outcome={outcome}"
                          f"{'' if not USE_META_DECIDER else f' | AI={decision_action}/{decision_strategy} u={decision_uncertainty:.2f}'}")

                    # stacking guard
                    if MAX_POSITIONS_PER_SYMBOL > 0:
                        if outcome == "BUY" and cur_qty > 0.0:
                            print(f"[IN-POSITION] {symbol}: already long {cur_qty}, skipping buy.")
                            sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                            _maybe_hedge_fx(symbol, sma_trend)
                            continue
                        if outcome == "SELL" and cur_qty < 0.0:
                            print(f"[IN-POSITION] {symbol}: already short {cur_qty}, skipping sell.")
                            sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                            _maybe_hedge_fx(symbol, sma_trend)
                            continue

                    if not _rate_limit_ok(key):
                        print(f"[RATE] {symbol}: trades/hour limit reached, holding.")
                        sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                        _maybe_hedge_fx(symbol, sma_trend)
                        continue

                    side = "LONG" if outcome == "BUY" else "SHORT"
                    if not _can_reenter(key, side, price):
                        print(f"[REENTRY] {symbol}: blocked (cooldown/distance).")
                        sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                        _maybe_hedge_fx(symbol, sma_trend)
                        continue

                    print(f"[DECISION] {symbol}: {outcome} @ {price} | current_pos={cur_qty}")

                    # ---- Execute decision ----
                    if outcome == "BUY":
                        if is_forex(symbol):
                            if cur_qty < 0.0:
                                okc, infoc, realized_fx = _route_close(symbol)
                                print(f"[FLIP CLOSE] {symbol}: {infoc}")
                                if okc:
                                    db_update_position(key, +abs(cur_qty), price)
                                    if realized_fx != 0.0:
                                        _feed_close_reward(meta, symbol, realized_fx, is_fx=True)
                            ok, info = _route_open(symbol, qty)
                            print(f"[ORDER] {symbol}: {info}")
                            if ok:
                                _last_open_action[key] = decision_action or "CLASSIC"
                                _rate_mark(key)
                                db_update_position(key, +qty, price)
                                _remember_entry(key, "LONG", price)
                        else:
                            ok, info = _route_open(symbol, qty)
                            print(f"[ORDER] {symbol}: {info}")
                            if ok:
                                _last_open_action[key] = decision_action or "CLASSIC"
                                _equity_position_open_ts[key] = time.time()
                                _equity_sell_streak.pop(key, None)
                                _rate_mark(key)
                                invalidate_portfolio_cache()
                                db_update_position(key, +qty, price)
                                _remember_entry(key, "LONG", price)
                                _eq_trail_sl.pop(symbol, None)

                    elif outcome == "SELL":
                        if is_forex(symbol):
                            if cur_qty > 0.0:
                                okc, infoc, realized_fx = _route_close(symbol)
                                print(f"[FLIP CLOSE] {symbol}: {infoc}")
                                if okc:
                                    db_update_position(key, -abs(cur_qty), price)
                                    if realized_fx != 0.0:
                                        _feed_close_reward(meta, symbol, realized_fx, is_fx=True)
                            ok, info = _route_open(symbol, -qty)
                            print(f"[ORDER] {symbol}: {info}")
                            if ok:
                                _last_open_action[key] = decision_action or "CLASSIC"
                                _rate_mark(key)
                                db_update_position(key, -qty, price)
                                _remember_entry(key, "SHORT", price)
                        else:
                            # Stocks: SELL == sell-to-close (no shorting). Require N consecutive SELL signals.
                            if cur_qty <= 0.0:
                                print("[EQUITY] Short selling blocked or no holdings to reduce.")
                                _equity_sell_streak.pop(key, None)
                                continue
                            streak = _equity_sell_streak.get(key, 0) + 1
                            _equity_sell_streak[key] = streak
                            if streak < EQUITY_SELL_CONFIRM_CYCLES:
                                print(f"[EQUITY SELL CONFIRM] {symbol}: need {EQUITY_SELL_CONFIRM_CYCLES} SELLs, have {streak} — holding.")
                                continue
                            sell_qty = cur_qty
                            entry = float(getattr(db_pos, "avg_price", 0.0) or 0.0)
                            ok, info = _route_open(symbol, -sell_qty)
                            print(f"[EQUITY CLOSE] {symbol}: {info}")
                            if ok:
                                _equity_sell_streak.pop(key, None)
                                _equity_position_open_ts.pop(key, None)
                                _equity_position_open_ts.pop(symbol, None)
                                realized_eq = record_equity_close(symbol, entry, price, sell_qty)
                                _feed_close_reward(meta, symbol, realized_eq, is_fx=False)
                                _rate_mark(key)
                                invalidate_portfolio_cache()
                                db_update_position(key, 0.0, 0.0, overwrite=True)
                                _eq_trail_sl.pop(symbol, None)

                    sma_trend = analyze_sma(symbol) if is_forex(symbol) else None
                    _maybe_hedge_fx(symbol, sma_trend)

                except KeyboardInterrupt:
                    raise
                except Exception as sym_err:
                    print(f"[LOOP ERROR] {symbol}: {sym_err}")

            # --------------------------- Profit Guard pass ---------------------
            try:
                _profit_guard_run(all_symbols, latest_outcomes, meta=meta)
            except Exception as e:
                print(f"[PG] skipped this cycle: {e}")

            time.sleep(3)
    except KeyboardInterrupt:
        print("\n[STOP] Keyboard interrupt received. Exiting loop.")
    except Exception as e:
        print(f"[FATAL LOOP ERROR] {e}")
    finally:
        # Final best-effort sync to avoid stale DB positions after manual stop.
        print("[SHUTDOWN] Running final MT5/DB reconciliation...")
        try:
            mt5_sync_mm_deals_to_pnl()
        except Exception as e:
            print(f"[SHUTDOWN] MT5 PnL sync failed: {e}")
        _reconcile_live_positions(all_symbols, reason="shutdown")
