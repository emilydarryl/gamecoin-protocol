# Contributing to GameCoin

Thank you for helping improve GameCoin. Bug reports, tests, documentation fixes, security hardening, wallet improvements, and protocol research are welcome.

## Development workflow

1. Fork the repository and create a focused branch.
2. Keep private keys, wallet files, passwords, seeds, credentials, and production data out of commits and issue reports.
3. Add or update tests for behavioral changes.
4. Run `python -m unittest discover -s tests -v` before opening a pull request.
5. Open a pull request describing the problem, the proposed change, and any compatibility or consensus impact.

External contributions are reviewed by an official GameCoin maintainer before merge. A pull request does not become part of the official protocol merely because its source code is public.

## Consensus and network changes

Changes to consensus, transaction validity, block validity, monetary policy, difficulty adjustment, address encoding, network identity, genesis rules, fork choice, or P2P protocol are high-risk changes.

A consensus-impacting pull request must:

- clearly label the consensus effect;
- include deterministic tests covering acceptance and rejection cases;
- document activation or compatibility behavior;
- preserve the current mainnet genesis unless an explicitly planned new network is being created; and
- receive explicit maintainer approval before any official release adopts it.

Do not silently change `gamecoin-mainnet`, P2P protocol `6`, the fixed mainnet genesis, subsidy rules, or other consensus constants in an unrelated pull request.

## Mining behavior

The CPU miner must remain user-initiated and visible. Contributions must not make mining start secretly, persist without user consent, evade process controls, or consume resources without clear user action.

## Security reports

Do not disclose an exploitable wallet, consensus, network, signing, or key-management vulnerability in a public issue before maintainers have had a reasonable opportunity to respond. Follow `SECURITY.md`.

## License

By contributing, you agree that your contribution may be distributed under the repository's MIT License. You retain copyright in your contribution.
