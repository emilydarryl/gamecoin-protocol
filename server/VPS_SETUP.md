# GameCoin v1.0.0 Mainnet Seed

## Isolation

- Install under `/opt/gamecoin-mainnet`.
- Mainnet RPC: `127.0.0.1:22444`.
- Mainnet P2P: `0.0.0.0:22445`.
- Data: `/opt/gamecoin-mainnet/data`.
- Logs: `/opt/gamecoin-mainnet/logs`.
- Do not copy a testnet chain database into the mainnet data directory.
- Do not store wallet/private-key files on a public seed.

## Service

Install `server/gamecoin-mainnet.service` as `/etc/systemd/system/gamecoin-mainnet.service`, then daemon-reload, enable and start it.

The status endpoint should report:

- network `gamecoin-mainnet`
- P2P protocol `6`
- node version `1.0.0`
- genesis `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- coinbase maturity `100`
- integer `total_work`

RPC port 22444 remains localhost-only. Expose only TCP 22445 publicly.
