import unittest

from gamecoin.time_rules import MAX_FUTURE_BLOCK_SECONDS, median_time_past, validate_block_timestamp


class TimestampRuleTests(unittest.TestCase):
    def test_median_time_past_uses_recent_window(self):
        blocks = [{'timestamp': value} for value in range(1, 15)]
        self.assertEqual(median_time_past(blocks), 9)

    def test_timestamp_must_be_strictly_greater_than_mtp(self):
        blocks = [{'timestamp': value} for value in range(100, 111)]
        mtp = median_time_past(blocks)
        with self.assertRaises(ValueError):
            validate_block_timestamp(blocks, mtp, now=10_000)
        validate_block_timestamp(blocks, mtp + 1, now=10_000)

    def test_future_limit(self):
        now = 1_000_000
        validate_block_timestamp([], now + MAX_FUTURE_BLOCK_SECONDS, now=now)
        with self.assertRaises(ValueError):
            validate_block_timestamp([], now + MAX_FUTURE_BLOCK_SECONDS + 1, now=now)


if __name__ == '__main__':
    unittest.main()
