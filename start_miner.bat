@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
echo Available wallets:
py -3 wallet.py list --dir wallets
echo.
set /p WALLET=Enter wallet filename or short name (example wallet_001): 
if "%WALLET%"=="" exit /b 1
if not exist "wallets\%WALLET%" (
  if exist "wallets\%WALLET%.wallet.json" set WALLET=%WALLET%.wallet.json
)
if not exist "wallets\%WALLET%" (
  echo Wallet not found: wallets\%WALLET%
  pause
  exit /b 1
)
set /p THREADS=CPU processes to use [2]: 
if "%THREADS%"=="" set THREADS=2
py -3 miner.py --wallet "wallets\%WALLET%" --threads %THREADS% --log-dir logs
pause
