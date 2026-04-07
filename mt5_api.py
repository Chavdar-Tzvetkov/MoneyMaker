# mt5_api.py
"""
MT5 API wrapper: connection handling, price fetching, opening/closing market orders,
with safe comments, price rounding, volume normalization, broker fill-policy fallback,
automatic volume capping by free margin, and SL/TP modification.
Also adds realized PnL capture on close (writes DailyPnL).
"""

from __future__ import annotations
from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timedelta
import os, re
import MetaTrader5 as mt5
import pandas as pd
from dotenv import load_dotenv
from utils.symbols import normalize_symbol
from services.pnl_service import record_fx_close_profit

load_dotenv()

# Track MT5 deal tickets we've already logged into DailyPnL during this
# process lifetime. This gives basic protection against double-counting
# if close handling is retried or invoked from multiple call sites, or
# when we also reconcile from history in the live loop.
_logged_deal_ids: set[int] = set()
MM_MAGIC = int(os.getenv("MM_MAGIC", "606060"))

# ---------- connection ----------
def initialize_mt5() -> bool:
    login = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    path = os.getenv("MT5_EXE_PATH", None)
    if not login or not password or not server:
        print("[MT5] Missing login/password/server in environment variables.")
        return False
    if not mt5.initialize(path):
        print(f"[MT5] initialize() failed: {mt5.last_error()}")
        return False
    if not mt5.login(login, password=password, server=server):
        print(f"[MT5] login() failed: {mt5.last_error()}")
        return False
    print(f"[MT5] Connected to account #{login}")
    return True

def shutdown_mt5():
    mt5.shutdown()
    print("[MT5] Connection closed.")


# ---------- sessions ----------
def is_symbol_tradable_now(symbol: str, now: datetime | None = None) -> bool:
    """
    Return True if the symbol is tradable *right now*.
    Prefer broker session windows via mt5.symbol_info_session_trade();
    fall back to generic market hours (utils.market_hours.is_market_open)
    when the API isn't available or yields no active session.
    """
    sym = normalize_symbol(symbol)
    info = mt5.symbol_info(sym)
    if info is None:
        return False
    if not info.visible:
        mt5.symbol_select(sym, True)

    # trade_mode: 0=disabled, 1=longonly, 2=shortonly, 3=closeonly, 4=full
    trade_mode = getattr(info, "trade_mode", 4)
    if trade_mode in (0, 3):
        return False

    now = now or datetime.now()

    # Prefer broker sessions if available
    if hasattr(mt5, "symbol_info_session_trade"):
        weekday = now.weekday()  # 0=Mon..6=Sun
        cur_sec = now.hour * 3600 + now.minute * 60 + now.second

        # Iterate session slots (0..9)
        for idx in range(10):
            sess = mt5.symbol_info_session_trade(sym, weekday, idx)
            if sess is None:
                break
            tf = getattr(sess, "time_from", None)
            tt = getattr(sess, "time_to", None)
            if tf is None or tt is None:
                continue
            if tf <= cur_sec <= tt:
                return True
        # If no active session matched, fall back to generic hours below.

    # Fallback: generic market hours (your utils/market_hours.py)
    try:
        from utils.market_hours import is_market_open as _is_open_generic
        # Use the *original* symbol string so suffixes like '=X' are preserved
        return _is_open_generic(symbol)
    except Exception:
        # Last-resort: if broker allows full trading mode, assume tradable
        return trade_mode == 4


def count_open_positions(prefixes=('EUR', 'USD', 'GBP', 'JPY', 'CHF', 'AUD', 'CAD', 'NZD')) -> int:
    """Count open positions for common FX prefixes; lightweight concurrency cap."""
    positions = mt5.positions_get()
    if not positions:
        return 0
    cnt = 0
    for p in positions:
        sym = getattr(p, "symbol", "") or ""
        # FX pairs often start with a currency code; simple heuristic
        if any(sym.startswith(px) for px in prefixes):
            cnt += 1
    return cnt
