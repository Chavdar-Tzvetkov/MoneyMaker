# config.py

# ----- SMA Strategy Tuning (split by asset class) -----
SMA_WINDOWS = {
    "forex":  {"fast": 20, "slow": 50},
    "stocks": {"fast": 20, "slow": 50},
}

# delta = (SMA_FAST - SMA_SLOW) / SMA_SLOW
SMA_THRESHOLDS = {
    "forex":  {"buy": 0.0008, "sell": -0.0008, "hold": 0.0002},   # ±0.08%, neutral ±0.02%
    "stocks": {"buy": 0.0020, "sell": -0.0020, "hold": 0.0005},   # ±0.20%, neutral ±0.05%
}

# ----- Instruments -----
INSTRUMENTS = [
    "AAPL", "AVGO", "MSFT", "GOOGL", "TSLA", "AMZN", "NVDA", "AMD", "KO", "LVMUY", "RACE", "PLUG", "AIOT"
]

# Keep =X for yfinance; we strip it only when sending to MT5.
FOREX_SYMBOLS = ["EURUSD=X", "USDCHF=X", "GBPUSD=X"]  # (USDJPY removed as requested)

# Global flag (set by main.py)
LIVE_TRADING = False

# ----- Trade management (both asset classes) -----
MAX_POSITIONS_PER_SYMBOL = 1          # no stacking for base entries
REENTRY_COOLDOWN_SEC=20     # was higher — allows quicker re-entries
REENTRY_DELTA_PCT=0.0015    # was larger — smaller price drift required to re-enter

# ----- Trailing / Breakeven (FX only in current code) -----
TRAILING_STOP_ENABLED       = True
TRAILING_STOP_DISTANCE_PCT  = 0.0020   # 0.20% trail (a bit looser to fit wider SL)
TRAILING_STEP_PCT           = 0.0007   # update SL when improved by ~0.07%
BREAKEVEN_AFTER_PCT         = 0.0015   # move SL to entry at +0.15%

# ----- Risk management (fractions, not percents) -----
# Used at MT5 FX entries. T212 equities don’t use these TP/SL at broker level.
TAKE_PROFIT_PERCENT = 0.0008    # +0.08% TP (lowered)
STOP_LOSS_PERCENT   = -0.0015   # −0.15% SL (extended)

# ----- Equity software stops & trailing (managed by the bot on T212) -----
EQUITY_STOPS_ENABLED             = True     # master enable for software stops on stocks
EQUITY_TAKE_PROFIT_PERCENT       = 0.0060   # +0.60% TP
EQUITY_STOP_LOSS_PERCENT         = -0.0150  # −1.50% SL
EQUITY_TRAILING_ENABLED          = True
EQUITY_TRAILING_DISTANCE_PCT     = 0.0100   # 1.0% trail distance
EQUITY_TRAILING_STEP_PCT         = 0.0030   # update when improved by ~0.3%
EQUITY_BREAKEVEN_AFTER_PCT       = 0.0040   # start trailing after +0.4% in profit

# Default order size:
# - FX (MT5): lots (e.g., 0.2 lot)
# - Stocks (T212): fractional shares (e.g., 0.2 share)
TRADE_QUANTITY = 0.2

# ----- AI meta-controller defaults (mirrors the env toggles we added) -----
AI_META = {
    "USE_META_DECIDER": True,
    "MIN_UCB_MARGIN": 0.05,
    "UCB_FLOOR": -0.10,
    "FLIP_COOLDOWN_SEC": 120,
    "MAX_ACCEPTABLE_UNCERTAINTY": 0.95,
}

# ----- Rate limiting (per symbol) -----
RATE_LIMIT = {
    "MAX_TRADES_PER_HOUR": 8,
}

# ----- Spike Fade (mean-reversion on outsized 1-bar moves) -----
# When ENABLED and the last bar is a large spike, the bot flips a BUY->SELL or SELL->BUY
# before sending the order. Safe defaults: disabled.
SPIKE_FADE_ENABLED        = True   # master switch
SPIKE_FADE_ATR_MULT       = 1.5     # require |last_return| >= ATR% * this
SPIKE_FADE_MIN_RET_PCT    = 0.0030  # AND also >= 0.30% absolute 1-bar return
SPIKE_FADE_COOLDOWN_SEC   = 120     # don't flip again for this symbol within N sec

# ----- Hedging (FX only) -----
# NOTE: live_trading.py currently reads HEDGE_* from ENV, not from this dict.
# If you prefer ENV, set: HEDGE_ENABLED=1, HEDGE_RATIO=0.5, HEDGE_TP_PCT=0.002, HEDGE_SL_PCT=0.005, HEDGE_COOLDOWN_SEC=120
HEDGE = {
    "ENABLED": True,
    "RATIO": 0.50,       # hedge 50% of the opposing leg
    "TP_PCT": 0.0020,    # 0.20% TP for hedge (take quick cover profits)
    "SL_PCT": 0.0050,    # 0.50% SL for hedge (wider, it's insurance)
    "COOLDOWN_SEC": 120,
}

# ----- Broker pacing -----
T212_MIN_ORDER_INTERVAL_SEC = 1.2
