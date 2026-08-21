# Code signing policy

**Status: SignPath Foundation application preparation. Public-trust signing is not yet active.**

GameCoin intends to use SignPath.io with a certificate provided by SignPath Foundation for official Windows releases after the project is accepted. Until acceptance is confirmed, this repository must not claim that a release is signed by SignPath Foundation.

After acceptance, the project website and release pages will display the required acknowledgement:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation.

## Team roles

- **Committer and reviewer:** [@emilydarryl](https://github.com/emilydarryl)
- **Release/signing approver:** [@emilydarryl](https://github.com/emilydarryl)

When additional team members are granted these roles, this policy and the corresponding GitHub/SignPath permission groups must be updated.

## Source and review rules

- Official release artifacts must originate from `emilydarryl/gamecoin-protocol`.
- External contributions must be reviewed by a GameCoin maintainer before merge.
- Build scripts, GitHub Actions workflows, installer definitions, dependency files, and signing configuration are treated as security-sensitive source and receive the same review as application code.
- Official signing requests may only originate from GitHub-hosted Actions using SignPath's GitHub trusted-build integration and origin verification.
- Release signing is restricted to the protected official release path configured in SignPath. Local developer builds are not submitted for public-trust signing.
- Signing requests require approval by an authorized release/signing approver.

## What may be signed

Only GameCoin artifacts built from source maintained in this repository may be signed using the GameCoin signing project. Third-party binaries must not be re-signed as GameCoin components.

The initial Windows signing target is `GameCoin-Setup-v1.0.0-Mainnet.exe`. The SignPath artifact configuration constrains the expected product identity and version metadata before signing.

## Privacy policy

See [PRIVACY.md](PRIVACY.md). GameCoin does not implement analytics or behavioral telemetry, but it does communicate with configured peers and performs the documented update check.
