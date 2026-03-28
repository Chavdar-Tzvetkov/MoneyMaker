# config.py
import os
from dotenv import load_dotenv
load_dotenv()

# ----- User base (location) and per-platform budgets -----
# Base timezone for "today" (PnL day rollover, logs). Bulgaria = Europe/Sofia (EET/EEST).
BASE_TIMEZONE = os.getenv("BASE_TIMEZONE", "Europe/Sofia")

# Optional fixed reference equity per platform (USD). If set, used for risk sizing and circuit breaker
# instead of live API equity. Lets you run one bot with MT5 ~9500 and T212 ~4200 without over-calling APIs.
REFERENCE_EQUITY_MT5 = float(os.getenv("REFERENCE_EQUITY_MT5", "0"))   # 0 = use live MT5 equity
REFERENCE_EQUITY_T212 = float(os.getenv("REFERENCE_EQUITY_T212", "0"))  # 0 = use live T212 equity

# ----- SMA Strategy Tuning (split by asset class) -----
SMA_WINDOWS = {
    "forex":  {"fast": 20, "slow": 50},
    "stocks": {"fast": 21, "slow": 55},   # wider/steadier for equities
}

# delta = (SMA_FAST - SMA_SLOW) / SMA_SLOW
SMA_THRESHOLDS = {
    "forex":  {"buy": 0.0008, "sell": -0.0008, "hold": 0.0002},
    "stocks": {"buy": 0.0045, "sell": -0.0045, "hold": 0.0015},  # 0.45% / 0.15% band
}

# ----- Instruments -----
INSTRUMENTS = [
    "AAPL", "AVGO", "MSFT", "GOOGL", "TSLA", "AMZN", "NVDA", "AMD", "KO", "LVMUY", "RACE", "PLUG", "AIOT"
]

# Keep =X for yfinance; we strip it only when sending to MT5.
FOREX_SYMBOLS = ["EURUSD=X", "USDCHF=X", "GBPUSD=X", "AUDUSD=X", "USDCAD=X", "NZDUSD=X", "EURGBP=X"]  # expanded majors (USDJPY still excluded)

# Global flag (set by main.py)
LIVE_TRADING = False

# ----- Trade management (both asset classes) -----
MAX_POSITIONS_PER_SYMBOL = 1          # no stacking for base entries
REENTRY_COOLDOWN_SEC = int(os.getenv("REENTRY_COOLDOWN_SEC", "120"))       # FX: reduce churn (was 20s)
REENTRY_DELTA_PCT = float(os.getenv("REENTRY_DELTA_PCT", "0.0025"))        # FX: need larger move to re-enter
# Equity-specific (stocks trade less frequently, hold longer)
REENTRY_COOLDOWN_SEC_EQUITY = int(os.getenv("REENTRY_COOLDOWN_SEC_EQUITY", "300"))   # 5 min
REENTRY_DELTA_PCT_EQUITY = float(os.getenv("REENTRY_DELTA_PCT_EQUITY", "0.005"))     # 0.5%
EQUITY_MIN_HOLD_MINUTES = float(os.getenv("EQUITY_MIN_HOLD_MINUTES", "15"))          # no TP/PG/trail close before this (SL still allowed)
EQUITY_SELL_CONFIRM_CYCLES = int(os.getenv("EQUITY_SELL_CONFIRM_CYCLES", "2"))       # require N consecutive SELL signals before closing

# ----- Trailing / Breakeven (FX only in current code) -----
TRAILING_STOP_ENABLED       = True
TRAILING_STOP_DISTANCE_PCT  = 0.0020   # 0.20% trail (a bit looser to fit wider SL)
TRAILING_STEP_PCT           = 0.0007   # update SL when improved by ~0.07%
BREAKEVEN_AFTER_PCT         = 0.0015   # move SL to entry at +0.15%

# ----- Risk management (fractions, not percents) -----
# Broker-side TP/SL for FX only (MT5). Equities use software stops.
# Slightly wider TP vs SL → better R:R when MIN_RR / pretrade filters apply.
TAKE_PROFIT_PERCENT = float(os.getenv("TAKE_PROFIT_PERCENT", "0.0020"))   # +0.20% TP default
STOP_LOSS_PERCENT   = float(os.getenv("STOP_LOSS_PERCENT", "-0.0015"))    # −0.15% SL default

# Account-level risk controls (fractions of current equity)
# These are *targets* used by the live loop to size positions.
# Defaults tuned for capital preservation after large demo drawdowns; override in .env.
FX_RISK_PER_TRADE_FRAC   = float(os.getenv("FX_RISK_PER_TRADE_FRAC", "0.0005"))   # 0.05% equity risk per FX trade
EQ_RISK_PER_TRADE_FRAC   = float(os.getenv("EQ_RISK_PER_TRADE_FRAC", "0.002"))    # 0.2% per equity trade
FX_MAX_DAILY_LOSS_FRAC   = float(os.getenv("FX_MAX_DAILY_LOSS_FRAC", "0.005"))    # 0.5% max daily FX loss → halt
EQ_MAX_DAILY_LOSS_FRAC   = float(os.getenv("EQ_MAX_DAILY_LOSS_FRAC", "0.0075"))   # 0.75% max daily equity loss

# Hard cap on MT5 lot size per order (also enforced in mt5_api). Stops 2+ lot disasters.
MAX_FX_LOTS_PER_ORDER    = float(os.getenv("MAX_FX_LOTS_PER_ORDER", "0.35"))

