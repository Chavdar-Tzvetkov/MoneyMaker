# services/alpha_vantage.py

import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

def get_alpha_sma(symbol: str, interval: str = "daily", time_period: int = 20):
    try:
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=SMA&symbol={symbol}&interval={interval}"
            f"&time_period={time_period}&series_type=close&apikey={API_KEY}"
        )
        response = requests.get(url)
        data = response.json()

        if "Technical Analysis: SMA" not in data:
            raise ValueError(f"SMA data missing for {symbol}")

        df = pd.DataFrame.from_dict(data["Technical Analysis: SMA"], orient="index", dtype=float)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        return df["SMA"]
    except Exception as e:
        print(f"[Alpha ERROR] {symbol} → SMA fetch failed: {e}")
        return None

