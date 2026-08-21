import json
import tempfile
import unittest
from pathlib import Path

from gamecoin.wallet_core import (
    WalletLockedError,
    WalletPasswordError,
    change_wallet_password,
    create_wallet,
    current_receive_record,
    generate_receive_address,
    is_encrypted_wallet,
    is_wallet_locked,
    load_wallet,
    migrate_wallet_file_to_encrypted,
    private_key_for_address,
    save_encrypted_wallet,
    save_wallet,
    validate_new_password,
)


PASSWORD = 'correct horse battery staple'
NEW_PASSWORD = 'another strong wallet password'


class WalletEncryptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'wallet.wallet.json'

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_encrypted_file_has_no_plaintext_seed_or_private_key(self) -> None:
        wallet = create_wallet('encrypted-test')
        seed = wallet['master_seed']
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        raw_text = self.path.read_text(encoding='utf-8')
        raw = json.loads(raw_text)
        self.assertEqual(raw['version'], 3)
        self.assertIn('encryption', raw)
        self.assertNotIn('master_seed', raw)
        self.assertNotIn('private_key', raw)
        self.assertNotIn(seed, raw_text)
        self.assertEqual(raw['encryption']['kdf'], 'argon2id')
        self.assertEqual(raw['encryption']['cipher'], 'aes-256-gcm')

    def test_locked_wallet_can_show_address_but_cannot_sign(self) -> None:
        wallet = create_wallet('locked-test')
        address = current_receive_record(wallet)['address']
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        locked = load_wallet(str(self.path))
        self.assertTrue(is_encrypted_wallet(locked))
        self.assertTrue(is_wallet_locked(locked))
        self.assertEqual(current_receive_record(locked)['address'], address)
        with self.assertRaises(WalletLockedError):
            private_key_for_address(locked, address)

    def test_correct_password_unlocks_and_wrong_password_fails(self) -> None:
        wallet = create_wallet('password-test')
        address = current_receive_record(wallet)['address']
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        with self.assertRaises(WalletPasswordError):
            load_wallet(str(self.path), 'definitely the wrong password')
        unlocked = load_wallet(str(self.path), PASSWORD)
        self.assertEqual(current_receive_record(unlocked)['address'], address)
        private_key_for_address(unlocked, address)

    def test_public_metadata_tamper_is_detected_on_unlock(self) -> None:
        wallet = create_wallet('tamper-test')
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        raw = json.loads(self.path.read_text(encoding='utf-8'))
        raw['label'] = 'tampered-label'
        self.path.write_text(json.dumps(raw), encoding='utf-8')
        with self.assertRaises(WalletPasswordError):
            load_wallet(str(self.path), PASSWORD)

    def test_encrypted_wallet_can_add_address_and_remains_encrypted(self) -> None:
        wallet = create_wallet('address-test')
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        unlocked = load_wallet(str(self.path), PASSWORD)
        unlocked, item = generate_receive_address(unlocked, 'Second')
        save_encrypted_wallet(unlocked, str(self.path), PASSWORD)
        locked = load_wallet(str(self.path))
        self.assertEqual(len(locked['receive_addresses']), 2)
        self.assertEqual(current_receive_record(locked)['address'], item['address'])
        raw = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertNotIn('master_seed', raw)
        self.assertNotIn('private_key', raw)

    def test_change_password_preserves_wallet_identity(self) -> None:
        wallet = create_wallet('change-password')
        address = current_receive_record(wallet)['address']
        save_encrypted_wallet(wallet, str(self.path), PASSWORD)
        change_wallet_password(str(self.path), PASSWORD, NEW_PASSWORD)
        with self.assertRaises(WalletPasswordError):
            load_wallet(str(self.path), PASSWORD)
        changed = load_wallet(str(self.path), NEW_PASSWORD)
        self.assertEqual(current_receive_record(changed)['address'], address)

    def test_plaintext_wallet_migration_preserves_address_and_backup(self) -> None:
        wallet = create_wallet('migration-test')
        address = current_receive_record(wallet)['address']
        save_wallet(wallet, str(self.path))
        backup = Path(self.tmp.name) / 'legacy-backup.json'
        migrate_wallet_file_to_encrypted(str(self.path), PASSWORD, str(backup))
        self.assertTrue(backup.exists())
        self.assertIn('master_seed', json.loads(backup.read_text(encoding='utf-8')))
        locked = load_wallet(str(self.path))
        self.assertTrue(is_encrypted_wallet(locked))
        unlocked = load_wallet(str(self.path), PASSWORD)
        self.assertEqual(current_receive_record(unlocked)['address'], address)

    def test_testnet_wallet_identity_is_rejected(self) -> None:
        wallet = create_wallet('wrong-network')
        wallet['format'] = 'gamecoin-testnet-wallet'
        wallet['network'] = 'gamecoin-public-testnet-v4'
        self.path.write_text(json.dumps(wallet), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Not a GameCoin mainnet wallet file'):
            load_wallet(str(self.path))

    def test_password_policy_rejects_short_passwords(self) -> None:
        with self.assertRaises(ValueError):
            validate_new_password('short')


if __name__ == '__main__':
    unittest.main()
