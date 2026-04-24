@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [WARN] venv not found. Run setup_once.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate"

REM Optional: update pip deps when requirements.txt changed
if exist ".venv\req.sha256" (
  for /f "skip=1 tokens=* delims=" %%H in ('
    certutil -hashfile requirements.txt SHA256 ^| findstr /R "^[0-9A-F]"
  ') do (
    set "NEWHASH=%%H"
    goto :compare
  )
  :compare
  set /p OLDHASH=<".venv\req.sha256"
  if /I "%NEWHASH%" NEQ "%OLDHASH%" (
    echo [DEPS] requirements.txt changed - updating...
    python -m pip install -r requirements.txt
    > ".venv\req.sha256" echo %NEWHASH%
  )
)

REM Live mode: AI + LLM. Override in .env or here for classic (USE_META_DECIDER=0, LLM_ENABLED=0)
set "USE_META_DECIDER=1"
set "LLM_ENABLED=0"

REM FX execution tuning (reduce over-filtering that causes zero MT5 trades)
REM Keep safety checks enabled, but relax thresholds so valid setups can pass.
set "MAX_ACCEPTABLE_UNCERTAINTY=1.00"
set "PRECONFIRM_ATR_MIN_FX=0.00012"
set "PRECONFIRM_GRACE_BPS_FX=80"
REM FX decisive nudging increases chop entries; keep it OFF by default.
set "DECISIVE_MODE_FX=0"

REM Autonomous live-safe profile (cross-account)
set "CIRCUIT_BREAKER_ENABLED=1"
set "CIRCUIT_BREAKER_HALT_MINUTES=90"
set "CLEAR_HALT_ON_START=1"
set "FX_MAX_DAILY_LOSS_FRAC=0.10"
set "MAX_CONCURRENT_FOREX=3"
set "MAX_TRADES_PER_HOUR=4"
set "EQUITY_MAX_TRADES_PER_HOUR=2"
REM Reduce per-trade FX risk to avoid repeatedly hitting max lot cap.
set "FX_RISK_PER_TRADE_FRAC=0.0005"
set "EQ_RISK_PER_TRADE_FRAC=0.0015"
set "PG_REQUIRE_NOT_BUY=1"
set "SUPERVISOR_ENABLED=1"
set "SUPERVISOR_TUNE_EVERY_CYCLES=15"

REM Optional: set in .env to avoid 429 and fix circuit breaker to your budgets (e.g. REFERENCE_EQUITY_MT5=9500 REFERENCE_EQUITY_T212=4200)
REM Optional: clear circuit breaker on start once (CLEAR_HALT_ON_START=1) or relax threshold (CIRCUIT_BREAKER_HALT_THRESHOLD=-0.35)

echo [START] Running MoneyMaker (LIVE)...
python Main.py --live
pause
