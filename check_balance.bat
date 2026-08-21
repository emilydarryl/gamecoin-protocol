@echo off
setlocal
cd /d "%~dp0"
py -3 wallet.py list --dir wallets
echo.
set /p WALLET=Enter wallet filename: 
if "%WALLET%"=="" exit /b 1
py -3 wallet.py balance "wallets\%WALLET%"
pause
