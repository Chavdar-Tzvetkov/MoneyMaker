# utils/symbols.py
from __future__ import annotations

"""
Symbol helpers:

- Forex detection works for both Yahoo-style ("EURUSD=X") and plain pairs ("EURUSD").
- normalize_symbol(): removes '=X' and uppercases (good for DB keys).
- to_yf_symbol(): returns Yahoo-finance friendly symbol (adds '=X' for FX).
- to_mt5_symbol(): returns MT5-friendly symbol (6-letter FX like 'EURUSD').

Only call to_mt5_symbol() when is_forex(symbol) is True.
"""

def _clean(s: str) -> str:
    return (s or "").strip().upper()


def is_forex(symbol: str) -> bool:
    """
    True for:
      - 'EURUSD=X' (Yahoo style)
      - 'eurusd' / 'EURUSD' (plain 6 letters)
    """
    s = _clean(symbol)
    if s.endswith("=X"):
        return True
    # allow 6 alpha chars (e.g., EURUSD, USDJPY)
    if len(s) == 6 and s.isalpha():
        return True
    return False


def is_crypto(symbol: str) -> bool:
    s = _clean(symbol)
    return s.endswith("-USD") or s.endswith("USDT")


def is_stock(symbol: str) -> bool:
    # crude but effective: not FX, not crypto
    return not is_forex(symbol) and not is_crypto(symbol)


def normalize_symbol(symbol: str) -> str:
    """
    Canonical DB/display key:
      - 'EURUSD=X' -> 'EURUSD'
      - 'eurusd'   -> 'EURUSD'
      - 'AAPL'     -> 'AAPL'
    """
    s = _clean(symbol)
    if s.endswith("=X"):
        s = s[:-2]
    return s


def to_yf_symbol(symbol: str) -> str:
    """
    Convert to yfinance-friendly symbol.
      - 'EURUSD'   -> 'EURUSD=X'
      - 'EURUSD=X' -> 'EURUSD=X'
      - 'AAPL'     -> 'AAPL'
    """
    s = _clean(symbol)
    if s.endswith("=X"):
        return s
    if len(s) == 6 and s.isalpha():
        return s + "=X"
    return s


def to_mt5_symbol(symbol: str) -> str:
    """
    Convert to MT5/MetaTrader-friendly FX symbol (letters only, 6 chars).
      - 'EURUSD=X'     -> 'EURUSD'
      - 'eurusd'       -> 'EURUSD'
      - 'EUR/USD'      -> 'EURUSD'
      - 'USDJPY.m'     -> 'USDJPY'   (strips common suffixes)
      - 'GBPUSD_pro'   -> 'GBPUSD'   (letters-only fallback)

    NOTE: Only use this for FX symbols (guard with is_forex()).
    """
    s = _clean(symbol)

    # Strip Yahoo suffix
    if s.endswith("=X"):
        s = s[:-2]

    # Remove common separators/broker decorations
    # (keeps only letters; safe for most MT5 FX instruments)
    letters_only = "".join(ch for ch in s if ch.isalpha())

    # If we ended with exactly 6 letters, that’s a standard FX pair
    if len(letters_only) == 6:
        return letters_only

    # Fallback: if original looked like FX (first 6 letters form a pair), use that.
    if len(letters_only) > 6:
        guess = letters_only[:6]
        if len(guess) == 6 and guess.isalpha():
            return guess

    # Last resort: return normalized symbol (shouldn’t happen if is_forex is True)
    return normalize_symbol(symbol)
