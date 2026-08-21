@echo off
setlocal
cd /d "%~dp0"
echo Starting GameCoin MAINNET node v1.0.0...
echo Wallet/miner RPC stays on 127.0.0.1:22444.
echo The node will sync from the peer(s) in config.json.
echo.
py -3 node.py --config config.json
pause
