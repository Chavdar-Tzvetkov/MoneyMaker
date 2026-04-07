# strategies/sma_strategy.py
"""
Per-symbol SMA strategy with split sensitivity for forex vs stocks.

Decision per symbol:
  delta = (SMA_FAST - SMA_SLOW) / SMA_SLOW
  if   delta >= BUY  -> BUY
  elif delta <= SELL -> SELL
  elif |delta| <= HOLD -> HOLD (neutral band)
  else -> HOLD
"""

from __future__ import annotations
from typing import Optional
import math
import pandas as pd

from utils.market_data import get_clean_data
from utils.symbols import is_forex, is_stock
from config import SMA_WINDOWS, SMA_THRESHOLDS

def _fmt(x: float, digits: int = 4) -> str:
    try:
        return f"{x:.{digits}f}"
    except Exception:
        return str(x)

def _safe_sma(close: pd.Series, window: int) -> Optional[float]:
    if close is None or len(close) < window:
        return None
    v = close.rolling(window=window).mean().iloc[-1]
    if v is None or math.isnan(v):
        return None
    return float(v)

def _bucket_for(symbol: str) -> str:
    if is_forex(symbol):
        return "forex"
    return "stocks"  # default bucket for everything else

def analyze_sma(
    symbol: str,
    *,
    fast: int | None = None,
    slow: int | None = None,
    hold_band: float | None = None,
    buy_th: float | None = None,
    sell_th: float | None = None,
    lookback_days: int = 120,
) -> Optional[str]:
    bucket = _bucket_for(symbol)
    wins = SMA_WINDOWS.get(bucket, SMA_WINDOWS["stocks"])
    th   = SMA_THRESHOLDS.get(bucket, SMA_THRESHOLDS["stocks"])

    fast_w = int(fast if fast is not None else wins["fast"])
    slow_w = int(slow if slow is not None else wins["slow"])
    buy_th = float(buy_th if buy_th is not None else th["buy"])
    sell_th = float(sell_th if sell_th is not None else th["sell"])
    hold_band = float(hold_band if hold_band is not None else th["hold"])

    print(f"[SMA] Analyzing {symbol} ({bucket})")

    df = get_clean_data(symbol, days=max(60, int(lookback_days or 120)))
    if df is None or df.empty or "Close" not in df:
        print(f"[SMA] No data for {symbol}")
        return None

    close = df["Close"].dropna()
    if len(close) < max(fast_w, slow_w) + 1:
        print(f"[SMA] Not enough data for {symbol}")
        return None

    sma_fast = _safe_sma(close, fast_w)
    sma_slow = _safe_sma(close, slow_w)
    if sma_fast is None or sma_slow is None or sma_slow == 0:
        print(f"[SMA] Missing SMA values for {symbol}")
        return None

    ratio = sma_fast / sma_slow
    delta = (sma_fast - sma_slow) / sma_slow

    print(
        f"[SMA VALS] {symbol}: SMA{fast_w}={_fmt(sma_fast, 2)}, "
        f"SMA{slow_w}={_fmt(sma_slow, 2)} | thresholds({bucket}) "
        f"buy>={buy_th} sell<={sell_th} hold±{hold_band}"
    )

    if abs(delta) <= hold_band:
        print(f"[SMA] HOLD — ratio={_fmt(ratio, 4)} delta={_fmt(delta, 4)}")
        return "HOLD"

    if delta >= buy_th:
        print(f"[SMA] BUY — ratio={_fmt(ratio, 4)} delta={_fmt(delta, 4)}")
        return "BUY"

    if delta <= sell_th:
        print(f"[SMA] SELL — ratio={_fmt(ratio, 4)} delta={_fmt(delta, 4)}")
        return "SELL"

    print(f"[SMA] HOLD — ratio={_fmt(ratio, 4)} delta={_fmt(delta, 4)}")
    return "HOLD"
