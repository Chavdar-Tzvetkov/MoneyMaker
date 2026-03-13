"""
Market regime detection (trend vs range) per symbol.
Used by the meta-controller to prefer trend-following vs mean-reversion strategies.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional

# Defaults (overridable via config)
REGIME_ADX_PERIOD = 14
REGIME_ADX_TREND_THRESHOLD = 25.0  # ADX above this => trend; below => range


def _compute_adx(df: pd.DataFrame, period: int = REGIME_ADX_PERIOD) -> Optional[float]:
    """
    Compute ADX (Average Directional Index) from OHLC. Returns last ADX value or None.
    Uses Wilder smoothing (RMA). Expects columns: Open, High, Low, Close.
    """
    if df is None or df.empty or len(df) < period + 1:
        return None
    for col in ("High", "Low", "Close"):
        if col not in df.columns:
            return None

    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)

    # True Range
    tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))

    # Directional movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Wilder-style smoothing: EWM with alpha=1/period (approximation to RMA)
    alpha = 1.0 / period
    atr = pd.Series(tr, index=df.index).ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, np.nan)

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx = dx.fillna(0).ewm(alpha=alpha, adjust=False).mean()

    last = float(adx.iloc[-1])
    return last if not (np.isnan(last) or np.isinf(last)) else None


def get_regime(
    df: Optional[pd.DataFrame],
    adx_period: int = REGIME_ADX_PERIOD,
    trend_threshold: float = REGIME_ADX_TREND_THRESHOLD,
) -> str:
    """
    Classify market regime as "trend" or "range" from recent OHLC bars.
    - trend: ADX >= trend_threshold (directional movement dominant)
    - range: ADX < trend_threshold (sideways, mean-reversion friendly)
    Returns "unknown" if data is insufficient or invalid.
    """
    if df is None or df.empty:
        return "unknown"
    adx = _compute_adx(df, period=adx_period)
    if adx is None:
        return "unknown"
    if adx >= trend_threshold:
        return "trend"
    return "range"
