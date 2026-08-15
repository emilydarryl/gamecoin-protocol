# GameCoin Network Reference

## Public Testnet v2

Current v0.8.3 testnet settings:

- Network ID: `gamecoin-public-testnet-v2`
- P2P protocol: `3`
- Default public P2P port: `18445`
- Local wallet/miner RPC: `127.0.0.1:18444`
- Target block interval: `150 seconds`

The localhost RPC port must not be exposed publicly.

## Mainnet separation requirement

Mainnet should use its own:

- network ID
- genesis block/hash
- P2P protocol version if consensus/network behavior changes
- ports
- data directory
- address version/prefix
- seed list

Testnet should remain operational after mainnet launch so future releases can be tested against a non-value network first.
