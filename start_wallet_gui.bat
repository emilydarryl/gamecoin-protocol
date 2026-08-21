@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if not errorlevel 1 (
  start "GameCoin Mainnet Wallet v1.0.0" pyw -3 wallet_gui.py
  exit /b 0
)
py -3 wallet_gui.py
if errorlevel 1 pause
