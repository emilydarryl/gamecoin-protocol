# GameCoin Protocol — Mainnet v1.0.0

GameCoin is an open-source proof-of-work cryptocurrency protocol with an encrypted desktop wallet, CPU miner, full node, deterministic consensus rules, Windows packaging, and seed-node deployment files.

The code is published under the **MIT License** so it can be inspected, audited, built, and forked. Open source does **not** give a fork control over the official GameCoin Mainnet: incompatible consensus changes are accepted only by nodes that choose to run those changed rules. See `GOVERNANCE.md`.

## Mainnet identity

- Network: `gamecoin-mainnet`
- P2P protocol: `6`
- Genesis: `fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233`
- Mainnet RPC: `127.0.0.1:22444` (localhost only)
- Mainnet P2P: `22445`
- Mainnet address prefix: `M`
- Target block time: `150 seconds`
- Initial subsidy: `5 GAME`
- Halving interval: `2,102,400 blocks`
- Coinbase maturity: `100 blocks`
- Default wallet fee: `0.001 GAME`
- Genesis premine: `0 GAME`

## Monetary policy

One GAME equals 100,000,000 atoms. Block 0 has no spendable outputs. Block 1 begins the normal 5 GAME subsidy. The subsidy halves every 2,102,400 blocks using integer-atom arithmetic until it reaches zero.

## Consensus baseline

Mainnet freezes the candidate-2 consensus baseline proven on Public Testnet v4: deterministic integer chainwork, greatest-valid-work fork choice, median-time-past timestamp rules, adaptive-window-v0.6 difficulty, coinbase maturity, miner fee collection, strict address checksum validation, and transaction/block/mempool resource ceilings.

Normal transactions may not contain a `coinbase` field. Coinbase transactions are block-only and are rejected by RPC/P2P mempool submission before any already-known-TXID shortcut.

## Wallet separation

Mainnet wallets use the `gamecoin-mainnet-wallet` format and `M...` addresses. Testnet wallet files and testnet `G...` addresses are intentionally rejected. New wallets are encrypted by default with Argon2id + AES-256-GCM.

## Build and test

Install dependencies and run the unit tests:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

On Windows, `BUILD_INSTALLER.bat` builds a local development installer. **Official release artifacts are built by the checked-in GitHub Actions release workflow** so the source/build origin can be verified.

The GitHub-hosted v1.0.0 Windows release pipeline has been validated end-to-end, and its resulting unsigned installer has been tested successfully on Windows. Public-trust signing is not active yet.

## Code signing policy

GameCoin is applying for SignPath Foundation open-source code signing. Until acceptance and a successful signing request, GameCoin release installers remain unsigned and the acknowledgement below must not be interpreted as a claim that current binaries are signed.

**Required SignPath acknowledgement for signed releases:**

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

SignPath team roles for GameCoin:

- **Authors:** [@emilydarryl](https://github.com/emilydarryl)
- **Reviewers:** [@emilydarryl](https://github.com/emilydarryl)
- **Approvers:** [@emilydarryl](https://github.com/emilydarryl)

See `CODE_SIGNING_POLICY.md` and `docs/SIGNPATH_SETUP.md` for the full policy and build/signing controls.

## Security and privacy

GameCoin is experimental cryptocurrency software and this source distribution is not an independent security audit. Before operating with material value, keep multiple tested backups, verify the genesis hash and release hashes/signatures, run more than one independent seed/peer, and complete `RELEASE_CHECKLIST.md`.

- Security reporting: `SECURITY.md`
- Privacy/network communications: `PRIVACY.md`
- Experimental-software disclaimer: `DISCLAIMER.md`

## Contributing and governance

- Contribution guide: `CONTRIBUTING.md`
- Project governance and official-release control: `GOVERNANCE.md`
- Name/branding policy: `TRADEMARKS.md`

## Protocol documentation

See `docs/CONSENSUS.md`, `docs/NETWORK.md`, `docs/MAINNET.md`, and `server/VPS_SETUP.md`.

## License

Copyright (c) 2026 EmilyGaming. Unless a file explicitly states otherwise, the original code, documentation, build files, and bundled project artwork in this repository are licensed under the MIT License. Trademark/source-identifying rights in the GameCoin name and logos are addressed separately in `TRADEMARKS.md`.
