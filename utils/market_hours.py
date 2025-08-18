# utils/market_hours.py
from datetime import datetime, time
import pytz

def is_market_open(symbol: str) -> bool:
    """
    - Crypto: 24/7
    - Forex: 24/5 using UTC (Sun 22:00 UTC → Fri 22:00 UTC)
    - Stocks: US market hours 09:30–16:00 US/Eastern, Mon–Fri
    """
    symbol = (symbol or "").upper()

    # Crypto: always on
    if symbol in ("BTC-USD", "ETH-USD"):
        return True

    # Clocks
    now_utc = datetime.now(pytz.UTC)
    weekday_utc = now_utc.weekday()  # Mon=0 ... Sun=6

    # Forex (treat '=X' or 6-letter pairs as FX)
    if symbol.endswith("=X") or (len(symbol) == 6 and symbol.isalpha()):
        # Open Mon–Thu all day UTC
        if 0 <= weekday_utc <= 3:
            return True
        # Friday: typically open until ~22:00 UTC
        if weekday_utc == 4:
            return now_utc.time() <= time(22, 0)
        # Sunday: typically opens ~22:00 UTC
        if weekday_utc == 6:
            return now_utc.time() >= time(22, 0)
        return False

    # US equities
    tz_est = pytz.timezone("America/New_York")
    now_est = datetime.now(tz_est)
    if now_est.weekday() >= 5:
        return False
    return time(9, 30) <= now_est.time() <= time(16, 0)
