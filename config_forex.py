# config_forex.py — FOREX-only knobs (stocks path untouched)
import os
from datetime import time

# Trade only these symbols for now (based on performance analysis)
FOREX_ALLOWED_SYMBOLS = ["EURUSD=X", "GBPUSD=X", "USDCHF=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X", "EURGBP=X"]  # MT5 mapping handled elsewhere

# Temporarily block poor performers
FOREX_BLOCKED_SYMBOLS = []

# Symbols that historically showed many small losses / chop: use a fraction of normal FX risk.
FOREX_REDUCED_RISK_SYMBOLS = [s.strip() for s in os.getenv(
    "FOREX_REDUCED_RISK_SYMBOLS", "USDCHF=X,GBPUSD=X"
).split(",") if s.strip()]
FOREX_REDUCED_RISK_MULT = float(os.getenv("FOREX_REDUCED_RISK_MULT", "0.5"))

# Enforce broker session trading instead of fixed windows
USE_BROKER_SESSIONS = False

# Risk/Reward enforcement
# Reasonable default; override via .env if you want stricter filters.
MIN_RR = 1.1        # min required Reward:Risk at placement (tp_pct/sl_pct)

# Time-based exit if trade not progressing
TIME_STOP_MIN = int(os.getenv("TIME_STOP_MIN", "45"))   # exit stagnant trades sooner
MIN_PROGRESS_R = float(os.getenv("MIN_PROGRESS_R", "0.35"))  # need a bit more progress to avoid time-stop noise

# Concurrency: cap number of simultaneous FX positions (fewer = less correlated blow-ups)
MAX_CONCURRENT_FOREX = int(os.getenv("MAX_CONCURRENT_FOREX", "5"))

# Optional: close all forex positions when broker session ends
FORCE_FLAT_AT_SESSION_END = False
