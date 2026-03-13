"""
AI-driven runner that chooses between SMA / Scalping / RSI_MR / DONCHIAN / SUPER / MACD / HOLD
via a LinUCB meta-controller. It keeps your existing risk limits; only selects
a strategy + parameters per symbol on the fly.
"""

from __future__ import annotations
import time
import traceback
from typing import Dict, Callable, Any, Optional

from ai.meta_controller import MetaController
from utils.market_data import load_recent_bars
from strategies import sma_strategy as sma
from strategies import scalping_strategy as scalp

# NEW strategies
from strategies.rsi_reversion import analyze_rsi
from strategies.donchian_breakout import analyze_donchian_breakout
from strategies.supertrend_trend import analyze_supertrend
from strategies.macd_trend import analyze_macd


# ---- Strategy adapters -------------------------------------------------------

def run_sma_once(symbol: str, params: dict) -> Optional[str]:
    """
    Calls your SMA analyzer. Expected returns: "BUY" | "SELL" | "HOLD" | None
    """
    if hasattr(sma, "analyze_sma"):
        try:
            return sma.analyze_sma(
                symbol,
                fast=params.get("fast"),
                slow=params.get("slow"),
                hold_band=params.get("hold_band", 0.0),
                tp=params.get("tp"),
                sl=params.get("sl"),
                trail=params.get("trail"),
            )
        except TypeError:
            return sma.analyze_sma(symbol)
        except Exception as e:
            print(f"[SMA ERROR] {symbol}: {e}")
            return None
    return None


def run_scalp_once(symbol: str, params: dict) -> Optional[str]:
    """
    Calls your scalping analyzer.
    """
    if hasattr(scalp, "analyze_scalping"):
        try:
            return scalp.analyze_scalping(symbol)
        except Exception as e:
            print(f"[SCALP ERROR] {symbol}: {e}")
            return None
    return None


def run_rsi_once(symbol: str, params: dict) -> Optional[str]:
    try:
        return analyze_rsi(
            symbol,
            lookback=params.get("lookback", "10d"),
            interval=params.get("interval", "15m"),
            rsi_len=int(params.get("rsi_len", 14)),
            overbought=float(params.get("overbought", 70.0)),
            oversold=float(params.get("oversold", 30.0)),
            trend_sma=int(params.get("trend_sma", 50)),
            buffer_bps=float(params.get("buffer_bps", 3.0)),
        )
    except Exception as e:
        print(f"[RSI ERROR] {symbol}: {e}")
        return None


def run_donchian_once(symbol: str, params: dict) -> Optional[str]:
    try:
        return analyze_donchian_breakout(
            symbol,
            lookback=params.get("lookback", "20d"),
            interval=params.get("interval", "30m"),
            ch_len=int(params.get("ch_len", 20)),
            atr_len=int(params.get("atr_len", 14)),
            min_range_bps=float(params.get("min_range_bps", 12.0)),
            buffer_atr=float(params.get("buffer_atr", 0.25)),
        )
    except Exception as e:
        print(f"[DONCHIAN ERROR] {symbol}: {e}")
        return None


def run_supertrend_once(symbol: str, params: dict) -> Optional[str]:
    try:
        return analyze_supertrend(
            symbol,
            lookback=params.get("lookback", "20d"),
            interval=params.get("interval", "15m"),
            atr_len=int(params.get("atr_len", 10)),
            mult=float(params.get("mult", 3.0)),
        )
    except Exception as e:
        print(f"[SUPER ERROR] {symbol}: {e}")
        return None


def run_macd_once(symbol: str, params: dict) -> Optional[str]:
    try:
        return analyze_macd(
            symbol,
            lookback=params.get("lookback", "20d"),
            interval=params.get("interval", "15m"),
            fast=int(params.get("fast", 12)),
            slow=int(params.get("slow", 26)),
            signal=int(params.get("signal", 9)),
            slope_len=int(params.get("slope_len", 50)),
        )
    except Exception as e:
        print(f"[MACD ERROR] {symbol}: {e}")
        return None


# Map meta decision.strategy -> runner
RUNNERS: Dict[str, Callable[[str, Dict[str, Any]], Optional[str]]] = {
    "SMA":       run_sma_once,

    # Existing key the AI will emit
    "SCALP":     run_scalp_once,

    # (Nice-to-have) support classic name too
    "SCALPING":  run_scalp_once,

    "RSI_MR":    run_rsi_once,
    "DONCHIAN":  run_donchian_once,
    "SUPER":     run_supertrend_once,
    "MACD":      run_macd_once,
    "HOLD":      lambda _s, _p: "HOLD",
}


