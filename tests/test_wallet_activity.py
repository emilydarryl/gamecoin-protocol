import unittest
from unittest.mock import patch

import wallet_gui


class WalletActivityTests(unittest.TestCase):
    def test_fee_bearing_mining_reward_uses_authoritative_block_detail(self):
        address = 'GCMDbD64cg28UKdWyNsbFpqwRvGTdUzTyv'
        listed = {
            'height': 101,
            'hash': 'abc',
            'timestamp': 1000,
            'transactions': [
                {
                    'coinbase': 101,
                    'txid': 'coinbase101',
                    'timestamp': 1000,
                    'outputs': [{'address': address, 'amount': 500_000_000}],
                },
                {'txid': 'normal', 'timestamp': 999, 'inputs': [], 'outputs': []},
            ],
        }
        authoritative = {
            **listed,
            'transactions': [
                {
                    'coinbase': 101,
                    'txid': 'coinbase101',
                    'timestamp': 1000,
                    'outputs': [{'address': address, 'amount': 500_100_000}],
                },
                listed['transactions'][1],
            ],
        }

        def fake_request(_base, path, **_kwargs):
            self.assertEqual(path, '/block/101')
            return {'ok': True, 'block': authoritative}

        with patch.object(wallet_gui, 'request_json', side_effect=fake_request):
            result = wallet_gui._authoritative_activity_block(listed, {address})

        row = wallet_gui._activity_row_for_tx(
            result['transactions'][0], {address}, 'Confirmed', 101, 1, result['timestamp']
        )
        self.assertIsNotNone(row)
        self.assertEqual(row['type'], 'Mining reward')
        self.assertEqual(row['amount'], 500_100_000)
        self.assertEqual(wallet_gui.format_amount(row['amount']), '5.00100000')

    def test_non_fee_block_does_not_add_detail_rpc(self):
        address = 'GCMDbD64cg28UKdWyNsbFpqwRvGTdUzTyv'
        block = {
            'height': 100,
            'hash': 'def',
            'transactions': [{
                'coinbase': 100,
                'outputs': [{'address': address, 'amount': 500_000_000}],
            }],
        }
        with patch.object(wallet_gui, 'request_json') as request:
            result = wallet_gui._authoritative_activity_block(block, {address})
        self.assertIs(result, block)
        request.assert_not_called()


if __name__ == '__main__':
    unittest.main()


class EncryptedWalletGuiTransactionTests(unittest.TestCase):
    def test_encrypted_wallet_send_unlocks_signs_and_stays_encrypted(self):
        import json
        import tempfile
        from pathlib import Path
        from urllib.parse import quote
        from gamecoin.wallet_core import create_wallet, current_receive_record, save_encrypted_wallet

        password = 'correct horse battery staple'
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'wallet.wallet.json'
            wallet = create_wallet('gui-send')
            owner = current_receive_record(wallet)['address']
            destination = current_receive_record(create_wallet('dest'))['address']
            save_encrypted_wallet(wallet, str(path), password)
            submitted = {}

            def fake_request(_base, rpc_path, method='GET', body=None, **_kwargs):
                if rpc_path == '/utxos/' + quote(owner):
                    return {'utxos': [{
                        'txid': '11' * 32,
                        'vout': 0,
                        'amount': 200_000_000,
                        'spendable': True,
                    }]}
                if rpc_path.startswith('/utxos/'):
                    return {'utxos': []}
                if rpc_path == '/tx' and method == 'POST':
                    submitted['tx'] = body['tx']
                    return {'txid': body['tx']['txid']}
                raise AssertionError(f'unexpected RPC {method} {rpc_path}')

            with patch.object(wallet_gui, 'request_json', side_effect=fake_request):
                tid = wallet_gui.build_and_submit_transaction(path, destination, '0.25', password)

            self.assertEqual(tid, submitted['tx']['txid'])
            self.assertTrue(submitted['tx']['inputs'][0]['signature'])
            self.assertEqual(submitted['tx']['outputs'][0]['amount'], 25_000_000)
            raw = json.loads(path.read_text(encoding='utf-8'))
            self.assertNotIn('master_seed', raw)
            self.assertNotIn('private_key', raw)
            self.assertEqual(len(raw['change_addresses']), 1)

    def test_encrypted_wallet_send_rejects_wrong_password_before_rpc(self):
        import tempfile
        from pathlib import Path
        from gamecoin.wallet_core import WalletPasswordError, create_wallet, current_receive_record, save_encrypted_wallet

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'wallet.wallet.json'
            wallet = create_wallet('gui-send')
            destination = current_receive_record(create_wallet('dest'))['address']
            save_encrypted_wallet(wallet, str(path), 'correct horse battery staple')
            with patch.object(wallet_gui, 'request_json') as request:
                with self.assertRaises(WalletPasswordError):
                    wallet_gui.build_and_submit_transaction(path, destination, '0.25', 'wrong password but long enough')
            request.assert_not_called()
