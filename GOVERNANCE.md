# GameCoin Project Governance

## Official project

The official source repository is intended to be `https://github.com/emilydarryl/gamecoin-protocol`. The initial project maintainer and release approver is `@emilydarryl`.

The repository is open source, but repository visibility does not give third parties control over the official GameCoin Mainnet. Anyone may modify and run their own copy under the MIT License. Modified consensus rules only affect nodes that choose to run those rules. Incompatible rule changes create or join a different fork; they do not force official GameCoin nodes to accept invalid blocks or transactions.

## Maintainer responsibilities

Maintainers decide what is merged into the official repository, which commits are tagged as official releases, and whether a proposed consensus change is suitable for adoption. Maintainers are expected to review external contributions, protect release credentials, keep build and signing workflows under source control, and respond responsibly to security reports.

## Consensus changes

Consensus changes require explicit review and release planning. They are never activated merely by merging an unrelated feature or by a third-party fork existing on GitHub.

For compatibility-sensitive changes, the project should document the activation condition, versioning impact, migration plan, and expected behavior of older nodes before release.

## Official releases

An official release must be built from the official repository using the checked-in GitHub Actions release workflow. When trusted code signing is active, release signing must use the project's approved SignPath signing policy and origin verification. Manually built local binaries are development artifacts and are not eligible for official SignPath release signing.

## Additional maintainers

Additional committers, reviewers, or signing approvers may be added later. `CODE_SIGNING_POLICY.md` and repository permissions must be updated when those roles change.