# ---- Lightweight ATR-based reward shaping -----------------------------------

def _atr_percent(df, n: int = 14) -> float:
    """
    Return ATR as a fraction of price (ATR / last_close). Falls back to close stdev if needed.
    """
    try:
        h = df["High"].astype(float)
        l = df["Low"].astype(float)
        c = df["Close"].astype(float)
        prev_c = c.shift(1)
        tr = (h - l).abs().combine((h - prev_c).abs(), max).combine((l - prev_c).abs(), max)
        atr = tr.rolling(n).mean().iloc[-1]
        last_c = float(c.iloc[-1])
        if last_c > 0 and atr is not None:
            return float(atr) / last_c
    except Exception:
        pass
    # fallback: percent stdev of close
    try:
        c = df["Close"].astype(float)
        if len(c) > 5 and float(c.iloc[-1]) != 0.0:
            return float(c.pct_change().rolling(20).std().iloc[-1] or 0.0)
    except Exception:
        pass
    return 0.0


def _estimate_reward(df, outcome: Optional[str]) -> float:
    """
    Proxy reward using next-bar move vs ATR%:
      reward = sign(outcome) * (ret_last_bar / ATR%)
    Clipped to [-1, 1]. HOLD slightly penalized when there's a move.
    """
    if outcome is None:
        return -0.05

    try:
        c = df["Close"].astype(float)
        if len(c) < 3:
            return 0.0
        ret = (float(c.iloc[-1]) - float(c.iloc[-2])) / max(float(c.iloc[-2]), 1e-12)
        atrp = _atr_percent(df)
        scale = atrp if atrp > 1e-6 else 1.0  # avoid div-by-zero
        base = ret / scale

        if outcome == "BUY":
            r = base
        elif outcome == "SELL":
            r = -base
        elif outcome == "HOLD":
            r = -abs(base) * 0.1
        else:
            r = 0.0

        # soft clip
        if r > 1.0:
            r = 1.0
        if r < -1.0:
            r = -1.0
        return float(r)
    except Exception:
        return 0.0


# ---- Main loop ---------------------------------------------------------------

def main(symbols, loop_delay: int = 5):
    """
    symbols: list[str] (tickers and/or forex symbols like 'EURUSD=X')
    loop_delay: seconds between top-level passes over the symbol list
    """
    meta = MetaController(
        alpha=0.6, d=11,
        min_ucb_margin=float(os.getenv("AI_MIN_UCB_MARGIN", "0.00")),
        ucb_floor=float(os.getenv("AI_UCB_FLOOR", "-1.00")),
        flip_cooldown_sec=int(os.getenv("AI_FLIP_COOLDOWN_SEC", "60")),
    )

    print("[AI] MetaController initialized")

    while True:
        try:
            for sym in symbols:
                df = load_recent_bars(sym, lookback="2d", interval="5m")
                if df is None or df.empty:
                    print(f"[AI] No data for {sym}, skipping")
                    continue

                # Guard: ensure required OHLC columns exist
                required = {"Open", "High", "Low", "Close"}
                cols = set(df.columns)
                missing = required - cols
                if missing:
                    print(f"[AI] Missing columns for {sym}: {missing}. Skipping.")
                    continue

                # Basic sanitization
                df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
                if df.empty:
                    print(f"[AI] Empty after dropna for {sym}. Skipping.")
                    continue

                # Decide which strategy/profile to use
                decision = meta.decide(df, symbol=sym)
                print(f"[AI] {sym} -> action={decision.action} strategy={decision.strategy} params={decision.params}")

                # Run chosen strategy once
                runner = RUNNERS.get(decision.strategy, RUNNERS["HOLD"])
                outcome = runner(sym, decision.params) if runner else "HOLD"

                # Reward: ATR-normalized last-bar move aligned with outcome
                reward = _estimate_reward(df, outcome)

                # Learn
                meta.learn(df, decision.action, reward, symbol=sym)

                # brief pause between symbols to avoid hammering data sources
                time.sleep(0.2)

            # outer-loop delay
            time.sleep(loop_delay)

        except KeyboardInterrupt:
            print("[AI] Stopped by user")
            break
        except Exception as e:
            print("[AI][FATAL]", e)
            traceback.print_exc()
            time.sleep(3)


if __name__ == "__main__":
    # Fallback for ad-hoc runs
    try:
        from config import INSTRUMENTS, FOREX_SYMBOLS
        symbols = list(INSTRUMENTS) + list(FOREX_SYMBOLS)
    except Exception:
        symbols = ["AAPL", "MSFT", "EURUSD=X"]

    main(symbols, loop_delay=5)