# ---------- utils ----------
def _safe_comment(prefix: str) -> str:
    ts = datetime.now().strftime("%m%d%H%M%S")
    return re.sub(r"[^A-Za-z0-9 _-]", "", f"{prefix} {ts}")[:30]

def _ensure_symbol_ready(symbol: str) -> Tuple[bool, str]:
    info = mt5.symbol_info(symbol)
    if info is None:
        return False, f"Symbol {symbol} not found in MT5."
    if not info.visible and not mt5.symbol_select(symbol, True):
        return False, f"Symbol {symbol} not visible and cannot be selected."
    if info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        return False, f"Trading disabled for {symbol}."
    return True, "OK"

def _normalize_volume(volume: float, info) -> float:
    if volume <= 0:
        return 0.0
    vol = max(float(volume), float(info.volume_min))
    vol = min(vol, float(info.volume_max))
    step = float(info.volume_step) or 0.01
    steps = int((vol - float(info.volume_min)) / step + 1e-9)
    return round(float(info.volume_min) + steps * step, 2)

def _round_price(sym_info, price: float) -> float:
    tick = getattr(sym_info, "trade_tick_size", 0.0) or getattr(sym_info, "point", 0.0) or 0.0
    if tick and tick > 0:
        steps = round(price / tick)
        return round(steps * tick, 10)
    digits = getattr(sym_info, "digits", 5) or 5
    return round(price, digits)

def _pick_fill_sequence(info) -> list[int]:
    preferred = getattr(info, "fill_policy", None)
    seq = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC]
    if preferred in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN, mt5.ORDER_FILLING_IOC):
        seq = [preferred] + [m for m in seq if m != preferred]
    return seq

def _cap_volume_by_margin(symbol: str, order_type: int, desired_vol: float, price: float, info, safety: float = 0.85) -> float:
    acct = mt5.account_info()
    if not acct:
        return 0.0
    free = float(acct.margin_free or 0.0)
    if free <= 0:
        return 0.0
    base = max(float(info.volume_min), 0.10)
    m = mt5.order_calc_margin(order_type, symbol, base, price)
    if m is None or m <= 0:
        base = float(info.volume_min)
        m = mt5.order_calc_margin(order_type, symbol, base, price)
        if m is None or m <= 0:
            return 0.0
    max_vol_est = (free * safety) / m * base
    target = min(desired_vol, max_vol_est)
    if target < float(info.volume_min):
        return 0.0
    return _normalize_volume(target, info)

def get_account_equity() -> float:
    """
    Return current MT5 account equity (float) or 0.0 if unavailable.
    Used by risk-based position sizing in the live loop.
    """
    try:
        acct = mt5.account_info()
        if not acct:
            return 0.0
        return float(getattr(acct, "equity", 0.0) or 0.0)
    except Exception:
        return 0.0

# ---------- public price/position ----------

def sync_new_mm_deals_to_pnl(window_hours: int = 24) -> None:
    """
    Scan recent MT5 deal history for EA-generated closing deals (those with
    comments starting with 'MM ') and log any *new* realized PnL into
    DailyPnL. This complements per-position close logging so that:
      - SL/TP triggered at the broker
      - manual closes in MT5 for MM-tagged trades
    are still reflected in the bot's PnL accounting.
    """
    try:
        to_dt = datetime.now()
        frm = to_dt - timedelta(hours=max(1, int(window_hours)))
        deals = mt5.history_deals_get(frm, to_dt) or []

        allowed_entries = {
            getattr(mt5, "DEAL_ENTRY_OUT", None),
            getattr(mt5, "DEAL_ENTRY_OUT_BY", None),
            getattr(mt5, "DEAL_ENTRY_INOUT", None),
        }
        entry_filter_enabled = any(e is not None for e in allowed_entries)

        for d in deals:
            comment = (getattr(d, "comment", "") or "").strip()
            magic = int(getattr(d, "magic", 0) or 0)
            # Prefer explicit bot magic; keep comment-prefix fallback for backward compatibility.
            if magic != MM_MAGIC and not comment.startswith("MM "):
                continue

            if entry_filter_enabled:
                entry_val = getattr(d, "entry", None)
                if entry_val not in allowed_entries:
                    continue

            deal_ticket = int(getattr(d, "ticket", 0) or 0)
            if deal_ticket in _logged_deal_ids:
                continue

            profit = float(getattr(d, "profit", 0.0) or 0.0)
            if profit != 0.0:
                record_fx_close_profit(profit)
            _logged_deal_ids.add(deal_ticket)
    except Exception:
        # Never let PnL sync issues break the main trading loop.
        pass
