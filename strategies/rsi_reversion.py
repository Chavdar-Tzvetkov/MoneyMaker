# strategies/rsi_reversion.py
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from utils.market_data import load_recent_bars

def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0.0)
    dn = -d.clip(upper=0.0)
    rs = (up.rolling(n).mean()) / (dn.rolling(n).mean() + 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)

def analyze_rsi(symbol: str,
                lookback: str = "10d",
                interval: str = "15m",
                rsi_len: int = 14,
                overbought: float = 70.0,
                oversold: float = 30.0,
                trend_sma: int = 50,
                buffer_bps: float = 3.0  # small buffer to avoid micro-flips
                ) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty:
        return None

    close = df["Close"].astype(float)
    if len(close) < max(rsi_len, trend_sma) + 2:
        return None

    rsi = _rsi(close, rsi_len)
    sma = close.rolling(trend_sma).mean()
    c = float(close.iloc[-1])
    r = float(rsi.iloc[-1])
    s = float(sma.iloc[-1])

    # Trend filter: only long if above SMA, only short if below SMA
    buf = c * (buffer_bps / 10000.0)
    if r <= oversold and c > s + buf:
        return "BUY"
    if r >= overbought and c < s - buf:
        return "SELL"
    return "HOLD"

