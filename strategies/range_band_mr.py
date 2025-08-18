# strategies/range_band_mr.py
from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np
from utils.market_data import load_recent_bars

def analyze_range_mr(
    symbol: str,
    lookback: str = "3d",
    interval: str = "1m",
    length: int = 60,           # ~1h on M1
    z_entry: float = 1.2,       # enter when |z| >= 1.2
    z_exit: float = 0.2,        # hold if already in pos; otherwise ignore small z
    slope_thr: float = 0.0004,  # ~4 bps slope gate (flat midline)
    min_bw: float = 0.0008,     # 8 bps minimum band width (ensure amplitude)
    max_bw: float = 0.0040      # 40 bps maximum band width (avoid massive trends)
) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty:
        return None

    c = df["Close"].astype(float)
    if len(c) < length + 5:
        return None

    mid = c.rolling(length).mean()
    sd = c.rolling(length).std(ddof=0)
    if sd.iloc[-1] is None or sd.iloc[-1] == 0:
        return "HOLD"

    upper = mid + 2.0 * sd
    lower = mid - 2.0 * sd

    # regime gates: flat midline and “reasonable” band
    mid_prev = float(mid.iloc[-length//2])
    mid_now  = float(mid.iloc[-1])
    if mid_prev <= 0:
        return "HOLD"
    slope = abs(mid_now - mid_prev) / mid_prev

    bw = (float(upper.iloc[-1]) - float(lower.iloc[-1])) / max(float(mid.iloc[-1]), 1e-12)

    if not (slope < slope_thr and min_bw <= bw <= max_bw):
        return "HOLD"

    z = (float(c.iloc[-1]) - float(mid.iloc[-1])) / float(sd.iloc[-1])

    # fade extremes back to midline
    if z >= z_entry:
        return "SELL"
    if z <= -z_entry:
        return "BUY"

    # if it’s too close to the middle, do nothing
    if abs(z) < z_exit:
        return "HOLD"

    return "HOLD"

