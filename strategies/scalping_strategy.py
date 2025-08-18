# strategies/scalping_strategy.py
import warnings
import pandas as pd

from utils.market_data import load_recent_bars

warnings.simplefilter("ignore", category=FutureWarning)

def analyze_scalping(symbol):
    print(f"[SCALPING] Analyzing {symbol}...")

    try:
        df = load_recent_bars(symbol, lookback="2d", interval="5m")
        if df is None or df.empty or 'Close' not in df.columns:
            print(f"[SCALPING] No data for {symbol}")
            return None

        df = df.copy()
        df['returns'] = df['Close'].pct_change()
        avg_return = float(df['returns'].mean())

        if avg_return > 0.001:
            print(f"[SCALPING SIGNAL] BUY signal for {symbol}")
            return "BUY"
        elif avg_return < -0.001:
            print(f"[SCALPING SIGNAL] SELL signal for {symbol}")
            return "SELL"
        else:
            print(f"[SCALPING SIGNAL] HOLD for {symbol}")
            return "HOLD"

    except Exception as e:
        print(f"[ERROR] Scalping failed for {symbol}: {e}")
        return None
