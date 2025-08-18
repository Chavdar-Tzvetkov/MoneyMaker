@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [WARN] venv not found. Run setup_once.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate"

REM Optional: auto-update ONLY if requirements.txt changed
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
    echo [DEPS] requirements.txt changed -> updating...
    python -m pip install -r requirements.txt
    > ".venv\req.sha256" echo %NEWHASH%
  )
)

REM You can keep these toggles in .env; the next two are just overrides if needed
set "USE_META_DECIDER=1"
set "LLM_ENABLED=0"

echo [START] Running MoneyMaker (LIVE + AI)...
python main.py --live-ai
pause
