import unittest

from gamecoin.time_rules import MAX_FUTURE_BLOCK_SECONDS, median_time_past, validate_block_timestamp


class TimeRuleTests(unittest.TestCase):
    def test_median_time_past(self):
        blocks = [{'timestamp': n} for n in [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]]
        self.assertEqual(median_time_past(blocks), 15)

    def test_requires_strictly_greater_than_mtp(self):
        blocks = [{'timestamp': n} for n in [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]]
        with self.assertRaises(ValueError):
            validate_block_timestamp(blocks, 15, now=100)
        validate_block_timestamp(blocks, 16, now=100)

    def test_future_boundary(self):
        validate_block_timestamp([], 100 + MAX_FUTURE_BLOCK_SECONDS, now=100)
        with self.assertRaises(ValueError):
            validate_block_timestamp([], 101 + MAX_FUTURE_BLOCK_SECONDS, now=100)


if __name__ == '__main__':
    unittest.main()
