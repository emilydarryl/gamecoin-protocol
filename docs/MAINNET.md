# GameCoin Mainnet v1.0.0

## Genesis

- Timestamp: `1787103720` (2026-08-19 01:42:00 UTC / 2026-08-18 20:42:00 UTC-05:00)
- Message: `GameCoin mainnet genesis 2026-08-18 | v1.0.0 | subsidy 5 GAME | halving 2102400 | target 150s | no premine`
- Genesis transaction: `2d55c15612d66f18f0f5e6c7151fefbcb19a285cfdaa67bd342894a14499d8a1`
- Genesis block: `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- Spendable genesis outputs: none

The first spendable issuance is the block-1 mining reward.

## Release identity

Mainnet uses network `gamecoin-mainnet`, P2P protocol 6, RPC/P2P ports 22444/22445, a separate Windows installer AppId/data directory, and `M...` addresses. Testnet chains and wallets are not migrated.

## Launch prerequisites

Before treating the network as production-ready with material value:

1. Run the complete automated test suite.
2. Re-run malformed transaction, duplicate-input, missing-input and explicit coinbase-submission tests against the packaged Windows binary.
3. Verify two independent machines produce the same genesis and status identity.
4. Operate at least two independent public P2P seeds/peers and test fresh-node synchronization/reorg behavior.
5. Back up and restore encrypted wallets on a separate machine.
6. Publish installer/source SHA-256 hashes and verify them from a clean host.
7. Keep RPC bound to localhost and expose only TCP 22445 on seed nodes.
