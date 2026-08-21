import unittest
from unittest.mock import patch

import miner


class _Event:
    def __init__(self):
        self.value = False

    def is_set(self):
        return self.value

    def set(self):
        self.value = True


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class MinerTimestampTests(unittest.TestCase):
    def test_worker_refreshes_timestamp_during_long_work(self):
        template = {
            'version': 2,
            'height': 1,
            'prev_hash': '00' * 32,
            'timestamp': 1_000,
            'difficulty': 1,
            'merkle_root': '11' * 32,
            'nonce': 0,
            'transactions': [],
        }
        event = _Event()
        out = _Queue()
        # First nonce misses. report_every=1 refreshes nTime to 1100.
        # Second nonce succeeds and must report the refreshed timestamp.
        with patch('miner.block_hash', return_value='22' * 32), \
             patch('miner.meets_work', side_effect=[False, True]), \
             patch('miner.time.time', side_effect=[1000.0, 1100.0, 1100.1, 1100.2, 1100.3]):
            miner.worker(template, 0, 1, event, out, report_every=1)
        found = next(item for item in out.items if item[0] == 'found')
        self.assertEqual(found[3], 1100)


if __name__ == '__main__':
    unittest.main()
