"""Deterministic transaction and miner-fee accounting rules."""

from gamecoin.consensus import block_subsidy


def transaction_fee(input_total: int, output_total: int) -> int:
    inputs = int(input_total)
    outputs = int(output_total)
    if inputs < 0 or outputs < 0:
        raise ValueError('Transaction totals cannot be negative')
    if outputs > inputs:
        raise ValueError('Outputs exceed inputs')
    return inputs - outputs


def expected_coinbase_value(height: int, total_fees: int) -> int:
    fees = int(total_fees)
    if fees < 0:
        raise ValueError('Transaction fees cannot be negative')
    return block_subsidy(int(height)) + fees
