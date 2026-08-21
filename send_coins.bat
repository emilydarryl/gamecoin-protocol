@echo off
setlocal
cd /d "%~dp0"
py -3 wallet.py list --dir wallets
echo.
set /p WALLET=Wallet filename to send FROM: 
set /p TO=Destination GameCoin mainnet address: 
set /p AMOUNT=Amount of GAME to send: 
if "%WALLET%"=="" exit /b 1
if "%TO%"=="" exit /b 1
if "%AMOUNT%"=="" exit /b 1
py -3 wallet.py send "wallets\%WALLET%" --to "%TO%" --amount "%AMOUNT%"
pause
