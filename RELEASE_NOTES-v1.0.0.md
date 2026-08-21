# GameCoin v1.0.0 Mainnet

## Mainnet identity

- Network: `gamecoin-mainnet`
- Protocol: `6`
- Genesis: `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- RPC/P2P: `22444` / `22445`
- Address prefix: `M`
- Initial block reward: `5 GAME`
- Coinbase maturity: `100 blocks`
- Target block interval: `150 seconds`
- Genesis premine: `0 GAME`

## Changes from Public Testnet v4

- New network ID, protocol identity, ports, data directory, installer identity, executable names and genesis.
- Testnet `G...` addresses replaced by mainnet `M...` addresses; testnet addresses are rejected.
- Mainnet wallet format is isolated from testnet wallet files.
- Mismatched/foreign chain data fails closed and is never automatically archived or reset.
- Normal transaction submission rejects any `coinbase` field before duplicate/already-known TXID handling.
- Consensus monetary/difficulty/resource rules otherwise preserve the tested candidate-2 baseline.
- Windows builds run the full automated test suite and verify the fixed mainnet identity before packaging.

## Fixed genesis message

`GameCoin mainnet genesis 2026-08-18 | v1.0.0 | subsidy 5 GAME | halving 2102400 | target 150s | no premine`

After public launch, changing the genesis message, timestamp, address encoding, consensus constants, or mainnet network identity creates an incompatible chain.