def get_current_price(symbol: str) -> Optional[float]:
    sym = normalize_symbol(symbol)
    tick = mt5.symbol_info_tick(sym)
    if not tick:
        print(f"[MT5] No tick for {sym}")
        return None
    if tick.bid and tick.ask:
        return (tick.bid + tick.ask) / 2.0
    return tick.last or None

def get_live_tick(symbol: str) -> Optional[Any]:
    return mt5.symbol_info_tick(normalize_symbol(symbol))

def _timeframe_from_interval(interval: str) -> Optional[int]:
    key = (interval or "").strip().lower()
    mapping = {
        "1m": mt5.TIMEFRAME_M1,
        "2m": mt5.TIMEFRAME_M2,
        "3m": mt5.TIMEFRAME_M3,
        "4m": mt5.TIMEFRAME_M4,
        "5m": mt5.TIMEFRAME_M5,
        "6m": mt5.TIMEFRAME_M6,
        "10m": mt5.TIMEFRAME_M10,
        "12m": mt5.TIMEFRAME_M12,
        "15m": mt5.TIMEFRAME_M15,
        "20m": mt5.TIMEFRAME_M20,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "2h": mt5.TIMEFRAME_H2,
        "3h": mt5.TIMEFRAME_H3,
        "4h": mt5.TIMEFRAME_H4,
        "6h": mt5.TIMEFRAME_H6,
        "8h": mt5.TIMEFRAME_H8,
        "12h": mt5.TIMEFRAME_H12,
        "1d": mt5.TIMEFRAME_D1,
    }
    return mapping.get(key)

