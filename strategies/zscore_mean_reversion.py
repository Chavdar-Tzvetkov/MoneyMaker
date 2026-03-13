# strategies/zscore_mean_reversion.py
"""
Z-score mean reversion: trade extremes on both forex (MT5) and stocks (T212).
- Price z-score > 2 (expensive vs recent mean) → SELL
- Price z-score < -2 (cheap vs recent mean) → BUY
- Uses rolling mean and std over N bars.
"""
from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd
from utils.market_data import load_recent_bars


def analyze_zscore(
    symbol: str,
    lookback: str = "15d",
    interval: str = "15m",
    length: int = 50,
    entry_z: float = 2.0,
    exit_buffer: float = 0.2,
) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].astype(float)
    if len(close) < length + 2:
        return None

    mean = close.rolling(length).mean()
    std = close.rolling(length).std()
    z = (close - mean) / (std + 1e-12)

    z_now = float(z.iloc[-1])
    if np.isnan(z_now) or np.isinf(z_now):
        return "HOLD"

    if z_now <= -entry_z:
        return "BUY"
    if z_now >= entry_z:
        return "SELL"
    return "HOLD"
