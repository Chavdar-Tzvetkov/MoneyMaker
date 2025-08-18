# 💰 MoneyMaker Bot

MoneyMaker is an automated trading bot built in **Python** that integrates with **Trading212 API**, **MetaTrader 5**, and market data providers like **yFinance** and **Alpha Vantage**.  
It supports multiple strategies (SMA, Scalping) with automatic switching, live trading, SQL-based trade logging, and AI-enhanced decision support.

---

## 🚀 Features
- 📈 **Multiple strategies** (SMA20/50 crossover, Scalping, hybrid AI logic)
- 🔄 **Automatic strategy switching** based on market conditions
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

## 📊 Database

Trades, positions, and daily PnL are logged in MSSQL.

Check db/models.py for schema.

## ⚠️ Disclaimer

This bot is for educational and experimental purposes only.
Use at your own risk. I am not responsible for financial losses caused by this software.
