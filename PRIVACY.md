# Privacy Policy

GameCoin is peer-to-peer cryptocurrency software. It does not contain advertising analytics, behavioral tracking, or a telemetry service.

## Network communications

GameCoin necessarily communicates with networked systems when those features are used:

- The node connects to configured GameCoin peers to discover chain state, synchronize blocks, relay valid transactions, and relay valid blocks. Peer operators can observe normal network metadata such as the connecting IP address and GameCoin user-agent string.
- The wallet communicates with the local GameCoin RPC service on `127.0.0.1:22444` for balances, transactions, mining controls, and chain status.
- The wallet performs an automatic update-manifest check against `https://emilygaming.com/gamecoin/mainnet-latest.json` when the GUI starts and when the user requests an update check. That HTTP request identifies the software version in its user-agent and, like ordinary web traffic, exposes the requesting IP address to the web server and its infrastructure.
- If the user opens the download page, their default web browser connects to the configured EmilyGaming download URL.

## Wallet and blockchain data

Private keys, deterministic wallet seeds, and wallet passwords are intended to remain on the user's device. GameCoin does not intentionally transmit those secrets to EmilyGaming or to peers.

Public blockchain information is not private. Addresses, transaction identifiers, amounts, block data, and other data included in or relayed for the public blockchain can be observed and retained by network participants.

Local node and wallet logs may contain operational information. Users are responsible for protecting their local log files and should inspect them before sharing diagnostics publicly.

## Third-party infrastructure

Users who obtain GameCoin from GitHub, EmilyGaming, SignPath, hosting providers, DNS providers, or other third-party infrastructure are also subject to those providers' own privacy practices.
