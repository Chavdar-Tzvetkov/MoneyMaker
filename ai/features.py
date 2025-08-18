# ai/features.py
from __future__ import annotations
import numpy as np
import pandas as pd

def compute_features(df: pd.DataFrame) -> np.ndarray:
    """
    Expect df with columns: Open, High, Low, Close (yfinance style).
    Returns a 10-dim feature vector for the meta-policy.
    """
    if df is None or df.empty:
        return np.zeros(10, dtype=float)

    # Ensure required columns exist
    for col in ("Open", "High", "Low", "Close"):
        if col not in df.columns:
            return np.zeros(10, dtype=float)

    # Drop obvious NaNs
    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if df.empty:
        return np.zeros(10, dtype=float)

    close = df["Close"].astype(float)

    # 1) Last return
    ret1 = float(close.pct_change().iloc[-1]) if len(close) > 1 else 0.0
    if np.isnan(ret1) or np.isinf(ret1):
        ret1 = 0.0

    # 2) Rolling volatility (20)
    if len(close) > 20:
        vol_series = close.pct_change().rolling(20).std()
        vol_val = vol_series.iloc[-1]
        vol = float(vol_val) if pd.notna(vol_val) else 0.0
    else:
        vol = 0.0

    # Helper: momentum over n bars
    def mom(n: int) -> float:
        if len(close) > n:
            val = float(close.iloc[-1] / close.iloc[-n] - 1.0)
            return 0.0 if np.isnan(val) or np.isinf(val) else val
        return 0.0

    m5  = mom(5)
    m20 = mom(20)
    m50 = mom(50)

    # 3) Simple MA deltas (guard small samples)
    sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float(close.iloc[-1])

    if np.isnan(sma20):
        sma20 = float(close.iloc[-1])
    if np.isnan(sma50) or sma50 == 0.0:
        last = float(close.iloc[-1])
        sma50 = last if last != 0.0 else 1.0

    delta = (sma20 - sma50) / (sma50 if sma50 != 0.0 else 1.0)

    # 4) Range compression (20)
    high_series = df["High"].astype(float)
    low_series  = df["Low"].astype(float)
    if len(df) >= 20:
        high = float(high_series.rolling(20).max().iloc[-1])
        low  = float(low_series.rolling(20).min().iloc[-1])
    else:
        high = float(high_series.iloc[-1])
        low  = float(low_series.iloc[-1])

    if np.isnan(high) or np.isnan(low) or low == 0.0:
        rng = 0.0
    else:
        rng = (high - low) / low

    # 5) Assemble feature vector (cast booleans to floats)
    x = np.array([
        ret1,
        vol,
        m5,
        m20,
        m50,
        delta,
        rng,
        float(sma20 > sma50),
        float(abs(delta) < 0.001),
        1.0,  # bias
    ], dtype=float)

    x[np.isnan(x)] = 0.0
    x = np.clip(x, -5, 5)
    return x
