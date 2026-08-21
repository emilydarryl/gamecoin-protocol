#!/usr/bin/env bash
set -euo pipefail
cd /opt/gamecoin-mainnet
exec .venv/bin/python node.py \
  --seed-mode \
  --rpc-host 127.0.0.1 \
  --rpc-port 22444 \
  --p2p-host 0.0.0.0 \
  --p2p-port 22445 \
  --data-dir /opt/gamecoin-mainnet/data \
  --log-dir /opt/gamecoin-mainnet/logs
