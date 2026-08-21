@echo off
setlocal
cd /d "%~dp0"
echo Installing GameCoin mainnet dependencies...
py -3 -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Setup failed. Make sure Python 3 is installed and the "py" command works.
  pause
  exit /b 1
)
echo.
echo Setup complete.
pause
