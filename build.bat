@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [WARN] venv not found. Run setup_once.bat first.
  pause
  exit /b 1
)

call ".venv\Scripts\activate"

REM Install PyInstaller if missing
python -m pip install pyinstaller --quiet

echo [BUILD] Building MoneyMaker executable (one-folder)...
pyinstaller --noconfirm MoneyMaker.spec

if exist "dist\MoneyMaker\MoneyMaker.exe" (
  echo.
  echo [OK] Built: dist\MoneyMaker\MoneyMaker.exe
  echo Run from dist\MoneyMaker\ with .env in that folder (or same dir as exe).
  echo Example: cd dist\MoneyMaker ^& MoneyMaker.exe --live
) else (
  echo [FAIL] Build did not produce dist\MoneyMaker\MoneyMaker.exe
)

pause
