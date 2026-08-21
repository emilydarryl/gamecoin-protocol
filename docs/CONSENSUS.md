# GameCoin Mainnet v1.0.0 Consensus

- Network ID: `gamecoin-mainnet`
- P2P protocol: `6`
- Genesis: `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- Atomic unit: `100,000,000` atoms per GAME
- Initial subsidy: `5 GAME`
- Halving interval: `2,102,400` blocks
- Target interval: `150 seconds`
- Bootstrap difficulty: `1000x` (`1,000,000,000` units)
- Coinbase maturity: `100 blocks`
- Genesis premine: `0 GAME`

## Fork choice

Every candidate chain must validate from the mainnet genesis. Cumulative work is an arbitrary-precision integer. A conflicting chain replaces the local chain only when its valid cumulative proof-of-work is strictly greater. Peer or seed identity does not override chainwork.

## Time and difficulty

A block timestamp must be strictly greater than the median timestamp of the preceding 11 blocks and no more than two hours beyond the validating node's current time. Median-time-past is used for timestamp validity only. Difficulty measures adjacent validated block timestamps, clamps each sample to 37–600 seconds, and uses rolling expected-work/time over 12 blocks. Upward adjustment is capped between 1.10x and 1.75x depending on observed pace; downward adjustment is capped at 0.67x per block. Status exposes this as `adaptive-window-v0.6`.

## Transactions and fees

For each normal transaction, `fee = sum(inputs) - sum(outputs)`. Outputs may not exceed inputs. A normal transaction must have at least one input and one output, pass signature/address checks, and may not contain a `coinbase` field.

Coinbase is valid only as transaction 0 of a valid non-genesis mined block. Its output value must equal the allowed height subsidy plus fees from all included normal transactions. Coinbase transactions are never valid mempool entries.

## Resource ceilings

- 128 inputs per transaction
- 128 outputs per transaction
- 100,000 serialized bytes per transaction
- 1,000 transactions per block, including coinbase
- 2,000,000 serialized bytes per block
- 5,000 transactions in the mempool

## Addresses

Mainnet addresses use the canonical `M` prefix plus Base58 payload/checksum encoding. Testnet `G` addresses are invalid on mainnet.
