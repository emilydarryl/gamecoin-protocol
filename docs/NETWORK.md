# GameCoin Mainnet Network Separation

GameCoin Mainnet is intentionally isolated from all public testnets.

- Network: `gamecoin-mainnet`
- Protocol: `6`
- Genesis: `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- RPC: `127.0.0.1:22444`
- P2P: `22445`
- Windows data identity: `GameCoinMainnet`
- Default source data/log directories: `data-mainnet` / `logs-mainnet`
- Mainnet address prefix: `M`

Known older test chains use different network IDs, protocol identities, genesis hashes, ports and `G` addresses. Mainnet never imports their balances, mempool or chain history. If mainnet is pointed at a data directory whose `chain.json` has a different genesis, startup fails without modifying the foreign chain.

Only P2P port 22445 should be exposed publicly. RPC 22444 must remain localhost-only.
