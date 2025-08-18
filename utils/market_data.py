from __future__ import annotations

import time
from typing import Optional
import pandas as pd
import yfinance as yf

from utils.symbols import to_yf_symbol, to_mt5_symbol, is_forex

# --- Optional MT5 hooks (gracefully degrade if missing) ----------------------
_mt5_ok = False
_mt5_get_price = None
_mt5_get_recent_bars = None
try:
    from mt5_api import get_current_price as _mt5_get_price  # required for live FX ticks
    _mt5_ok = True
    try:
        # Optional: if your mt5_api exposes it, we'll use it for FX candles
        from mt5_api import get_recent_bars as _mt5_get_recent_bars
    except Exception:
        _mt5_get_recent_bars = None
except Exception:
    _mt5_ok = False
    _mt5_get_price = None
    _mt5_get_recent_bars = None

REQUIRED = ("Open", "High", "Low", "Close")


def _normalize_ohlc_columns(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Normalize any OHLC frame (single or MultiIndex columns) to columns exactly
    ['Open','High','Low','Close']. If only 'Adj Close' exists, duplicate it
    to build OHLC. Returns None if we can't build a valid OHLC view.
    """
    if df is None or df.empty:
        return None

    # If MultiIndex columns, try to select the OHLC level
    if isinstance(df.columns, pd.MultiIndex):
        last = set(df.columns.get_level_values(-1))
        first = set(df.columns.get_level_values(0))
        if set(REQUIRED).issubset(last):
            df = df.copy()
            df.columns = df.columns.get_level_values(-1)
        elif set(REQUIRED).issubset(first):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        else:
            new_cols = []
            for col in df.columns:
                if isinstance(col, tuple):
                    if "Open" in col:
                        new_cols.append("Open")
                    elif "High" in col:
                        new_cols.append("High")
                    elif "Low" in col:
                        new_cols.append("Low")
                    elif "Close" in col:
                        new_cols.append("Close")
                    elif "Adj Close" in col:
                        new_cols.append("Adj Close")
                    else:
                        new_cols.append(col[-1])
                else:
                    new_cols.append(col)
            df = df.copy()
            df.columns = new_cols

    # Normalize case / aliases
    rename_map = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl == "open":
            rename_map[c] = "Open"
        elif cl == "high":
            rename_map[c] = "High"
        elif cl == "low":
            rename_map[c] = "Low"
        elif cl == "close":
            rename_map[c] = "Close"
        elif cl in ("adj close", "adj_close", "adjusted close"):
            rename_map[c] = "Adj Close"
        elif cl in ("ask", "bid", "price"):  # in case source gives single 'price'
            # we'll map to Close and synthesize the rest below
            rename_map[c] = "Close"
    if rename_map:
        df = df.rename(columns=rename_map)

    cols = set(df.columns)

    # If we have Adj Close only, synthesize OHLC from it
    if "Close" not in cols and "Adj Close" in cols:
        df = df.copy()
        df["Close"] = df["Adj Close"]

    # If some OHLC missing but Close exists, duplicate Close to fill gaps
    if "Close" in df.columns:
        for c in REQUIRED:
            if c not in df.columns:
                df[c] = df["Close"]

    # Final check
    if not set(REQUIRED).issubset(df.columns):
        return None

    out = df.loc[:, list(REQUIRED)].dropna()
    return out if not out.empty else None


# ------------------------- MT5 helpers (FX only) ------------------------------
def _mt5_interval_to_minutes(interval: str) -> Optional[int]:
    """
    Map string intervals like '1m','5m','15m','30m','1h' to minutes.
    Used to compute approximate number of bars for lookback.
    """
    s = str(interval).strip().lower()
    if s.endswith("m"):
        return int(s[:-1])
    if s.endswith("h"):
        return int(s[:-1]) * 60
    if s.endswith("d"):
        return int(s[:-1]) * 60 * 24
    return None

def _parse_lookback_days(lookback: str) -> int:
    """
    Convert yfinance-style period (e.g., '2d','10d','60d') to integer days.
    Defaults to 2 days when unknown.
    """
    try:
        s = str(lookback).strip().lower()
        if s.endswith("d"):
            return max(1, int(s[:-1]))
        if s.endswith("mo"):
            return max(1, int(s[:-2]) * 30)
        if s.endswith("y"):
            return max(1, int(s[:-1]) * 365)
    except Exception:
        pass
    return 2

def _approx_bars_needed(lookback: str, interval: str) -> int:
    """
    Compute approximate number of bars from lookback/interval for MT5 fetch.
    """
    minutes = _mt5_interval_to_minutes(interval) or 5
    days = _parse_lookback_days(lookback)
    total_minutes = days * 24 * 60
    n = max(50, int(total_minutes // minutes))  # ensure at least some bars
    return n

def _mt5_load_recent_bars_fx(symbol: str, lookback: str, interval: str) -> Optional[pd.DataFrame]:
    """
    Ask mt5_api for recent FX candles if supported; otherwise None.
    Expected mt5_api.get_recent_bars signature (flexible):
        get_recent_bars(symbol: str, bars: int=None, lookback_days: int=None, interval: str='5m') -> DataFrame
    The DataFrame should contain at least columns like open/high/low/close (any case).
    """
    if not (_mt5_ok and _mt5_get_recent_bars):
        return None

    mt5_sym = to_mt5_symbol(symbol)
    try:
        bars = _approx_bars_needed(lookback, interval)
        df = None

        # Prefer a bars-based request (most mt5 wrappers support 'count' style)
        try:
            df = _mt5_get_recent_bars(mt5_sym, bars=bars, interval=interval)
        except TypeError:
            # Some wrappers might use lookback_days instead of bars
            df = _mt5_get_recent_bars(mt5_sym, lookback_days=_parse_lookback_days(lookback), interval=interval)

        if df is None or df.empty:
            return None

        # Try to set a DatetimeIndex if there is a 'time' column
        if "time" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            try:
                df = df.copy()
                df.index = pd.to_datetime(df["time"], unit="s", errors="coerce")
            except Exception:
                pass

        # Normalize to OHLC
        df = _normalize_ohlc_columns(df)
        return df
    except Exception as e:
        print(f"[DATA WARN] MT5 bars {symbol}: {e}")
        return None


# ------------------------------ Public API -----------------------------------
def load_recent_bars(symbol: str, lookback: str = "2d", interval: str = "5m") -> Optional[pd.DataFrame]:
    """
    Fetch recent OHLC bars for intraday strategies/scalping.
    - For FX: try MT5 first, fallback to yfinance.
    - For Equities: yfinance.
    Returns a DataFrame with exactly ['Open','High','Low','Close'] or None.
    """
    # 1) FX via MT5 (if available)
    if is_forex(symbol):
        df_mt5 = _mt5_load_recent_bars_fx(symbol, lookback, interval)
        if df_mt5 is not None and not df_mt5.empty:
            return df_mt5

    # 2) Fallback: yfinance
    try:
        yf_sym = to_yf_symbol(symbol)
        df = yf.download(
            yf_sym,
            period=lookback,
            interval=interval,
            prepost=True,
            progress=False,
            auto_adjust=False,
            group_by="column",
        )
        df = _normalize_ohlc_columns(df)
        return df
    except Exception as e:
        print(f"[DATA ERROR] load_recent_bars {symbol}: {e}")
        return None


def get_clean_data(symbol: str, days: int = 90) -> Optional[pd.DataFrame]:
    """
    Download and validate close prices for SMA. Returns DF with ['Close'] or None.
    Retries a few times because yfinance can be flaky.
    (We continue to use yfinance for longer history; MT5 wrappers often focus on intraday.)
    """
    max_retries = 3

    for attempt in range(max_retries):
        try:
            yf_sym = to_yf_symbol(symbol)
            df = yf.download(
                yf_sym,
                period=f"{days}d",
                prepost=True,
                progress=False,
                auto_adjust=False,
                group_by="column",
            )
            if df is None or df.empty:
                raise ValueError("Empty dataframe")

            df = _normalize_ohlc_columns(df)
            if df is None or df.empty:
                raise ValueError("Cannot normalize OHLC")

            close = df[["Close"]].dropna()
            if len(close) < 50:
                raise ValueError("Insufficient data (<50 bars)")

            return close

        except Exception as e:
            print(f"[DATA ERROR] {symbol} attempt {attempt+1}: {e}")
            time.sleep(2)

    return None


def get_last_price(symbol: str) -> Optional[float]:
    """
    Lightweight last price (stocks/FX).
    - FX: try MT5 tick first, fallback to yfinance.
    - Equities: yfinance.
    """
    # 1) FX via MT5 tick
    if is_forex(symbol) and _mt5_ok and callable(_mt5_get_price):
        try:
            px = _mt5_get_price(to_mt5_symbol(symbol))
            if px is not None:
                return float(px)
        except Exception as e:
            print(f"[DATA WARN] MT5 tick {symbol}: {e}")

    # 2) Fallback: yfinance last close
    try:
        yf_sym = to_yf_symbol(symbol)
        df = yf.download(
            yf_sym,
            period="1d",
            interval="1m",
            prepost=True,
            progress=False,
            auto_adjust=False,
            group_by="column",
        )
        df = _normalize_ohlc_columns(df)
        if df is not None and not df.empty and "Close" in df.columns:
            return float(df["Close"].iloc[-1])
    except Exception as e:
        print(f"[DATA ERROR] last price {symbol}: {e}")

    return None
