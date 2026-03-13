@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [WARN] venv not found. Run setup_once.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate"

set "USE_META_DECIDER=0"
set "LLM_ENABLED=0"

REM Optional: equity behaviour (or set in .env)
REM set "EQUITY_MIN_HOLD_MINUTES=15"
REM set "EQUITY_SELL_CONFIRM_CYCLES=2"
REM set "EQUITY_MAX_TRADES_PER_HOUR=3"

echo [START] Running MoneyMaker (LIVE classic)...
python Main.py --live
pause