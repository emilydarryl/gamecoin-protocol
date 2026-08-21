"""Deterministic integer proof-of-work accounting for GameCoin."""

from typing import Any, Dict, Iterable

from gamecoin.utils import MAX_HASH_INT, target_for_difficulty

UINT256_SPACE = 1 << 256


def target_work(target: int) -> int:
    value = int(target)
    if value < 0 or value > MAX_HASH_INT:
        raise ValueError('Target is outside the 256-bit proof-of-work range')
    return UINT256_SPACE // (value + 1)


def block_work(block: Dict[str, Any]) -> int:
    version = int(block.get('version', 1))
    difficulty = int(block.get('difficulty', 0))
    if version <= 1:
        if difficulty < 0 or difficulty > 64:
            raise ValueError('Legacy difficulty is outside the valid range')
        return 16 ** difficulty
    return target_work(target_for_difficulty(difficulty))


def chain_work(blocks: Iterable[Dict[str, Any]], *, include_genesis: bool = False) -> int:
    total = 0
    for index, block in enumerate(blocks):
        if index == 0 and not include_genesis:
            continue
        total += block_work(block)
    return total
