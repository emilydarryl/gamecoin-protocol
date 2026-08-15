"""Non-consensus wallet and relay policy for the GameCoin candidate line."""

from gamecoin.consensus import COIN

# Wallets pay this amount by default. Consensus does not require a minimum fee;
# the actual fee is the difference between transaction inputs and outputs.
DEFAULT_TRANSACTION_FEE = COIN // 1_000  # 0.001 GAME
