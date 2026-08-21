# Security Policy

GameCoin v1.0.0 is experimental mainnet cryptocurrency software. This repository and release process do not constitute an independent security audit.

## Reporting a vulnerability

Please do **not** publish an exploitable wallet, consensus, networking, signing, release-pipeline, or key-storage vulnerability in a public issue before maintainers have had a reasonable opportunity to respond.

Preferred reporting path: GitHub private vulnerability reporting / repository Security Advisories once enabled for the public repository. If that channel is unavailable, contact the GameCoin maintainer through the official EmilyGaming site and state that the message concerns a private GameCoin security report.

Never include wallet files, passwords, master seeds, private keys, VPS credentials, API tokens, `.env` contents, or other secrets in a public report.

## Wallet storage

New mainnet wallets are encrypted by default with Argon2id-derived AES-256-GCM keys. Public address metadata remains readable while locked, but the deterministic master seed must not appear as plaintext `master_seed` or `private_key` fields in an encrypted version-3 wallet file.

A strong wallet password is required. Losing both the password and all usable recovery material can make an encrypted wallet unrecoverable. Back up encrypted wallet files before receiving funds and test recovery offline.

## Network separation

Mainnet uses `M...` addresses, its own wallet format, genesis, network ID, protocol, ports, and data directory. Testnet wallets and `G...` addresses are rejected. RPC must remain localhost-only unless an operator has independently designed and secured an authenticated remote-RPC deployment.

## Release security

Official releases should be built from the official GitHub repository on GitHub-hosted runners. Release hashes must be published. When SignPath Foundation signing is active, public-trust signing must use origin verification and the policy in `CODE_SIGNING_POLICY.md`.
