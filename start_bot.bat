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
set "LLM_ENABLED=1"

echo [START] Running MoneyMaker (LIVE)...
python Main.py --live
pause
