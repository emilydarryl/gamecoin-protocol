# SignPath Foundation application draft

This page contains the public, non-secret information prepared for the GameCoin SignPath Foundation application. Do not place SignPath API tokens, passwords, recovery codes, or other credentials in this file or in GitHub issues.

## Project information

- **Project name:** GameCoin Protocol
- **Suggested project handle:** `gamecoin-protocol`
- **Homepage:** https://github.com/emilydarryl/gamecoin-protocol
- **Source repository:** https://github.com/emilydarryl/gamecoin-protocol
- **License:** MIT License
- **Primary platform to sign:** Windows
- **Initial signing target:** `GameCoin-Setup-v1.0.0-Mainnet.exe`

## Project description

GameCoin is an open-source proof-of-work cryptocurrency protocol and desktop application suite. The repository contains the full node, encrypted desktop wallet, user-launched CPU miner, deterministic consensus implementation, tests, Windows packaging scripts, and seed-node deployment files. Mainnet v1.0.0 uses a fixed public genesis, P2P protocol 6, 150-second target block time, 5 GAME initial block subsidy, no genesis premine, and a 100-block coinbase maturity rule.

The CPU miner is an explicit user-launched application. It is not installed as a hidden service and is not intended to mine without the user's knowledge or consent.

## Why code signing is requested

GameCoin distributes a Windows installer directly to users. The project wants public-trust Authenticode signing so users can verify publisher integrity and, more importantly, so each signed binary can be tied to an automated build from the public source repository through SignPath origin verification.

## Release and build provenance

Official Windows release candidates are built by `.github/workflows/release-windows.yml` using GitHub-hosted runners. The workflow runs tests, verifies the fixed mainnet identity/genesis, renders versioned branding assets from source, builds the node/miner/wallet and Inno Setup installer, computes SHA-256, and uploads the unsigned installer as a workflow artifact.

The first GitHub-hosted v1.0.0 unsigned installer was successfully tested on Windows before this application was prepared.

- **Validated unsigned installer SHA-256:** `295416d431925d85e124a3ab3be5725c40a2f434bd543293d62da7e6945b3dd8`
- **Release form:** Inno Setup Windows installer (`GameCoin-Setup-v1.0.0-Mainnet.exe`)

Before submitting the application, provide SignPath with a stable public download/release URL for this release form if one is not already published.

## Code signing policy

See [../CODE_SIGNING_POLICY.md](../CODE_SIGNING_POLICY.md).

Required acknowledgement for signed releases:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

Team roles:

- **Authors:** [@emilydarryl](https://github.com/emilydarryl)
- **Reviewers:** [@emilydarryl](https://github.com/emilydarryl)
- **Approvers:** [@emilydarryl](https://github.com/emilydarryl)

Every signing request will require manual approval by an authorized approver.

## Privacy

See [../PRIVACY.md](../PRIVACY.md). GameCoin does not implement analytics or behavioral telemetry. Network communication consists of documented peer/node communication and the documented update-check behavior.

## Security and maintenance

- Security policy: [../SECURITY.md](../SECURITY.md)
- Governance: [../GOVERNANCE.md](../GOVERNANCE.md)
- Contribution policy: [../CONTRIBUTING.md](../CONTRIBUTING.md)
- SignPath integration plan: [SIGNPATH_SETUP.md](SIGNPATH_SETUP.md)
- SignPath artifact configuration: [../.signpath/artifact-configurations/windows-installer.xml](../.signpath/artifact-configurations/windows-installer.xml)

The project is actively maintained and uses public GitHub Actions CI on Linux and Windows.

## Maintainer checks before submission

1. Confirm GitHub multi-factor authentication is enabled for every Author, Reviewer, and Approver.
2. Publish a stable public download/release URL for the unsigned v1.0.0 installer in the form that will be signed.
3. Confirm the public download page includes or links the **Code signing policy** and privacy policy.
4. Submit the SignPath Foundation application using the information above.
5. Do not claim that GameCoin is signed by SignPath Foundation until acceptance and a successful signing request.
