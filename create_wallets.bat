@echo off
setlocal
cd /d "%~dp0"
set /p COUNT=How many mainnet wallets do you want to create? [3]: 
if "%COUNT%"=="" set COUNT=3
py -3 wallet.py create --count %COUNT% --dir wallets
echo.
py -3 wallet.py list --dir wallets
pause
