# SignPath Foundation Setup for GameCoin

This document prepares GameCoin for a SignPath Foundation Open Source Code Signing application. It does not imply that the project has already been accepted.

## Eligibility preparation

Before applying:

1. Make the official repository public and confirm GitHub detects the MIT license.
2. Keep the complete maintained source, build scripts, installer definition, tests, and signing configuration in the public repository.
3. Publish/link `CODE_SIGNING_POLICY.md` from the project home/download pages.
4. Publish/link `PRIVACY.md`.
5. Enable MFA for maintainers and signing approvers.
6. Ensure the CPU miner is user-initiated, visible, and easy to stop.
7. Enable GitHub private vulnerability reporting.
8. Keep official Windows builds on GitHub-hosted runners.

## SignPath project

Suggested values after acceptance/setup:

- Project name: `GameCoin Protocol`
- Project slug: `gamecoin-protocol`
- Repository URL: `https://github.com/emilydarryl/gamecoin-protocol`
- Trusted build system: predefined `GitHub.com`
- Artifact configuration: use `.signpath/artifact-configurations/windows-installer.xml` as the starting configuration
- Release signing policy slug: `release-signing`
- Origin verification: enabled
- Release signing approval: required

Upload an actual unsigned installer sample to SignPath and compare SignPath's generated configuration with the checked-in XML before enabling production signing. Do not weaken generated restrictions just to make a signing request pass.

## GitHub configuration

The workflow expects these values only after SignPath is active:

Repository secret:

- `SIGNPATH_API_TOKEN`

Repository variables:

- `SIGNPATH_ENABLED=true`
- `SIGNPATH_ORGANIZATION_ID=<organization UUID>`
- `SIGNPATH_PROJECT_SLUG=gamecoin-protocol`
- `SIGNPATH_SIGNING_POLICY_SLUG=release-signing`
- `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG=windows-installer`

The CI user behind the API token should only have the SignPath permissions needed to submit signing requests. Signing approval should remain a separate authorized action.

## GitHub trusted-build requirements

SignPath's GitHub integration should be linked to the GameCoin project and origin verification enabled. All jobs leading to an OSS signing request must use GitHub-hosted runners. Protect the official release path from force-pushes and require the repository's test checks to pass.

## Activation

Only after SignPath Foundation acceptance:

1. Set `SIGNPATH_ENABLED=true`.
2. Add the required SignPath secret/variables.
3. Update the website and release pages to display: `Free code signing provided by SignPath.io, certificate by SignPath Foundation.`
4. Run a release workflow and verify the resulting Authenticode signature on a clean Windows machine.
5. Publish the SHA-256 of the **signed** installer, because signing changes the file hash.
