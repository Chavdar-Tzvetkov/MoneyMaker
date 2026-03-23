# 💰 MoneyMaker Bot

MoneyMaker is an automated trading bot built in **Python** that integrates with **Trading212 API**, **MetaTrader 5**, and market data providers like **yFinance** and **Alpha Vantage**.  
It supports multiple strategies (SMA, Scalping, RSI, Donchian, MACD, Supertrend, Bollinger, etc.) with **AI-driven strategy selection per symbol**, live trading, SQL-based trade logging, and optional LLM decision support.

---

## 🚀 Features

- 📈 **Multiple strategies** – SMA crossover, Scalping, RSI mean-reversion, Donchian breakout, MACD, Supertrend, Bollinger, EMA cross, Breakout, Z-Score mean-reversion
- 🤖 **AI meta-controller (LinUCB)** – Selects which strategy to run per symbol in real time from market features; **learns from realized PnL** when positions close
- 📊 **Platform-specific strategy sets** – FX (MT5) uses short-term/mean-reversion strategies; equities (T212) use trend/swing strategies
- 🌡 **Regime filter** – ADX-based trend vs range detection; prefers trend-following in trends and mean-reversion in ranges
- 💰 **Profit-oriented options** – Min risk:reward gate, reward bias for winning trades (profitability not guaranteed)
- 💾 **Database-backed trade logging** – MSSQL (SQLAlchemy); trades, positions, daily PnL (split FX/equity)
- ⏱ **Scheduler** – Timed executions during market hours
- 🤖 **Live trading** – Trading212 (equities) and MT5 (forex) in one process; **separate accounts**, per-platform circuit breaker and position sizing
- 🛡 **Configurable TP/SL, trailing stops, profit guard**
- 🔔 **Future**: Telegram/Slack alerts

---

## 📂 Project structure

```
MoneyMaker/
├── Main.py                 # Entry point (scheduler, --live)
├── live_trading.py          # Core trading loop (AI + strategies + MT5/T212)
├── config.py               # Instruments, risk, AI/regime/profit settings
├── config_forex.py         # FX-specific (allowlist, sessions, etc.)
├── strategies/             # SMA, Scalping, RSI, Donchian, MACD, Supertrend, etc.
│   └── strategy_config.py   # Active strategy fallback, circuit breaker, daily PnL
├── ai/                     # AI decision layer
│   ├── meta_controller.py  # LinUCB meta-controller (strategy choice per symbol)
│   ├── policy_linucb.py    # LinUCB bandit
│   ├── features.py         # OHLC → feature vector
│   ├── regime.py           # ADX trend/range detection
│   ├── llm_decider.py      # Optional OpenAI tie-break/veto
│   └── README_AI_LEARNING.md  # Detailed AI & learning doc
├── utils/                  # Market data, hours, calendar, symbols
├── db/                     # MSSQL session, models
├── services/               # PnL, position, Alpha Vantage
├── state/linucb/           # Persisted LinUCB state per symbol (created at runtime)
├── requirements.txt
└── .env                    # API keys, DB, env overrides (copy from .env.example if present)
```

---

## ⚙️ Setup

### 1. Clone and install

