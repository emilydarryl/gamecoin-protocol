"""Consensus timestamp rules for GameCoin Mainnet v1.0.0."""

from statistics import median
from time import time
from typing import Any, Dict, Iterable, Optional

MEDIAN_TIME_WINDOW = 11
MAX_FUTURE_BLOCK_SECONDS = 2 * 60 * 60


def median_time_past(blocks: Iterable[Dict[str, Any]], window: int = MEDIAN_TIME_WINDOW) -> int:
    values = [int(block['timestamp']) for block in list(blocks)[-max(1, int(window)):]]
    if not values:
        return 0
    return int(median(values))


def validate_block_timestamp(
    previous_blocks: Iterable[Dict[str, Any]],
    candidate_timestamp: int,
    *,
    now: Optional[int] = None,
) -> None:
    timestamp = int(candidate_timestamp)
    history = list(previous_blocks)
    if history:
        mtp = median_time_past(history)
        if timestamp <= mtp:
            raise ValueError(f'Block timestamp must be greater than median time past ({mtp})')
    current_time = int(time()) if now is None else int(now)
    maximum = current_time + MAX_FUTURE_BLOCK_SECONDS
    if timestamp > maximum:
        raise ValueError(f'Block timestamp is too far in the future (max {maximum})')
