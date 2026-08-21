# GameCoin Open-Source Release Preparation Report

Prepared for `emilydarryl/gamecoin-protocol` from the GameCoin v1.0.0 Mainnet Windows Builder.

## Validation

- Unit tests: **37 passed / 0 failed**.
- Mainnet network identity, protocol number, genesis hash, wallet/address separation, coinbase maturity, fee rules, difficulty rules, reorg rules, timestamp rules, encrypted-wallet behavior, and coinbase mempool rejection remain covered by the existing test suite.
- `node.py`, `miner.py`, `wallet.py`, `wallet_gui.py`, `config.json`, `MAINNET_GENESIS.json`, and the `gamecoin/` protocol package are unchanged from the tested v1.0.0 builder.
- SignPath artifact-configuration XML is well-formed.
- GitHub Actions workflow YAML parses successfully.
- Windows PyInstaller version-info files parse as valid Python syntax.
- Repository scan found no embedded private-key blocks, assigned master seeds/private keys, API tokens, or email addresses in the prepared source tree.

## Open-source preparation

- Replaced the former custom disclaimer-only license with the OSI-approved MIT License.
- Added contribution, governance, privacy, security, branding, and experimental-software policies.
- Added CODEOWNERS for `@emilydarryl`.
- Added pull-request and bug-report templates.
- Added cross-platform CI.
- Added a GitHub-hosted Windows release workflow with optional SignPath integration.
- Added Windows PE version metadata for GameCoin executables and installer metadata suitable for SignPath restrictions.
- Added a checked-in SignPath artifact-configuration starting point and setup guide.

## Remaining external steps

1. Review and merge the staged private-repository pull request.
2. Make the repository public only after the final secret/publication review.
3. Enable GitHub branch/ruleset protections, private vulnerability reporting, and relevant security features.
4. Apply to SignPath Foundation.
5. After acceptance, configure SignPath organization/project/policy values and enable `SIGNPATH_ENABLED=true`.
6. Publish the required SignPath acknowledgement on the GameCoin home/download/release pages only after acceptance.
