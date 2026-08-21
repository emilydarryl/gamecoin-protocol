# GitHub Repository Setup

Official repository: `emilydarryl/gamecoin-protocol`

## Before making the repository public

- Review the staged open-source branch for accidental secrets, private wallet material, production credentials, or private server data.
- Confirm the fixed mainnet genesis and consensus tests still pass.
- Confirm `LICENSE` is the MIT License and GitHub recognizes it.
- Confirm all bundled files intended for public release may be published.

## Recommended repository settings

- Default branch: `main`
- Disable force pushes and branch deletion on `main`.
- Require the `CI / tests` checks before merging.
- Require pull requests for external contributions.
- Keep `CODEOWNERS` current when maintainers change.
- Enable Dependabot alerts and secret scanning where available.
- Enable private vulnerability reporting.
- Require MFA for maintainers.

For a one-maintainer project, do not configure a review rule that makes it impossible for the maintainer to merge their own maintenance work. External contributions must still be reviewed by the maintainer before merge. If a second maintainer is added, require at least one approving review for protected release branches.

## Releases

Use `.github/workflows/release-windows.yml` for official Windows build provenance. Local `BUILD_INSTALLER.bat` builds are development/test artifacts.

When SignPath is activated, protect the branch/tag path allowed by the release signing policy and do not sign artifacts copied in from local machines.