def get_recent_bars(
    symbol: str,
    bars: int | None = None,
    lookback_days: int | None = None,
    interval: str = "5m",
) -> Optional[pd.DataFrame]:
    """
    Fetch recent OHLC bars from MT5 as a pandas DataFrame.
    Returns columns: time, open, high, low, close, tick_volume, spread, real_volume.
    """
    sym = normalize_symbol(symbol)
    tf = _timeframe_from_interval(interval)
    if tf is None:
        return None
    ok, _ = _ensure_symbol_ready(sym)
    if not ok:
        return None

    count = int(bars or 0)
    if count <= 0:
        days = max(1, int(lookback_days or 2))
        # rough fallback (enough for indicators + guards)
        if interval.endswith("m"):
            count = max(200, int(days * 24 * 60 / max(1, int(interval[:-1]))))
        elif interval.endswith("h"):
            count = max(200, int(days * 24 / max(1, int(interval[:-1]))))
        else:
            count = max(200, days)

    rates = mt5.copy_rates_from_pos(sym, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    if df.empty:
        return None
    return df

def get_position(symbol: str) -> Optional[Dict[str, Any]]:
    sym = normalize_symbol(symbol)
    positions = mt5.positions_get(symbol=sym)
    if not positions:
        return None
    p = positions[0]
    return {
        "ticket": p.ticket,
        "type": p.type,           # 0=BUY, 1=SELL
        "volume": p.volume,
        "price_open": p.price_open,
        "profit": p.profit,
        "sl": getattr(p, "sl", 0.0),
        "tp": getattr(p, "tp", 0.0),
        "symbol": sym,
        "time": getattr(p, "time", None),
        "time_msc": getattr(p, "time_msc", None),
    }

# ---------- orders ----------
def place_market_order(symbol: str, quantity: float, tp_pct: float | None = None, sl_pct: float | None = None) -> Tuple[bool, str]:
    sym = normalize_symbol(symbol)
    ok, msg = _ensure_symbol_ready(sym)
    if not ok:
        return False, msg

    info = mt5.symbol_info(sym)
    if info is None:
        return False, f"symbol_info({sym}) returned None"

    tick = mt5.symbol_info_tick(sym)
    if not tick:
        return False, f"No tick for {sym}"

    is_buy = quantity > 0
    price = tick.ask if is_buy else tick.bid
    side = "BUY" if is_buy else "SELL"
    if not price or price <= 0:
        return False, f"No {'ask' if is_buy else 'bid'} price for {sym}"

    # Execution-quality gate: skip entries when spread is abnormally wide.
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    if bid > 0.0 and ask > 0.0 and ask >= bid:
        spread_abs = ask - bid
        mid = (ask + bid) / 2.0
        if mid > 0.0:
            max_spread_rel = float(os.getenv("MT5_MAX_SPREAD_REL", "0.00035"))  # 3.5 bps default
            spread_rel = spread_abs / mid
            if max_spread_rel > 0 and spread_rel > max_spread_rel:
                return False, (
                    f"Spread too wide for {sym}: rel={spread_rel:.5f} > max={max_spread_rel:.5f} "
                    f"(bid={bid:.5f}, ask={ask:.5f})"
                )

        max_spread_points = float(os.getenv("MT5_MAX_SPREAD_POINTS", "0"))  # 0 disables points check
        point = float(getattr(info, "point", 0.0) or 0.0)
        if max_spread_points > 0 and point > 0:
            spread_points = spread_abs / point
            if spread_points > max_spread_points:
                return False, (
                    f"Spread too wide for {sym}: {spread_points:.1f} points > max={max_spread_points:.1f}"
                )

    vol_desired = _normalize_volume(abs(float(quantity)), info)
    # Global lot cap (matches config MAX_FX_LOTS_PER_ORDER) — last line of defence vs oversized orders.
    _lot_cap = float(os.getenv("MAX_FX_LOTS_PER_ORDER", "0.35"))
    if _lot_cap > 0 and vol_desired > _lot_cap:
        vol_desired = _normalize_volume(_lot_cap, info)
    order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
    vol = _cap_volume_by_margin(sym, order_type, vol_desired, price, info, safety=0.85)
    if vol <= 0:
        acct = mt5.account_info()
        free = getattr(acct, "margin_free", 0.0) if acct else 0.0
        return False, f"No money: free_margin={free:.2f} desired_vol={vol_desired} symbol={sym}"

    sl_price = tp_price = None
    if tp_pct and tp_pct > 0:
        tp_price = _round_price(info, price * (1 + tp_pct) if is_buy else price * (1 - tp_pct))
    if sl_pct and sl_pct > 0:
        sl_price = _round_price(info, price * (1 - sl_pct) if is_buy else price * (1 + sl_pct))

    fill_sequence = _pick_fill_sequence(info)
    last_err = None
    for fill_mode in fill_sequence:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": vol,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_mode,
            "comment": _safe_comment(f"MM {side}"),
            "magic": MM_MAGIC,
        }
        if tp_price is not None:
            request["tp"] = tp_price
        if sl_price is not None:
            request["sl"] = sl_price

        result = mt5.order_send(request)
        if result is None:
            last_err = f"order_send None; last_error={mt5.last_error()}; request={request}"
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return True, f"ORDER OK [{side}] {sym}: ticket={result.order}, price={price}, vol={vol}, fill={fill_mode}, tp={tp_price}, sl={sl_price}"
        last_err = f"retcode={result.retcode} comment={getattr(result, 'comment', '')} fill={fill_mode}"
        if result.retcode == 10030:  # Unsupported filling mode
            continue
    return False, f"ORDER FAIL [{side}] {sym}: {last_err}"

