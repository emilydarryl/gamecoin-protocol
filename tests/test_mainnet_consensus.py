import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import node
from gamecoin.chainwork import block_work, chain_work, target_work
from gamecoin.consensus import (
    COIN,
    COINBASE_MATURITY,
    MAX_SUPPLY,
    MAX_TX_OUTPUTS,
    block_subsidy,
    coinbase_is_mature,
)
from gamecoin.transaction_rules import expected_coinbase_value, transaction_fee
from gamecoin.utils import (
    address_from_pubkey,
    merkle_root,
    target_for_difficulty,
    tx_id,
    validate_address,
)
from gamecoin.wallet_core import create_wallet, public_key_for_address, sign_transaction_input


class MainnetConsensusTests(unittest.TestCase):
    def make_state(self):
        temp = tempfile.TemporaryDirectory()
        state = node.ChainState(str(Path(temp.name) / 'data'), str(Path(temp.name) / 'logs'))
        self.addCleanup(temp.cleanup)
        return state

    def signed_spend(self, wallet, prev_txid, prev_vout, output_address, output_amount):
        owner = wallet['address']
        tx = {
            'timestamp': int(time.time()),
            'inputs': [{
                'txid': prev_txid,
                'vout': prev_vout,
                'pubkey': public_key_for_address(wallet, owner),
                'signature': '',
            }],
            'outputs': [{'address': output_address, 'amount': output_amount}],
        }
        tx['inputs'][0]['signature'] = sign_transaction_input(tx, 0, wallet, owner)
        tx['txid'] = tx_id(tx)
        return tx

    def test_mainnet_identity(self):
        self.assertEqual(node.NETWORK_NAME, 'gamecoin-mainnet')
        self.assertEqual(node.P2P_PROTOCOL, 6)
        self.assertEqual(node.GENESIS_HASH, 'fb7282bd7a829af95ebcf32da284ab4eb2c807eb65eb6ec63aed86b9ec9a7233')

    def test_mainnet_genesis_has_no_premine(self):
        genesis = node.make_genesis()
        self.assertEqual(genesis['height'], 0)
        self.assertEqual(genesis['transactions'][0]['outputs'], [])
        self.assertEqual(node.circulating_supply(0), 0)

    def test_mempool_rejects_coinbase_before_known_txid_shortcut(self):
        state = self.make_state()
        wallet = create_wallet('miner')
        block = state.mining_template(wallet['address'])
        coinbase = block['transactions'][0]
        state.chain.append({**block, 'hash': '00' * 32})
        with self.assertRaisesRegex(ValueError, 'Coinbase transactions cannot be submitted to the mempool'):
            state.add_transaction(coinbase, source='test')

    def test_mainnet_addresses_are_distinct_from_testnet_prefix(self):
        wallet = create_wallet('mainnet-address')
        address = wallet['address']
        self.assertTrue(address.startswith('M'))
        self.assertTrue(validate_address(address))
        self.assertFalse(validate_address('G' + address[1:]))

    def test_foreign_chain_fails_closed_without_modification(self):
        import json
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        data = Path(temp.name) / 'data'
        logs = Path(temp.name) / 'logs'
        data.mkdir(parents=True)
        foreign = [{'height': 0, 'hash': '11' * 32}]
        chain_path = data / 'chain.json'
        chain_path.write_text(json.dumps(foreign), encoding='utf-8')
        before = chain_path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'does not belong to GameCoin Mainnet'):
            node.ChainState(str(data), str(logs))
        self.assertEqual(chain_path.read_bytes(), before)

    def test_integer_chainwork_exact(self):
        block = {'version': 2, 'difficulty': node.INITIAL_DIFFICULTY_UNITS}
        self.assertIsInstance(block_work(block), int)
        self.assertEqual(block_work(block), target_work(target_for_difficulty(node.INITIAL_DIFFICULTY_UNITS)))
        self.assertEqual(chain_work([{'version': 1, 'difficulty': 0}, block]), block_work(block))

    def test_coinbase_maturity_boundary(self):
        self.assertFalse(coinbase_is_mature(10, 10 + COINBASE_MATURITY - 1))
        self.assertTrue(coinbase_is_mature(10, 10 + COINBASE_MATURITY))

    def test_fee_arithmetic(self):
        self.assertEqual(transaction_fee(5 * COIN, 5 * COIN - 100_000), 100_000)
        self.assertEqual(expected_coinbase_value(1, 100_000), 5 * COIN + 100_000)
        with self.assertRaises(ValueError):
            transaction_fee(COIN, COIN + 1)

    def test_strict_address_checksum(self):
        wallet = create_wallet('test')
        address = wallet['address']
        self.assertTrue(validate_address(address))
        replacement = '1' if address[-1] != '1' else '2'
        self.assertFalse(validate_address(address[:-1] + replacement))
        self.assertFalse(validate_address('Gnot-a-real-address'))

    def test_immature_coinbase_rejected_and_mature_accepted(self):
        state = self.make_state()
        wallet = create_wallet('miner')
        destination = create_wallet('dest')['address']
        prev_txid = '11' * 32
        utxo = {
            (prev_txid, 0): {
                'address': wallet['address'],
                'amount': 5 * COIN,
                '_coinbase': True,
                '_created_height': 1,
            }
        }
        tx = self.signed_spend(wallet, prev_txid, 0, destination, 5 * COIN - 100_000)
        with self.assertRaisesRegex(ValueError, 'immature'):
            state.validate_normal_tx(tx, dict(utxo), spend_height=100)
        fee = state.validate_normal_tx(tx, dict(utxo), spend_height=101)
        self.assertEqual(fee, 100_000)

    def test_mining_template_collects_transaction_fee(self):
        state = self.make_state()
        owner = create_wallet('owner')
        miner = create_wallet('miner')
        destination = create_wallet('dest')['address']
        prev_txid = '33' * 32
        tx = self.signed_spend(owner, prev_txid, 0, destination, 5 * COIN - 100_000)
        state.mempool = [tx]
        base_utxos = {
            (prev_txid, 0): {
                'address': owner['address'],
                'amount': 5 * COIN,
                '_coinbase': False,
                '_created_height': 0,
            }
        }
        with patch.object(state, 'build_utxos', return_value=dict(base_utxos)):
            block = state.mining_template(miner['address'])
        self.assertEqual(len(block['transactions']), 2)
        self.assertEqual(block['transactions'][0]['outputs'][0]['amount'], 5 * COIN + 100_000)

    def test_resource_ceiling_rejects_too_many_outputs(self):
        state = self.make_state()
        wallet = create_wallet('owner')
        prev_txid = '22' * 32
        tx = {
            'timestamp': int(time.time()),
            'inputs': [{
                'txid': prev_txid,
                'vout': 0,
                'pubkey': public_key_for_address(wallet, wallet['address']),
                'signature': '',
            }],
            'outputs': [{'address': wallet['address'], 'amount': 1} for _ in range(MAX_TX_OUTPUTS + 1)],
        }
        tx['txid'] = tx_id(tx)
        with self.assertRaisesRegex(ValueError, 'too many outputs'):
            state.validate_normal_tx(tx, {})

    def test_mainnet_rejects_legacy_block_versions(self):
        state = self.make_state()
        wallet = create_wallet('miner')
        height = len(state.chain)
        coinbase = {
            'timestamp': node.GENESIS_TIMESTAMP + 1,
            'inputs': [],
            'outputs': [{'address': wallet['address'], 'amount': block_subsidy(height)}],
            'coinbase': f'height:{height}',
        }
        coinbase['txid'] = tx_id(coinbase)
        block = {
            'version': 1,
            'height': height,
            'prev_hash': state.tip()['hash'],
            'timestamp': node.GENESIS_TIMESTAMP + 1,
            'difficulty': 0,
            'merkle_root': merkle_root([coinbase['txid']]),
            'nonce': 0,
            'transactions': [coinbase],
        }
        with self.assertRaisesRegex(ValueError, 'Unsupported block version'):
            state._validate_block_against(block, state.chain, state.build_utxos())

    def test_valid_mainnet_block_claims_exact_subsidy(self):
        state = self.make_state()
        wallet = create_wallet('miner')
        block = state.mining_template(wallet['address'])
        with patch('node.meets_work', return_value=True):
            final = state._validate_block_against(block, state.chain, state.build_utxos())
        self.assertEqual(final['height'], 1)
        self.assertEqual(final['transactions'][0]['outputs'][0]['amount'], 5 * COIN)

    def test_greater_work_reorg_only(self):
        state = self.make_state()
        genesis = state.chain[0]
        low = {'version': 2, 'height': 1, 'difficulty': 1_000_000, 'hash': 'aa' * 32, 'transactions': []}
        high = {'version': 2, 'height': 1, 'difficulty': 2_000_000, 'hash': 'bb' * 32, 'transactions': []}
        state.chain = [genesis, low]
        with patch.object(state, 'validate_chain_candidate', return_value=[genesis, high]):
            self.assertTrue(state.replace_chain([genesis, high], source='test-peer'))
        self.assertEqual(state.tip()['hash'], high['hash'])
        with patch.object(state, 'validate_chain_candidate', return_value=[genesis, high]):
            self.assertFalse(state.replace_chain([genesis, high], source='same-tip'))

    def test_equal_or_lower_work_reorg_rejected(self):
        state = self.make_state()
        genesis = state.chain[0]
        local = {'version': 2, 'height': 1, 'difficulty': 2_000_000, 'hash': 'aa' * 32, 'transactions': []}
        equal = {'version': 2, 'height': 1, 'difficulty': 2_000_000, 'hash': 'cc' * 32, 'transactions': []}
        state.chain = [genesis, local]
        with patch.object(state, 'validate_chain_candidate', return_value=[genesis, equal]):
            with self.assertRaisesRegex(ValueError, 'does not have greater cumulative work'):
                state.replace_chain([genesis, equal], source='test-peer')

    def test_difficulty_samples_use_adjacent_timestamps_not_mtp(self):
        scale = node.DIFFICULTY_SCALE
        chain = [{'version': 1, 'height': 0, 'timestamp': 1_000_000, 'difficulty': 0}]
        timestamp = 1_000_000
        for height in range(1, 12):
            timestamp += 5
            chain.append({
                'version': 2,
                'height': height,
                'timestamp': timestamp,
                'difficulty': 1_000 * scale,
            })
        timestamp += 500
        chain.append({
            'version': 2,
            'height': 12,
            'timestamp': timestamp,
            'difficulty': 10_000 * scale,
        })
        samples = node.ChainState._recent_work_samples_for(chain)
        self.assertEqual(samples[-1][0], 500.0)
        self.assertEqual(samples[0][0], float(node.DIFFICULTY_SAMPLE_MIN_SECONDS))

    def test_difficulty_reverses_after_slow_high_work_block(self):
        scale = node.DIFFICULTY_SCALE
        chain = [{'version': 1, 'height': 0, 'timestamp': 2_000_000, 'difficulty': 0}]
        timestamp = 2_000_000
        factors = [1000, 1500, 2250, 3375, 5000, 7500, 11000, 16000, 23000, 34000, 50000]
        for height, factor in enumerate(factors, 1):
            timestamp += 8
            chain.append({
                'version': 2,
                'height': height,
                'timestamp': timestamp,
                'difficulty': factor * scale,
            })
        timestamp += 600
        current_units = 63_424 * scale
        chain.append({
            'version': 2,
            'height': 12,
            'timestamp': timestamp,
            'difficulty': current_units,
        })
        plan = node.ChainState._difficulty_plan_for(chain)
        self.assertLess(plan['desired_units'], current_units)
        self.assertLess(plan['next_units'], current_units)
        self.assertEqual(plan['status'], 'RAMPING DOWN')

    def test_difficulty_single_fast_samples_are_clamped(self):
        scale = node.DIFFICULTY_SCALE
        chain = [
            {'version': 1, 'height': 0, 'timestamp': 3_000_000, 'difficulty': 0},
            {'version': 2, 'height': 1, 'timestamp': 3_000_001, 'difficulty': 1_000 * scale},
        ]
        samples = node.ChainState._recent_work_samples_for(chain)
        self.assertEqual(samples[0][0], float(node.DIFFICULTY_SAMPLE_MIN_SECONDS))

    def test_max_supply_unchanged(self):
        self.assertEqual(MAX_SUPPLY, 2_102_399_972_668_800)


if __name__ == '__main__':
    unittest.main()
