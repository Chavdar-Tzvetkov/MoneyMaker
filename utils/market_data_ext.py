
# utils/market_data_ext.py
import yfinance as yf
import pandas as pd

def load_recent_bars(symbol: str, lookback="2d", interval="5m") -> pd.DataFrame:
    try:
        df = yf.download(symbol, period=lookback, interval=interval, progress=False)
        return df if df is not None and not df.empty else None
    except Exception:
        return None
