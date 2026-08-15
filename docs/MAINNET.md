# GameCoin Mainnet Readiness Plan

GameCoin v0.8.3 is the public-testnet baseline. Mainnet should not launch by renaming or reusing the current testnet chain.

## v0.9.0 Mainnet Candidate priorities

### Consensus

- replace floating-point cumulative work with deterministic integer chainwork
- select forks by greatest valid cumulative proof-of-work
- remove any seed-authority chain replacement path
- add median-time-past and future-time limits
- add coinbase maturity
- define transaction fees and miner fee collection
- enforce strict address checksums and canonical formatting
- cap transaction/block/mempool resource usage

### Wallet and keys

- encrypt wallet secrets at rest
- add lock/unlock behavior
- define backup/recovery workflow
- keep mining possible while locked if practical; require unlock for spending

### Networking

- support multiple independent seed nodes
- improve peer discovery and peer rotation
- ensure nodes remain usable if any one seed or website is unavailable

### Testing

Before mainnet genesis:

- freeze consensus rules
- add deterministic consensus test vectors
- test competing forks and reorgs
- test node crashes and restart recovery
- test malformed blocks and transactions
- test clock skew and timestamp edge cases
- test wallet backup/restore
- test upgrade paths
- run an extended multi-node soak test for at least roughly 10,000 blocks

## Mainnet launch

The mainnet launch should create a brand-new chain starting at height 0 with a new genesis block and no carried-over testnet balances.