def close_position_market(symbol: str) -> Tuple[bool, str, float]:
    sym = normalize_symbol(symbol)
    pos = get_position(sym)
    if not pos:
        return False, f"No open position to close for {sym}", 0.0

    info = mt5.symbol_info(sym)
    if info is None:
        return False, f"symbol_info({sym}) returned None", 0.0
    tick = mt5.symbol_info_tick(sym)
    if not tick:
        return False, f"No tick for {sym}", 0.0

    is_buy = (pos["type"] == mt5.POSITION_TYPE_BUY)
    price = tick.bid if is_buy else tick.ask
    side = "SELL" if is_buy else "BUY"
    if not price or price <= 0:
        return False, f"No close price for {sym}", 0.0

    fill_sequence = _pick_fill_sequence(info)
    last_err = None
    for fill_mode in fill_sequence:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": pos["ticket"],
            "symbol": sym,
            "volume": pos["volume"],
            "type": (mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY),
            "price": price,
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_mode,
            "comment": _safe_comment("MM CLOSE"),
            "magic": MM_MAGIC,
        }
        result = mt5.order_send(request)
        if result is None:
            last_err = f"close order_send None; last_error={mt5.last_error()}; request={request}"
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            realized_total = 0.0
            # --- realized PnL logging via history_deals_get ---
            try:
                to_dt = datetime.now()
                # Narrower window to reduce ambiguity while still covering the
                # most recent close. Typical MT5 history calls are cheap.
                frm = to_dt - timedelta(hours=1)
                deals = mt5.history_deals_get(frm, to_dt) or []

                realized_total = 0.0

                # Determine which deal.entry values represent a closing leg on
                # this broker; fall back to no entry filter if constants are
                # not exposed by the MetaTrader5 module.
                allowed_entries = {
                    getattr(mt5, "DEAL_ENTRY_OUT", None),
                    getattr(mt5, "DEAL_ENTRY_OUT_BY", None),
                    getattr(mt5, "DEAL_ENTRY_INOUT", None),
                }
                entry_filter_enabled = any(e is not None for e in allowed_entries)

                # Iterate in chronological order so that if multiple partial
                # closes occurred, we accumulate their profit while only
                # counting each deal ticket once per process lifetime.
                for d in sorted(deals, key=lambda x: getattr(x, "time", 0)):
                    if getattr(d, "position_id", 0) != pos["ticket"]:
                        continue
                    if getattr(d, "symbol", "") != sym:
                        continue

                    if entry_filter_enabled:
                        entry_val = getattr(d, "entry", None)
                        if entry_val not in allowed_entries:
                            continue

                    deal_ticket = int(getattr(d, "ticket", 0) or 0)
                    if deal_ticket in _logged_deal_ids:
                        continue

                    profit = float(getattr(d, "profit", 0.0) or 0.0)
                    if profit != 0.0:
                        realized_total += profit
                        _logged_deal_ids.add(deal_ticket)

                if realized_total != 0.0:
                    record_fx_close_profit(realized_total)
            except Exception:
                # PnL logging failures must not break order closing.
                pass
            return True, f"CLOSE OK [{side}] {sym}: ticket={result.order}, price={price}, vol={pos['volume']}, fill={fill_mode}", realized_total
        last_err = f"retcode={result.retcode} comment={getattr(result, 'comment', '')} fill={fill_mode}"
        if result.retcode == 10030:
            continue
    return False, f"CLOSE FAIL [{side}] {sym}: {last_err}", 0.0

def modify_position_sl_tp(symbol: str, sl: Optional[float] = None, tp: Optional[float] = None) -> Tuple[bool, str]:
    sym = normalize_symbol(symbol)
    pos = get_position(sym)
    if not pos:
        return False, f"No open position for {sym}"
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": pos["ticket"],
        "symbol": sym,
        "sl": sl if sl is not None else pos["sl"],
        "tp": tp if tp is not None else pos["tp"],
        "comment": _safe_comment("MM MOD"),
    }
    result = mt5.order_send(req)
    if result is None:
        return False, f"SLTP modify None; last_error={mt5.last_error()}; request={req}"
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        return True, f"SLTP modify OK {sym}: sl={req['sl']} tp={req['tp']}"
    return False, f"SLTP modify FAIL {sym}: retcode={result.retcode} comment={getattr(result,'comment','')}"
