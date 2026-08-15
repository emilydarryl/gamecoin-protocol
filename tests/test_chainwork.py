import unittest

from gamecoin.chainwork import block_work, chain_work, target_work
from gamecoin.utils import DIFFICULTY_SCALE, MAX_HASH_INT, target_for_difficulty


class ChainworkTests(unittest.TestCase):
    def test_max_target_has_one_unit_of_work(self):
        self.assertEqual(target_work(MAX_HASH_INT), 1)

    def test_v2_work_increases_with_difficulty(self):
        low = {'version': 2, 'difficulty': 1 * DIFFICULTY_SCALE}
        high = {'version': 2, 'difficulty': 1000 * DIFFICULTY_SCALE}
        self.assertGreater(block_work(high), block_work(low))

    def test_v2_work_matches_target_formula(self):
        block = {'version': 2, 'difficulty': 13725 * DIFFICULTY_SCALE}
        expected = (1 << 256) // (target_for_difficulty(block['difficulty']) + 1)
        self.assertEqual(block_work(block), expected)

    def test_legacy_work_is_exact_power_of_sixteen(self):
        self.assertEqual(block_work({'version': 1, 'difficulty': 0}), 1)
        self.assertEqual(block_work({'version': 1, 'difficulty': 3}), 4096)

    def test_chain_work_skips_genesis_by_default(self):
        blocks = [
            {'version': 1, 'difficulty': 0},
            {'version': 1, 'difficulty': 3},
            {'version': 1, 'difficulty': 4},
        ]
        self.assertEqual(chain_work(blocks), 4096 + 65536)


if __name__ == '__main__':
    unittest.main()
