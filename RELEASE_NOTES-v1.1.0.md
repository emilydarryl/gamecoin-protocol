# GameCoin v1.1.0 Mainnet

This coordinated network upgrade adds public pool identification and improves wallet balance clarity.

## Pool tags

Miners and pools may add a public pool tag of up to 32 safe characters to a block template. The tag is committed to the coinbase transaction as `height:<height>|pool:<name>` and is permanently public. The desktop wallet exposes this as **Pool tag** on the Mining tab, and the command-line miner accepts `--pool-tag`.

Pool tags identify mining software or pool operators; they are not verified legal identities. Coinbase transactions are created only when blocks are found, so pool tags appear on mined blocks rather than in the transaction mempool.

## Coinbase maturity upgrade

- Existing rule: 100-block maturity.
- New rule: 10-block maturity.
- Activation: candidate block height 500.
- Genesis, supply, rewards, halvings, target time, and difficulty rules are unchanged.

All nodes and wallets must upgrade to P2P protocol 7 before activation. The scheduled activation prevents an immediate rule change on the live chain and gives operators time to upgrade.

## Wallet clarity

The Overview tab now distinguishes total, spendable, and immature mining balances. This explains why a wallet can show mined GAME while still rejecting a send that exceeds currently spendable funds.
