# GameCoin v1.0.0 Mainnet Release Checklist

- [ ] Confirm network `gamecoin-mainnet`, protocol `6`, genesis `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`.
- [ ] Confirm RPC is localhost-only on `22444`; public P2P is `22445`.
- [ ] Confirm a fresh wallet produces an `M...` address and a testnet `G...` address is rejected.
- [ ] Confirm genesis has zero spendable outputs and circulating supply is 0 at height 0.
- [ ] Confirm block 1 subsidy is exactly 5.00000000 GAME.
- [ ] Confirm coinbase maturity is exactly 100 blocks.
- [ ] Confirm normal `/tx` submission containing any `coinbase` field is rejected, even if its TXID is already known.
- [ ] Re-run invalid-TXID, duplicate-input, missing-input, bad-signature, bad-address and overspend tests.
- [ ] Re-run fee collection, timestamp, resource-ceiling, adaptive difficulty and greatest-work reorg tests.
- [ ] Confirm mainnet refuses a foreign/testnet chain.json without modifying it.
- [ ] Test encrypted wallet create/lock/unlock/password-change/backup/recovery.
- [ ] Verify fresh-node synchronization between at least two independent peers.
- [ ] Build the Windows installer on a clean host and publish SHA-256.
- [ ] Verify installer and source package hashes from a second machine.
- [ ] Back up seed-node configuration and document firewall rule exposing only TCP 22445.

## Open-source / signed release checks

- [ ] Confirm the release commit is in the official public GitHub repository and contains no secrets or wallet material.
- [ ] Confirm CI passes on the release commit.
- [ ] Confirm installer PE metadata identifies `GameCoin Mainnet`, version `1.0.0`, and publisher/company `EmilyGaming`.
- [ ] If SignPath Foundation signing is active, confirm the signing request has verified GitHub origin and an authorized approval.
- [ ] Verify Authenticode on the final signed installer from a clean Windows machine.
- [ ] Generate and publish SHA-256 **after signing**; do not reuse the unsigned installer hash.
- [ ] Confirm the website/release page links `CODE_SIGNING_POLICY.md` and `PRIVACY.md`.