```bash
git clone https://github.com/<YourUsername>/MoneyMaker.git
cd MoneyMaker

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

Create `.env` (or copy from `.env.example` if available) and set at least:

| Variable | Description |
|----------|-------------|
| `TRADING212_API_KEY` | Trading212 API key |
| `MT5_LOGIN` | MetaTrader 5 account number |
| `MT5_PASSWORD` | MT5 password |
| `MT5_SERVER` | MT5 server (e.g. BenchMark-Server) |
| `MSSQL_CONN_STR` or `DB_CONNECTION_STRING` | MSSQL connection string |

**Two accounts in one bot:** The bot trades **MT5 (forex)** and **Trading212 (equities)** in one process. Funds are **not** combined: position sizing uses **MT5 equity** for FX and **T212 equity** for equities. The circuit breaker is **per account**. Optional: set `REFERENCE_EQUITY_MT5=9500` and `REFERENCE_EQUITY_T212=4200` to pin budgets. For per-account PnL you need `pnl_fx` and `pnl_equity` on `DailyPnL`; if missing:  
`ALTER TABLE DailyPnL ADD pnl_fx FLOAT DEFAULT 0; ALTER TABLE DailyPnL ADD pnl_equity FLOAT DEFAULT 0;`

**Base timezone:** Set `BASE_TIMEZONE=Europe/Sofia` so “today” for daily PnL and circuit-breaker rollover follows your local day.

### 3. Run the bot

- **Live trading:** `python Main.py` (or `python Main.py --live` depending on your entry point)
- **Batch:** Use `start_bot.bat` on Windows to set env (e.g. `USE_META_DECIDER=1`, `LLM_ENABLED=1`) and run the bot.

---

## 🤖 AI and strategies

- **Meta-controller:** LinUCB chooses *which strategy* to run per symbol each bar (SMA, RSI_MR, Donchian, MACD, Supertrend, Bollinger, etc.). It learns from **realized PnL** when positions close (`_feed_close_reward` in `live_trading.py`). State is stored per symbol under `state/linucb/<SYMBOL>.npz`.
- **Platform-specific arms:** FX symbols only use FX-suited strategies (e.g. Scalping, RSI_MR, RangeMR, ZScore_MR); equity symbols use equity-suited ones (e.g. SMA, MACD, Supertrend, Breakout). See `ai/meta_controller.py` (`ACTION_NAMES_FX`, `ACTION_NAMES_EQUITY`).
- **Regime filter:** When `REGIME_FILTER_ENABLED=1` (default), ADX classifies each symbol as **trend** or **range**. The meta-controller then restricts to trend-following arms in trend and mean-reversion arms in range. Env: `REGIME_ADX_PERIOD`, `REGIME_ADX_TREND_THRESHOLD`.
- **Profit-oriented:** `MIN_RISK_REWARD_RATIO` blocks opening trades when configured TP/SL ratio is below the value; `REWARD_PROFIT_BIAS` scales up positive rewards so the bandit leans toward profitable arms. **Profitability is not guaranteed.**
- **LLM (optional):** Set `LLM_ENABLED=1` and `OPENAI_API_KEY`. The LLM can tie-break, veto, or act as primary advisor. See `ai/llm_decider.py`.

For more detail (features, reward flow, tuning), see **`ai/README_AI_LEARNING.md`**.

---

## 📋 Environment variables (main ones)

**Broker & DB**  
`TRADING212_API_KEY`, `BASE_URL` (T212), `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MSSQL_CONN_STR` (or `DB_CONNECTION_STRING`)

**Location & budgets**  
`BASE_TIMEZONE`, `REFERENCE_EQUITY_MT5`, `REFERENCE_EQUITY_T212`

**AI meta-controller**  
`USE_META_DECIDER` (1/0), `AI_MIN_UCB_MARGIN`, `AI_UCB_FLOOR`, `AI_FLIP_COOLDOWN_SEC`, `MAX_ACCEPTABLE_UNCERTAINTY`, `AI_BAR_INTERVAL`

**Regime**  
`REGIME_FILTER_ENABLED`, `REGIME_ADX_PERIOD`, `REGIME_ADX_TREND_THRESHOLD`

**Profit-oriented**  
`MIN_RISK_REWARD_RATIO`, `REWARD_PROFIT_BIAS`

**Risk / rate**  
`FX_RISK_PER_TRADE_FRAC`, `EQ_RISK_PER_TRADE_FRAC`, `FX_MAX_DAILY_LOSS_FRAC`, `EQ_MAX_DAILY_LOSS_FRAC`, `MAX_TRADES_PER_HOUR`, `EQUITY_MAX_TRADES_PER_HOUR`

**Capital preservation (FX drawdown protection)**  
Defaults aim to limit wipe-outs: **`MAX_FX_LOTS_PER_ORDER`** (hard cap per MT5 order, e.g. `0.35`), **`MAX_CONCURRENT_FOREX`** (max open FX positions), **`FOREX_REDUCED_RISK_SYMBOLS`** / **`FOREX_REDUCED_RISK_MULT`** (half-size on choppy pairs like `USDCHF=X`), **`REENTRY_COOLDOWN_SEC`** / **`REENTRY_DELTA_PCT`**, **`TIME_STOP_MIN`**. Set **`HEDGE_ENABLED=0`** in `.env` if hedging burns margin (recommended after large losses).

**Equity**  
`EQUITY_TAKE_PROFIT_PERCENT`, `EQUITY_STOP_LOSS_PERCENT`, `REENTRY_COOLDOWN_SEC_EQUITY`, `EQUITY_MIN_HOLD_MINUTES`, `EQUITY_SELL_CONFIRM_CYCLES`

**LLM**  
`LLM_ENABLED`, `LLM_MODE`, `LLM_MIN_CONF`, `LLM_MODEL`, `OPENAI_API_KEY`

**Pre-trade / hedging / profit guard**  
`PRECONFIRM_ENABLED`, `PRECONFIRM_ATR_MIN`, `HEDGE_ENABLED`, `PG_ENABLED`, etc.

---

## 🕐 Trading hours and holidays

- **MT5 (Forex):** 24/5 (Sunday 22:00 UTC → Friday 22:00 UTC). No trading on configured FX holiday dates.
- **Trading212 (US equities):** NYSE/NASDAQ 09:30–16:00 US/Eastern, Mon–Fri. No trading on US market holidays; early-close days (e.g. Christmas Eve) until 13:00 ET.

Calendar: `utils/market_calendar.py` (`US_EQUITY_CLOSED`, `US_EQUITY_EARLY_CLOSE`, `FX_CLOSED`). Update annually.

---

## 📦 Packaging (Windows)

1. In project root with venv activated: `build.bat`
2. Output: `dist\MoneyMaker\` (includes `MoneyMaker.exe` and dependencies)
3. Copy `.env` and optionally `state\` (LinUCB state) into `dist\MoneyMaker\`
4. Run: `cd dist\MoneyMaker` then `MoneyMaker.exe --live` (or add `--live` to shortcut Target)

Requires PyInstaller. Icon: `icons\moneymaker_bot_icon.ico` if present.

---

## 📊 Database

Trades, positions, and daily PnL are logged in MSSQL. Schema: `db/models.py`. Daily PnL supports `pnl_fx` and `pnl_equity` for per-platform totals.

---

## ⚠️ Disclaimer

This bot is for **educational and experimental purposes only**. Use at your own risk. I am not responsible for financial losses caused by this software. **Trading involves risk of loss; profitability cannot be guaranteed.**