# ----- Equity software stops & trailing (managed by the bot on T212) -----
EQUITY_STOPS_ENABLED             = True     # master enable for software stops on stocks
EQUITY_TAKE_PROFIT_PERCENT       = float(os.getenv("EQUITY_TAKE_PROFIT_PERCENT", "0.015"))   # +1.5% TP (wider so positions can run)
EQUITY_STOP_LOSS_PERCENT         = -0.0150  # −1.50% SL
EQUITY_TRAILING_ENABLED          = True
EQUITY_TRAILING_DISTANCE_PCT     = 0.0150   # 1.5% trail distance (wider)
EQUITY_TRAILING_STEP_PCT         = 0.0050   # update when improved by 0.5%
EQUITY_BREAKEVEN_AFTER_PCT       = 0.0060   # start trailing after +0.6% in profit

# Default order size:
# - FX (MT5): lots (e.g., 0.2 lot)
# - Stocks (T212): fractional shares (e.g., 0.2 share)
TRADE_QUANTITY = float(os.getenv("TRADE_QUANTITY", "0.05"))  # fallback when risk sizing unavailable (FX)

# ----- AI meta-controller: real-time automated strategy switching (no human interaction) -----
# USE_META_DECIDER=1: LinUCB selects strategy per symbol each bar from market behaviour (SMA, RSI_MR, DONCHIAN, MACD, etc.).
# USE_META_DECIDER=0: single ACTIVE_STRATEGY (SMA or SCALPING) still auto-switched by daily PnL (strategy_config).
AI_META = {
    "USE_META_DECIDER": os.getenv("USE_META_DECIDER", "1") == "1",
    "MIN_UCB_MARGIN": float(os.getenv("AI_MIN_UCB_MARGIN", "0.05")),
    "UCB_FLOOR": float(os.getenv("AI_UCB_FLOOR", "-0.10")),
    "FLIP_COOLDOWN_SEC": int(os.getenv("AI_FLIP_COOLDOWN_SEC", "120")),
    "MAX_ACCEPTABLE_UNCERTAINTY": float(os.getenv("MAX_ACCEPTABLE_UNCERTAINTY", "0.95")),
}

# ----- Regime filter: prefer trend vs range strategies from ADX -----
# When enabled, the meta-controller restricts arms by market regime (trend => trend-following, range => mean-reversion).
REGIME = {
    "ENABLED": os.getenv("REGIME_FILTER_ENABLED", "1") == "1",
    "ADX_PERIOD": int(os.getenv("REGIME_ADX_PERIOD", "14")),
    "ADX_TREND_THRESHOLD": float(os.getenv("REGIME_ADX_TREND_THRESHOLD", "25.0")),
}

# ----- Profit-oriented behaviour (profitability cannot be guaranteed; these bias toward better R:R and learning) -----
PROFIT = {
    # Require at least ~1:1 configured TP/SL ratio before opening by default.
    # Set higher (e.g. 1.5) in .env if you want stricter filters.
    "MIN_RISK_REWARD_RATIO": float(os.getenv("MIN_RISK_REWARD_RATIO", "1.0")),
    # Mildly reward profitable strategies more when learning from PnL
    "REWARD_PROFIT_BIAS": float(os.getenv("REWARD_PROFIT_BIAS", "1.2")),  # 20% bonus for wins by default
}


# ----- Rate limiting (per symbol) -----
RATE_LIMIT = {
    "MAX_TRADES_PER_HOUR": int(os.getenv("MAX_TRADES_PER_HOUR", "8")),           # FX
    "EQUITY_MAX_TRADES_PER_HOUR": int(os.getenv("EQUITY_MAX_TRADES_PER_HOUR", "3")),  # stocks (stricter)
}


# ----- Spike Fade (mean-reversion on outsized 1-bar moves) -----
# When ENABLED and the last bar is a large spike, the bot flips a BUY->SELL or SELL->BUY
# before sending the order. Default: disabled for stability; enable via env if desired.
SPIKE_FADE_ENABLED        = bool(int(os.getenv("SPIKE_FADE_ENABLED", "0")))   # master switch (was True)
SPIKE_FADE_ATR_MULT       = 1.5     # require |last_return| >= ATR% * this
SPIKE_FADE_MIN_RET_PCT    = 0.0030  # AND also >= 0.30% absolute 1-bar return
SPIKE_FADE_COOLDOWN_SEC   = 120     # don't flip again for this symbol within N sec

# ----- Hedging (FX only) -----
# NOTE: live_trading.py currently reads HEDGE_* from ENV, not from this dict.
# If you prefer ENV, set: HEDGE_ENABLED=1, HEDGE_RATIO=0.5, HEDGE_TP_PCT=0.002, HEDGE_SL_PCT=0.005, HEDGE_COOLDOWN_SEC=120
HEDGE = {
    "ENABLED": False,  # live_trading reads HEDGE_* from .env; default off in code
    "RATIO": 0.50,       # hedge 50% of the opposing leg
    "TP_PCT": 0.0020,    # 0.20% TP for hedge (take quick cover profits)
    "SL_PCT": 0.0050,    # 0.50% SL for hedge (wider, it's insurance)
    "COOLDOWN_SEC": 120,
}

# ----- Broker pacing -----
T212_MIN_ORDER_INTERVAL_SEC = 1.2
