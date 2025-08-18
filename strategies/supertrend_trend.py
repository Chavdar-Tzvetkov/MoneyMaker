# strategies/supertrend_trend.py
from __future__ import annotations
from typing import Optional, Tuple
import numpy as np
import pandas as pd
from utils.market_data import load_recent_bars

def _atr(h, l, c, n=10):
    prev_c = c.shift(1)
    tr = (h - l).abs().combine((h - prev_c).abs(), max).combine((l - prev_c).abs(), max)
    return tr.rolling(n).mean()

def _supertrend(h, l, c, atr_len=10, mult=3.0) -> Tuple[pd.Series, pd.Series]:
    atr = _atr(h, l, c, atr_len)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr

    st = pd.Series(index=c.index, dtype=float)
    trend = pd.Series(index=c.index, dtype=int)  # +1 bull, -1 bear

    st.iloc[0] = upper.iloc[0]
    trend.iloc[0] = 1
    for i in range(1, len(c)):
        if c.iloc[i] > st.iloc[i-1]:
            trend.iloc[i] = 1
        elif c.iloc[i] < st.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]

        if trend.iloc[i] == 1:
            st.iloc[i] = min(upper.iloc[i], st.iloc[i-1])
        else:
            st.iloc[i] = max(lower.iloc[i], st.iloc[i-1])

    return st, trend

def analyze_supertrend(symbol: str,
                       lookback="20d",
                       interval="15m",
                       atr_len: int = 10,
                       mult: float = 3.0) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty:
        return None
    if len(df) < atr_len + 5:
        return None

    h, l, c = df["High"].astype(float), df["Low"].astype(float), df["Close"].astype(float)
    st, tr = _supertrend(h, l, c, atr_len=atr_len, mult=mult)

    # signal on last completed bar vs supertrend
    last_c = float(c.iloc[-1])
    last_st = float(st.iloc[-1])
    last_tr = int(tr.iloc[-1])

    if last_tr == 1 and last_c > last_st:
        return "BUY"
    if last_tr == -1 and last_c < last_st:
        return "SELL"
    return "HOLD"

