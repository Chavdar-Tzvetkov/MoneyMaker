# 💰 MoneyMaker Bot

MoneyMaker is an automated trading bot built in **Python** that integrates with **Trading212 API**, **MetaTrader 5**, and market data providers like **yFinance** and **Alpha Vantage**.  
It supports multiple strategies (SMA, Scalping) with automatic switching, live trading, SQL-based trade logging, and AI-enhanced decision support.

---

## 🚀 Features
- 📈 **Multiple strategies** (SMA20/50 crossover, Scalping, hybrid AI logic)
- 🔄 **Automatic strategy switching** based on market conditions (AI meta-controller selects strategy per symbol in real time; no human interaction)
- 💾 **Database-backed trade logging** using MSSQL (via SQLAlchemy/EFCore-style models)
- ⏱ **Scheduler** for timed executions during market hours
- 🧾 **PnL tracking** (Daily profit/loss monitoring)
- 🤖 **Live Trading** mode (Trading212, MT5)
- 🛡 **Configurable stop-loss & take-profit**
- 🔔 **Future roadmap**: Telegram/Slack alerts on trade execution

---

## 📂 Project Structure

MoneyMaker/
│── strategies/ # SMA, Scalping, strategy config
│── utils/ # Scheduler, helpers
│── db/ # Database session, models
│── live_trading.py # Core trading loop
│── main.py # Entry point
│── requirements.txt # Dependencies
│── .env.example # Example environment config
│── README.md # This file


---

## ⚙️ Setup

### 1. Clone the repo
```bash
git clone https://github.com/<YourUsername>/MoneyMakerBot.git
cd MoneyMakerBot


## Create a virtual environment

python -m venv .venv
source .venv/bin/activate   # (Linux/Mac)
.venv\Scripts\activate      # (Windows)


## Install dependencies
pip install -r requirements.txt

##

Configure environment

Copy .env.example → .env and update:

T212_API_KEY=your_api_key
MT5_LOGIN=your_login
MT5_PASSWORD=your_password
MT5_SERVER=BenchMark-Server
DB_CONNECTION_STRING=mssql+pyodbc://username:password@localhost/MoneyMakerDB?driver=ODBC+Driver+17+for+SQL+Server


## Running the Bot


Live trading:

python main.py


Dry-run / simulation mode (if implemented):

python main.py --dry-run

## 🕐 Trading hours and holidays

The bot respects **official trading hours and non-trading days** for both platforms:

- **MT5 (Forex)**: 24/5 (Sunday 22:00 UTC → Friday 22:00 UTC). No trading on configured FX holiday dates (e.g. Christmas, New Year).
- **Trading212 (US equities)**: NYSE/NASDAQ hours 09:30–16:00 US/Eastern, Mon–Fri. No trading on US market holidays (New Year, MLK Day, Presidents’ Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas, etc.). On early-close days (e.g. Christmas Eve), trading is allowed only until 13:00 ET.

Calendar data is in `utils/market_calendar.py`; update `US_EQUITY_CLOSED`, `US_EQUITY_EARLY_CLOSE`, and `FX_CLOSED` annually.

## 📦 Packaging as executable (Windows)

You can build a standalone console executable so you don’t need Python installed on the target machine:

1. In the project root (with venv activated), run:
   ```bat
   build.bat
   ```
2. The output is **`dist\MoneyMaker\`**: it contains `MoneyMaker.exe` and all dependencies.
3. Copy your **`.env`** (and optionally a **`state\`** folder for LinUCB) into **`dist\MoneyMaker\`**.
4. Run from that folder, e.g.:
   ```bat
   cd dist\MoneyMaker
   MoneyMaker.exe --live
   ```
   Or create a shortcut to `MoneyMaker.exe` and add `--live` in the shortcut’s “Target” (optional).

Requires **PyInstaller** (installed automatically by `build.bat`). The exe uses your **`icons\moneymaker_bot_icon.ico`** if present.

## 📊 Database

Trades, positions, and daily PnL are logged in MSSQL.

Check db/models.py for schema.

## ⚠️ Disclaimer

This bot is for educational and experimental purposes only.
Use at your own risk. I am not responsible for financial losses caused by this software.
