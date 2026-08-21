"""Non-consensus wallet and relay policy for GameCoin Mainnet."""

from gamecoin.consensus import COIN

# Consensus permits zero-fee transactions. The wallet defaults to 0.001 GAME.
DEFAULT_TRANSACTION_FEE = COIN // 1_000
