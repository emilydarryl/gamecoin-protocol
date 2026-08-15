"""Deterministic transaction and miner-fee accounting rules."""

from gamecoin.consensus import block_subsidy


def transaction_fee(input_total: int, output_total: int) -> int:
    """Return the implicit transaction fee in atoms.

    GameCoin uses the standard UTXO convention: fees are not a separate
    transaction field. The fee is the sum of referenced inputs minus the sum
    of newly created outputs.
    """
    inputs = int(input_total)
    outputs = int(output_total)
    if inputs < 0 or outputs < 0:
        raise ValueError('Transaction totals cannot be negative')
    if outputs > inputs:
        raise ValueError('Outputs exceed inputs')
    return inputs - outputs


def expected_coinbase_value(height: int, total_fees: int) -> int:
    """Return the exact coinbase value required for a candidate block."""
    fees = int(total_fees)
    if fees < 0:
        raise ValueError('Transaction fees cannot be negative')
    return block_subsidy(int(height)) + fees
