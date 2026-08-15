import unittest

from gamecoin.consensus import COIN, COINBASE_MATURITY, block_subsidy, coinbase_is_mature
from gamecoin.policy import DEFAULT_TRANSACTION_FEE
from gamecoin.transaction_rules import expected_coinbase_value, transaction_fee


class TransactionRuleTests(unittest.TestCase):
    def test_coinbase_requires_100_blocks_of_maturity(self):
        created = 25
        self.assertFalse(coinbase_is_mature(created, created + COINBASE_MATURITY - 1))
        self.assertTrue(coinbase_is_mature(created, created + COINBASE_MATURITY))

    def test_fee_is_inputs_minus_outputs(self):
        self.assertEqual(transaction_fee(2 * COIN, 2 * COIN - 123_456), 123_456)

    def test_zero_fee_is_consensus_valid(self):
        self.assertEqual(transaction_fee(COIN, COIN), 0)

    def test_outputs_cannot_exceed_inputs(self):
        with self.assertRaisesRegex(ValueError, 'Outputs exceed inputs'):
            transaction_fee(COIN, COIN + 1)

    def test_coinbase_value_is_subsidy_plus_all_transaction_fees(self):
        height = 42
        fees = 3 * DEFAULT_TRANSACTION_FEE
        self.assertEqual(expected_coinbase_value(height, fees), block_subsidy(height) + fees)

    def test_default_wallet_fee_is_point_zero_zero_one_game(self):
        self.assertEqual(DEFAULT_TRANSACTION_FEE, 100_000)


if __name__ == '__main__':
    unittest.main()
