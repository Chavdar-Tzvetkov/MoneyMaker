# strategies/breakout_strategy.py
"""
N-day high/low breakout: momentum on both forex (MT5) and stocks (T212).
- Close above N-day high → BUY (breakout up)
- Close below N-day low → SELL (breakout down)
- Optional minimum range (avoid tiny breakouts in flat markets).
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.market_data import load_recent_bars


def analyze_breakout(
    symbol: str,
    lookback: str = "30d",
    interval: str = "15m",
    n_days: int = 20,
    min_range_pct: float = 0.002,
) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    if len(close) < n_days + 2:
        return None

    # Use last N bars as "N-day" (same TF as interval)
    roll_high = high.rolling(n_days).max()
    roll_low = low.rolling(n_days).min()
    prev_high = float(roll_high.iloc[-2])
    prev_low = float(roll_low.iloc[-2])
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])

    range_ok = (prev_high - prev_low) / max(prev_low, 1e-12) >= min_range_pct if min_range_pct else True
    if not range_ok:
        return "HOLD"

    if price > prev_high and prev_close <= prev_high:
        return "BUY"
    if price < prev_low and prev_close >= prev_low:
        return "SELL"
    return "HOLD"
