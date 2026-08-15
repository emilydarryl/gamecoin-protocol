# GameCoin Consensus Reference

This document records the consensus parameters of **GameCoin Public Testnet v2 / v0.8.3** as a baseline for the v0.9.x mainnet-candidate work. It is **not** the final mainnet specification.

## Current public-testnet-v2 parameters

- Network ID: `gamecoin-public-testnet-v2`
- P2P protocol: `3`
- Genesis hash: `15318ffdacb299fcf99464f9b98e5796f6629144db5b2c7f2bc2554168ea1b9b`
- Atomic unit: `100,000,000` atoms per GAME
- Initial non-genesis block subsidy: `5 GAME`
- Halving interval: `2,102,400` blocks
- Target block interval: `150 seconds`
- Bootstrap difficulty: `1000x`
- Exact maximum supply under integer-atom halvings: `21,023,999.72668800 GAME`
- Genesis subsidy: `0 GAME`

## Monetary policy

The block subsidy is determined only by height. Height 0 receives no subsidy. Heights 1 through 2,102,400 receive 5 GAME per block; later eras repeatedly halve the subsidy using integer atom arithmetic until the subsidy reaches zero.

## v0.9.x consensus work before mainnet

The mainnet-candidate line must freeze and test the following rules before a mainnet genesis block is created:

1. Integer-only cumulative chainwork.
2. Fork choice based on greatest valid cumulative proof-of-work, with no seed-authority override.
3. Median-time-past and maximum-future-time timestamp validation.
4. Coinbase maturity.
5. Explicit transaction-fee accounting and miner fee collection.
6. Strict address decoding/checksum validation.
7. Transaction and block resource limits.
8. Deterministic validation test vectors for block hashes, transaction IDs, subsidy boundaries, difficulty, timestamps, reorgs, and chainwork.

Any change to these rules after mainnet launch must be treated as a consensus change and versioned accordingly.
