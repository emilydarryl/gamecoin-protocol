"""Consensus constants and monetary policy for GameCoin public testnet v2."""

COIN = 100_000_000
INITIAL_BLOCK_REWARD = 5 * COIN
HALVING_INTERVAL_BLOCKS = 2_102_400
TARGET_BLOCK_SECONDS = 150
COINBASE_MATURITY = 100


def block_subsidy(height: int) -> int:
    """Return the allowed coinbase subsidy, in atoms, for a non-genesis block height."""
    height = int(height)
    if height <= 0:
        return 0
    halvings = (height - 1) // HALVING_INTERVAL_BLOCKS
    if halvings >= 63:
        return 0
    return INITIAL_BLOCK_REWARD >> halvings


def coinbase_is_mature(created_height: int, spend_height: int) -> bool:
    """Return whether a coinbase output may be spent in ``spend_height``.

    A coinbase created at height H becomes spendable in block H +
    ``COINBASE_MATURITY``. For a mempool transaction, callers should use the
    height of the next candidate block as ``spend_height``.
    """
    created_height = int(created_height)
    spend_height = int(spend_height)
    if created_height < 0 or spend_height < 0:
        return False
    return spend_height - created_height >= COINBASE_MATURITY


def circulating_supply(height: int) -> int:
    """Return cumulative mined subsidy through ``height`` (genesis is height 0)."""
    remaining = max(0, int(height))
    reward = INITIAL_BLOCK_REWARD
    total = 0
    while remaining > 0 and reward > 0:
        blocks = min(remaining, HALVING_INTERVAL_BLOCKS)
        total += blocks * reward
        remaining -= blocks
        reward //= 2
    return total


def maximum_supply() -> int:
    """Return the exact maximum supply under integer-atom halvings."""
    reward = INITIAL_BLOCK_REWARD
    total = 0
    while reward > 0:
        total += HALVING_INTERVAL_BLOCKS * reward
        reward //= 2
    return total


MAX_SUPPLY = maximum_supply()


def next_halving_height(height: int) -> int | None:
    """Return the first block height paid at the next lower subsidy."""
    height = max(0, int(height))
    current_reward = block_subsidy(height + 1)
    if current_reward <= 0:
        return None
    era = height // HALVING_INTERVAL_BLOCKS
    transition = (era + 1) * HALVING_INTERVAL_BLOCKS + 1
    return transition


def blocks_until_halving(height: int) -> int | None:
    """Return blocks remaining before the reward changes for newly mined blocks."""
    nxt = next_halving_height(height)
    if nxt is None:
        return None
    # At height H, the next candidate block is H+1. If that candidate is the
    # transition block, zero blocks remain at the old reward.
    return max(0, nxt - (int(height) + 1))
