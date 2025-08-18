# strategies/macd_trend.py
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from utils.market_data import load_recent_bars

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()

def analyze_macd(symbol: str,
                 lookback="20d",
                 interval="15m",
                 fast=12, slow=26, signal=9,
                 slope_len: int = 50) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty:
        return None

    c = df["Close"].astype(float)
    if len(c) < max(slow, signal, slope_len) + 5:
        return None

    ema_fast = _ema(c, fast)
    ema_slow = _ema(c, slow)
    macd = ema_fast - ema_slow
    macd_sig = _ema(macd, signal)
    hist = macd - macd_sig

    ema_slope = _ema(c, slope_len)
    slope_up = float(ema_slope.iloc[-1]) > float(ema_slope.iloc[-5])

    macd_now, macd_prev = float(macd.iloc[-1]), float(macd.iloc[-2])
    sig_now,  sig_prev  = float(macd_sig.iloc[-1]), float(macd_sig.iloc[-2])

    bull_cross = macd_prev <= sig_prev and macd_now > sig_now and macd_now > 0
    bear_cross = macd_prev >= sig_prev and macd_now < sig_now and macd_now < 0

    if bull_cross and slope_up:
        return "BUY"
    if bear_cross and not slope_up:
        return "SELL"
    return "HOLD"

