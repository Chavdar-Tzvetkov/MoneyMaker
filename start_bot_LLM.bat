@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [WARN] venv not found. Run setup_once.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate"

REM AI meta-controller + OpenAI LLM (tie-break / veto / primary)
set "USE_META_DECIDER=1"
set "LLM_ENABLED=1"

REM LLM mode: TIE_BREAK (override HOLD when confident), VETO (block quant if low conf), or PRIMARY (LLM decides)
REM set "LLM_MODE=TIE_BREAK"
REM set "LLM_MIN_CONF=0.65"
REM Ensure OPENAI_API_KEY is set in .env

echo [START] Running MoneyMaker (LIVE + AI + LLM)...
python Main.py --live-ai
pause
