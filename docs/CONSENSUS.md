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

## v0.9.x candidate transaction rules

### Coinbase maturity

A mining coinbase output is not spendable until **100 blocks** after the block that created it. A coinbase created at height `H` becomes valid as an input in block `H + 100`.

Mempool validation evaluates maturity against the height of the next candidate block. The UTXO set therefore tracks whether an output came from a coinbase and the block height at which it was created.

### Transaction fees

GameCoin uses implicit UTXO fees. A transaction fee is:

`sum(inputs) - sum(outputs)`

Outputs may never exceed inputs. A zero-fee transaction remains consensus-valid for now; minimum relay/mining fee policy can be added separately without changing the transaction accounting rule.

For the candidate wallet, the default fee policy is **0.001 GAME (100,000 atoms)** per transaction. This is wallet policy, not a consensus minimum.

A valid candidate block must pay its coinbase output exactly:

`block subsidy + sum(transaction fees in the block)`

This prevents transaction value from silently disappearing and makes all included transaction fees available to the miner that confirms the block.

## Hard-fork / testnet note

Coinbase maturity and miner fee collection change block and transaction validity. They must **not** be activated retroactively on the existing public-testnet-v2 history. The v0.9.0 mainnet-candidate line should exercise these rules on a new candidate testnet/network genesis before mainnet is created.

## Remaining v0.9.x consensus work before mainnet

The mainnet-candidate line must freeze and test the following rules before a mainnet genesis block is created:

1. Integer-only cumulative chainwork.
2. Fork choice based on greatest valid cumulative proof-of-work, with no seed-authority override.
3. Median-time-past and maximum-future-time timestamp validation.
4. **Coinbase maturity: implemented in candidate rules; node integration and candidate-network soak testing remain.**
5. **Explicit transaction-fee accounting and miner fee collection: implemented in candidate rules; node/wallet integration and soak testing remain.**
6. Strict address decoding/checksum validation.
7. Transaction and block resource limits.
8. Deterministic validation test vectors for block hashes, transaction IDs, subsidy boundaries, difficulty, timestamps, reorgs, chainwork, maturity, and fees.

Any change to these rules after mainnet launch must be treated as a consensus change and versioned accordingly.
