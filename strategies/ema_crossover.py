# strategies/ema_crossover.py
"""
EMA crossover: trend-following on both forex (MT5) and stocks (T212).
- Fast EMA cross above slow EMA → BUY
- Fast EMA cross below slow EMA → SELL
- Optional: require price above/below both EMAs to avoid chop.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.market_data import load_recent_bars


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def analyze_ema_crossover(
    symbol: str,
    lookback: str = "20d",
    interval: str = "15m",
    fast: int = 9,
    slow: int = 21,
    require_price_side: bool = True,
) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].astype(float)
    if len(close) < slow + 2:
        return None

    ema_f = _ema(close, fast)
    ema_s = _ema(close, slow)

    f_now, f_prev = float(ema_f.iloc[-1]), float(ema_f.iloc[-2])
    s_now, s_prev = float(ema_s.iloc[-1]), float(ema_s.iloc[-2])
    price = float(close.iloc[-1])

    bull_cross = f_prev <= s_prev and f_now > s_now
    bear_cross = f_prev >= s_prev and f_now < s_now

    if require_price_side:
        if bull_cross and price > s_now:
            return "BUY"
        if bear_cross and price < s_now:
            return "SELL"
    else:
        if bull_cross:
            return "BUY"
        if bear_cross:
            return "SELL"
    return "HOLD"
