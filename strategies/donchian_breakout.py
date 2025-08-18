# strategies/donchian_breakout.py
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from utils.market_data import load_recent_bars

def _atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    prev_c = c.shift(1)
    tr = (h - l).abs().combine((h - prev_c).abs(), max).combine((l - prev_c).abs(), max)
    return tr.rolling(n).mean()

def analyze_donchian_breakout(symbol: str,
                               lookback: str = "20d",
                               interval: str = "30m",
                               ch_len: int = 20,
                               atr_len: int = 14,
                               min_range_bps: float = 12.0,  # breakout must exceed this
                               buffer_atr: float = 0.25       # require close to clear band by 0.25*ATR
                               ) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty:
        return None

    h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    if len(df) < max(ch_len, atr_len) + 2:
        return None

    upper = h.rolling(ch_len).max()
    lower = l.rolling(ch_len).min()
    atr = _atr(h, l, c, atr_len)

    up = float(upper.iloc[-2])  # use previous completed bar’s channel
    lo = float(lower.iloc[-2])
    at = float(atr.iloc[-2])
    px = float(c.iloc[-1])

    if at <= 0 or up <= 0 or lo <= 0:
        return "HOLD"

    # ensure the channel is "wide enough"
    rng_bps = ((up - lo) / ((up + lo) / 2.0)) * 10000.0
    if rng_bps < min_range_bps:
        return "HOLD"

    # breakout conditions with ATR buffer
    if px > up + buffer_atr * at:
        return "BUY"
    if px < lo - buffer_atr * at:
        return "SELL"
    return "HOLD"

