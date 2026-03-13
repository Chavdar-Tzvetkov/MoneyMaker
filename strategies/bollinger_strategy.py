# strategies/bollinger_strategy.py
"""
Bollinger Bands: mean reversion at bands with trend filter.
Works on both forex (MT5) and stocks (T212).

- Buy when price touches or crosses below lower band and trend is up (price > middle).
- Sell when price touches or crosses above upper band and trend is down (price < middle).
- Optional: require RSI confirmation to avoid catching falling/rising knives.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.market_data import load_recent_bars


def _bb(close: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def analyze_bollinger(
    symbol: str,
    lookback: str = "20d",
    interval: str = "15m",
    window: int = 20,
    num_std: float = 2.0,
    buffer_pct: float = 0.001,
) -> Optional[str]:
    df = load_recent_bars(symbol, lookback=lookback, interval=interval)
    if df is None or df.empty or "Close" not in df.columns:
        return None

    close = df["Close"].astype(float)
    if len(close) < window + 2:
        return None

    upper, mid, lower = _bb(close, window, num_std)
    u, m, l = float(upper.iloc[-1]), float(mid.iloc[-1]), float(lower.iloc[-1])
    prev_u, prev_m, prev_l = float(upper.iloc[-2]), float(mid.iloc[-2]), float(lower.iloc[-2])
    price = float(close.iloc[-1])
    prev_price = float(close.iloc[-2])

    if m <= 0:
        return None

    buf = price * buffer_pct
    # Mean reversion: buy near lower band when not in strong downtrend (price >= mid - buffer)
    at_lower = price <= l + buf or (prev_price >= prev_l and price < prev_price)
    at_upper = price >= u - buf or (prev_price <= prev_u and price > prev_price)

    if at_lower and price >= m - buf:
        return "BUY"
    if at_upper and price <= m + buf:
        return "SELL"
    return "HOLD"
