# config_forex.py — FOREX-only knobs (stocks path untouched)
from datetime import time

# Trade only these symbols for now (based on performance analysis)
FOREX_ALLOWED_SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDCHF=X"]  # MT5 mapping handled elsewhere

# Temporarily block poor performers
FOREX_BLOCKED_SYMBOLS = []

# Enforce broker session trading instead of fixed windows
USE_BROKER_SESSIONS = False

# Risk/Reward enforcement
# Reasonable default; override via .env if you want stricter filters.
MIN_RR = 1.1        # min required Reward:Risk at placement (tp_pct/sl_pct)

# Time-based exit if trade not progressing
TIME_STOP_MIN = 60   # minutes (exit sooner if trade stalls)
MIN_PROGRESS_R = 0.3  # if < 0.3R progress after TIME_STOP_MIN → exit

# Concurrency: cap number of simultaneous FX positions
MAX_CONCURRENT_FOREX = 4   # was 10; reduces over-exposure during choppy periods

# Optional: close all forex positions when broker session ends
FORCE_FLAT_AT_SESSION_END = False
