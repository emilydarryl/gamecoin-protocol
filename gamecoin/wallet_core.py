import base64
import hashlib
import hmac
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .network import NETWORK_NAME
from .utils import address_from_pubkey, canonical_json, validate_address

# Version 3 stores the wallet seed only inside an Argon2id + AES-256-GCM
# authenticated-encryption envelope. Version 2 is the previous plaintext HD
# wallet storage design; mainnet intentionally uses a separate file/network identity.
WALLET_VERSION = 3
PLAINTEXT_WALLET_VERSION = 2
WALLET_FORMAT = 'gamecoin-mainnet-wallet'
LEGACY_NETWORKS = set()
HD_DOMAIN = b'GameCoin-HD-Wallet-v1'
BRANCH_CODES = {'receive': 0, 'change': 1, 'mining': 2}

ENCRYPTION_SCHEME = 'argon2id-aes-256-gcm-v1'
KDF_NAME = 'argon2id'
CIPHER_NAME = 'aes-256-gcm'
KDF_MEMORY_KIB = 64 * 1024
KDF_ITERATIONS = 3
KDF_LANES = 4
KDF_KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
MIN_PASSWORD_LENGTH = 12


class WalletLockedError(ValueError):
    pass


class WalletPasswordError(ValueError):
    pass


def validate_new_password(password: str) -> None:
    if not isinstance(password, str):
        raise ValueError('Wallet password must be text')
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f'Wallet password must be at least {MIN_PASSWORD_LENGTH} characters')
    if len(password.encode('utf-8')) > 1024:
        raise ValueError('Wallet password is too long')


def _master_seed_bytes(wallet: Dict[str, Any]) -> bytes:
    value = wallet.get('master_seed') or wallet.get('private_key')
    if not isinstance(value, str):
        if is_encrypted_wallet(wallet):
            raise WalletLockedError('Wallet is locked. Enter the wallet password to use private keys.')
        raise ValueError('Wallet master seed is missing')
    try:
        seed = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError('Wallet master seed is not valid hexadecimal') from exc
    if len(seed) != 32:
        raise ValueError('Wallet master seed must be 32 bytes')
    return seed


def _derive_private_seed(master_seed: bytes, branch: str, index: int) -> bytes:
    if branch not in BRANCH_CODES:
        raise ValueError(f'Unknown wallet branch: {branch}')
    if index < 0 or index > 0x7FFFFFFF:
        raise ValueError('Wallet address index is out of range')
    if branch == 'receive' and index == 0:
        return master_seed
    msg = HD_DOMAIN + bytes([BRANCH_CODES[branch]]) + int(index).to_bytes(8, 'big')
    return hmac.new(master_seed, msg, hashlib.sha512).digest()[:32]


def _record(master_seed: bytes, branch: str, index: int, label: str = '') -> Dict[str, Any]:
    private_seed = _derive_private_seed(master_seed, branch, index)
    private = Ed25519PrivateKey.from_private_bytes(private_seed)
    public_raw = private.public_key().public_bytes_raw()
    return {
        'branch': branch,
        'index': int(index),
        'label': str(label or ''),
        'address': address_from_pubkey(public_raw),
        'public_key': public_raw.hex(),
    }


def _base_wallet(master_seed: bytes, label: str = '') -> Dict[str, Any]:
    receive0 = _record(master_seed, 'receive', 0, 'Default')
    mining0 = _record(master_seed, 'mining', 0, 'Mining rewards')
    return {
        'format': WALLET_FORMAT,
        'version': PLAINTEXT_WALLET_VERSION,
        'network': NETWORK_NAME,
        'label': str(label or ''),
        'master_seed': master_seed.hex(),
        'receive_addresses': [receive0],
        'change_addresses': [],
        'mining_addresses': [mining0],
        'next_receive_index': 1,
        'next_change_index': 0,
        'next_mining_index': 1,
        'current_receive_index': 0,
        'current_mining_index': 0,
        'warning': 'MAINNET LEGACY-PLAINTEXT WALLET. Private seed is plaintext until this wallet is encrypted.',
        # Compatibility aliases used by older v4 tools. They are never written
        # outside the encrypted envelope by the v3 storage format.
        'address': receive0['address'],
        'public_key': receive0['public_key'],
        'private_key': master_seed.hex(),
    }


def create_wallet(label: str = '') -> Dict[str, Any]:
    private = Ed25519PrivateKey.generate()
    return _base_wallet(private.private_bytes_raw(), label)


def _validate_network(wallet: Dict[str, Any]) -> None:
    if wallet.get('format') != WALLET_FORMAT:
        raise ValueError('Not a GameCoin mainnet wallet file')
    wallet_network = str(wallet.get('network', '') or '')
    if wallet_network and wallet_network != NETWORK_NAME and wallet_network not in LEGACY_NETWORKS:
        raise ValueError(f'Wallet belongs to an unsupported GameCoin network: {wallet_network}')


def _verify_record(master_seed: bytes, raw: Dict[str, Any], expected_branch: str) -> Dict[str, Any]:
    branch = str(raw.get('branch', expected_branch))
    if branch != expected_branch:
        raise ValueError('Wallet address branch mismatch')
    index = int(raw.get('index', -1))
    expected = _record(master_seed, branch, index, str(raw.get('label', '')))
    if raw.get('address') != expected['address']:
        raise ValueError('Wallet derived address mismatch')
    if raw.get('public_key') != expected['public_key']:
        raise ValueError('Wallet derived public key mismatch')
    return expected


def _verify_public_record(raw: Dict[str, Any], expected_branch: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError('Invalid wallet address entry')
    branch = str(raw.get('branch', expected_branch))
    if branch != expected_branch:
        raise ValueError('Wallet address branch mismatch')
    index = int(raw.get('index', -1))
    if index < 0 or index > 0x7FFFFFFF:
        raise ValueError('Wallet address index is out of range')
    address = str(raw.get('address', ''))
    public_key = str(raw.get('public_key', ''))
    if not validate_address(address):
        raise ValueError('Wallet contains an invalid GameCoin address')
    try:
        public_raw = bytes.fromhex(public_key)
    except ValueError as exc:
        raise ValueError('Wallet public key is not valid hexadecimal') from exc
    if len(public_raw) != 32:
        raise ValueError('Wallet public key must be 32 bytes')
    if address_from_pubkey(public_raw) != address:
        raise ValueError('Wallet address does not match public key')
    return {
        'branch': branch,
        'index': index,
        'label': str(raw.get('label', '') or ''),
        'address': address,
        'public_key': public_key.lower(),
    }


def _upgrade_legacy_wallet(wallet: Dict[str, Any]) -> Dict[str, Any]:
    private_raw = bytes.fromhex(str(wallet['private_key']))
    if len(private_raw) != 32:
        raise ValueError('Legacy wallet private key must be 32 bytes')
    private = Ed25519PrivateKey.from_private_bytes(private_raw)
    derived_public = private.public_key().public_bytes_raw().hex()
    if derived_public != wallet.get('public_key'):
        raise ValueError('Wallet private/public key mismatch')
    if address_from_pubkey(bytes.fromhex(derived_public)) != wallet.get('address'):
        raise ValueError('Wallet address does not match public key')
    upgraded = _base_wallet(private_raw, str(wallet.get('label', '')))
    if upgraded['address'] != wallet.get('address'):
        raise ValueError('Legacy wallet migration would change the original address')
    return upgraded


def _normalize_plain_wallet(wallet: Dict[str, Any]) -> Dict[str, Any]:
    _validate_network(wallet)
    version = int(wallet.get('version', 1))
    if version <= 1:
        return _upgrade_legacy_wallet(wallet)
    if version != PLAINTEXT_WALLET_VERSION:
        raise ValueError(f'Unsupported plaintext GameCoin wallet version: {version}')

    seed = _master_seed_bytes(wallet)
    normalized = _base_wallet(seed, str(wallet.get('label', '')))
    for field, branch in (
        ('receive_addresses', 'receive'),
        ('change_addresses', 'change'),
        ('mining_addresses', 'mining'),
    ):
        raw_items = wallet.get(field, [])
        if not isinstance(raw_items, list):
            raise ValueError(f'Wallet {field} must be a list')
        verified: List[Dict[str, Any]] = []
        seen = set()
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ValueError(f'Invalid entry in {field}')
            item = _verify_record(seed, raw, branch)
            key = int(item['index'])
            if key in seen:
                raise ValueError(f'Duplicate {branch} address index')
            seen.add(key)
            verified.append(item)
        verified.sort(key=lambda x: int(x['index']))
        normalized[field] = verified

    if not normalized['receive_addresses']:
        normalized['receive_addresses'] = [_record(seed, 'receive', 0, 'Default')]
    if not normalized['mining_addresses']:
        normalized['mining_addresses'] = [_record(seed, 'mining', 0, 'Mining rewards')]

    max_receive = max(int(x['index']) for x in normalized['receive_addresses'])
    max_change = max((int(x['index']) for x in normalized['change_addresses']), default=-1)
    max_mining = max(int(x['index']) for x in normalized['mining_addresses'])
    normalized['next_receive_index'] = max(max_receive + 1, int(wallet.get('next_receive_index', max_receive + 1)))
    normalized['next_change_index'] = max(max_change + 1, int(wallet.get('next_change_index', max_change + 1)))
    normalized['next_mining_index'] = max(max_mining + 1, int(wallet.get('next_mining_index', max_mining + 1)))
    normalized['current_receive_index'] = int(wallet.get('current_receive_index', max_receive))
    normalized['current_mining_index'] = int(wallet.get('current_mining_index', 0))
    if not any(int(x['index']) == normalized['current_receive_index'] for x in normalized['receive_addresses']):
        normalized['current_receive_index'] = max_receive
    if not any(int(x['index']) == normalized['current_mining_index'] for x in normalized['mining_addresses']):
        normalized['current_mining_index'] = int(normalized['mining_addresses'][0]['index'])
    normalized['warning'] = str(wallet.get('warning', normalized['warning']))
    default = next((x for x in normalized['receive_addresses'] if int(x['index']) == 0), normalized['receive_addresses'][0])
    normalized['address'] = default['address']
    normalized['public_key'] = default['public_key']
    normalized['private_key'] = seed.hex()
    # Preserve internal metadata for an encrypted wallet that was unlocked in
    # memory. Internal keys are never serialized directly.
    if isinstance(wallet.get('_encrypted_storage'), dict):
        normalized['_encrypted_storage'] = dict(wallet['_encrypted_storage'])
    return normalized


def _validate_encryption_block(enc: Any) -> Dict[str, Any]:
    if not isinstance(enc, dict):
        raise ValueError('Encrypted wallet is missing its encryption metadata')
    if enc.get('scheme') != ENCRYPTION_SCHEME:
        raise ValueError(f'Unsupported wallet encryption scheme: {enc.get("scheme")}')
    if enc.get('kdf') != KDF_NAME or enc.get('cipher') != CIPHER_NAME:
        raise ValueError('Unsupported wallet KDF or cipher')
    iterations = int(enc.get('iterations', 0))
    lanes = int(enc.get('lanes', 0))
    memory_cost = int(enc.get('memory_cost_kib', 0))
    if iterations < 1 or iterations > 20:
        raise ValueError('Encrypted wallet Argon2 iteration count is out of range')
    if lanes < 1 or lanes > 16:
        raise ValueError('Encrypted wallet Argon2 lane count is out of range')
    if memory_cost < 8 * 1024 or memory_cost > 2 * 1024 * 1024:
        raise ValueError('Encrypted wallet Argon2 memory cost is out of range')
    try:
        salt = base64.b64decode(str(enc.get('salt', '')), validate=True)
        nonce = base64.b64decode(str(enc.get('nonce', '')), validate=True)
        ciphertext = base64.b64decode(str(enc.get('ciphertext', '')), validate=True)
    except Exception as exc:
        raise ValueError('Encrypted wallet contains invalid base64 data') from exc
    if len(salt) < 16 or len(salt) > 64:
        raise ValueError('Encrypted wallet salt length is invalid')
    if len(nonce) != NONCE_BYTES:
        raise ValueError('Encrypted wallet AES-GCM nonce must be 12 bytes')
    if len(ciphertext) < 16:
        raise ValueError('Encrypted wallet ciphertext is too short')
    return {
        'scheme': ENCRYPTION_SCHEME,
        'kdf': KDF_NAME,
        'cipher': CIPHER_NAME,
        'iterations': iterations,
        'lanes': lanes,
        'memory_cost_kib': memory_cost,
        'salt': str(enc['salt']),
        'nonce': str(enc['nonce']),
        'ciphertext': str(enc['ciphertext']),
    }


def _normalize_encrypted_wallet(wallet: Dict[str, Any]) -> Dict[str, Any]:
    _validate_network(wallet)
    if int(wallet.get('version', 0)) != WALLET_VERSION:
        raise ValueError(f'Unsupported encrypted GameCoin wallet version: {wallet.get("version")}')
    if 'master_seed' in wallet or 'private_key' in wallet:
        raise ValueError('Encrypted wallet must not contain plaintext private key material')
    wallet_id = str(wallet.get('wallet_id', '')).lower()
    try:
        wallet_id_raw = bytes.fromhex(wallet_id)
    except ValueError as exc:
        raise ValueError('Encrypted wallet ID is invalid') from exc
    if len(wallet_id_raw) != 16:
        raise ValueError('Encrypted wallet ID must be 16 bytes')
    enc = _validate_encryption_block(wallet.get('encryption'))

    normalized: Dict[str, Any] = {
        'format': WALLET_FORMAT,
        'version': WALLET_VERSION,
        'network': str(wallet.get('network') or NETWORK_NAME),
        'wallet_id': wallet_id,
        'label': str(wallet.get('label', '') or ''),
        'receive_addresses': [],
        'change_addresses': [],
        'mining_addresses': [],
        'encryption': enc,
    }
    for field, branch in (
        ('receive_addresses', 'receive'),
        ('change_addresses', 'change'),
        ('mining_addresses', 'mining'),
    ):
        raw_items = wallet.get(field, [])
        if not isinstance(raw_items, list):
            raise ValueError(f'Wallet {field} must be a list')
        seen = set()
        items: List[Dict[str, Any]] = []
        for raw in raw_items:
            item = _verify_public_record(raw, branch)
            if item['index'] in seen:
                raise ValueError(f'Duplicate {branch} address index')
            seen.add(item['index'])
            items.append(item)
        items.sort(key=lambda x: int(x['index']))
        normalized[field] = items

    if not normalized['receive_addresses'] or not normalized['mining_addresses']:
        raise ValueError('Encrypted wallet must contain public receive and mining addresses')
    max_receive = max(int(x['index']) for x in normalized['receive_addresses'])
    max_change = max((int(x['index']) for x in normalized['change_addresses']), default=-1)
    max_mining = max(int(x['index']) for x in normalized['mining_addresses'])
    normalized['next_receive_index'] = max(max_receive + 1, int(wallet.get('next_receive_index', max_receive + 1)))
    normalized['next_change_index'] = max(max_change + 1, int(wallet.get('next_change_index', max_change + 1)))
    normalized['next_mining_index'] = max(max_mining + 1, int(wallet.get('next_mining_index', max_mining + 1)))
    normalized['current_receive_index'] = int(wallet.get('current_receive_index', max_receive))
    normalized['current_mining_index'] = int(wallet.get('current_mining_index', 0))
    if not any(int(x['index']) == normalized['current_receive_index'] for x in normalized['receive_addresses']):
        normalized['current_receive_index'] = max_receive
    if not any(int(x['index']) == normalized['current_mining_index'] for x in normalized['mining_addresses']):
        normalized['current_mining_index'] = int(normalized['mining_addresses'][0]['index'])
    normalized['warning'] = 'MAINNET ENCRYPTED WALLET. Password required for signing and deterministic address generation.'
    default = next((x for x in normalized['receive_addresses'] if int(x['index']) == 0), normalized['receive_addresses'][0])
    normalized['address'] = default['address']
    normalized['public_key'] = default['public_key']
    normalized['_locked'] = True
    return normalized


def normalize_wallet(wallet: Dict[str, Any]) -> Dict[str, Any]:
    _validate_network(wallet)
    version = int(wallet.get('version', 1))
    if version == WALLET_VERSION and isinstance(wallet.get('encryption'), dict):
        return _normalize_encrypted_wallet(wallet)
    return _normalize_plain_wallet(wallet)


def is_encrypted_wallet(wallet: Dict[str, Any]) -> bool:
    return bool(
        (int(wallet.get('version', 0) or 0) == WALLET_VERSION and isinstance(wallet.get('encryption'), dict))
        or isinstance(wallet.get('_encrypted_storage'), dict)
    )


def is_wallet_locked(wallet: Dict[str, Any]) -> bool:
    return bool(is_encrypted_wallet(wallet) and not isinstance(wallet.get('master_seed'), str))


def _public_metadata(wallet: Dict[str, Any]) -> Dict[str, Any]:
    # Current receive/mining selection is intentionally excluded so the user can
    # switch which already-derived address is displayed without decrypting and
    # rewriting the secret envelope. Address lists/counters are authenticated.
    return {
        'format': WALLET_FORMAT,
        'network': str(wallet.get('network') or NETWORK_NAME),
        'label': str(wallet.get('label', '') or ''),
        'receive_addresses': list(wallet.get('receive_addresses', [])),
        'change_addresses': list(wallet.get('change_addresses', [])),
        'mining_addresses': list(wallet.get('mining_addresses', [])),
        'next_receive_index': int(wallet.get('next_receive_index', 0)),
        'next_change_index': int(wallet.get('next_change_index', 0)),
        'next_mining_index': int(wallet.get('next_mining_index', 0)),
    }


def _public_metadata_hash(wallet: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_public_metadata(wallet))).hexdigest()


def _aad(wallet_id: str) -> bytes:
    return canonical_json({
        'format': WALLET_FORMAT,
        'version': WALLET_VERSION,
        'network': NETWORK_NAME,
        'wallet_id': wallet_id,
        'scheme': ENCRYPTION_SCHEME,
    })


def _derive_encryption_key(password: str, salt: bytes, iterations: int, lanes: int, memory_cost_kib: int) -> bytes:
    if not isinstance(password, str) or password == '':
        raise WalletPasswordError('Wallet password is required')
    kdf = Argon2id(
        salt=salt,
        length=KDF_KEY_BYTES,
        iterations=int(iterations),
        lanes=int(lanes),
        memory_cost=int(memory_cost_kib),
        ad=None,
        secret=None,
    )
    return kdf.derive(password.encode('utf-8'))


def _storage_from_plain(wallet: Dict[str, Any], wallet_id: str, encryption: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_plain_wallet(wallet)
    return {
        'format': WALLET_FORMAT,
        'version': WALLET_VERSION,
        'network': NETWORK_NAME,
        'wallet_id': wallet_id,
        'label': normalized['label'],
        'receive_addresses': normalized['receive_addresses'],
        'change_addresses': normalized['change_addresses'],
        'mining_addresses': normalized['mining_addresses'],
        'next_receive_index': normalized['next_receive_index'],
        'next_change_index': normalized['next_change_index'],
        'next_mining_index': normalized['next_mining_index'],
        'current_receive_index': normalized['current_receive_index'],
        'current_mining_index': normalized['current_mining_index'],
        'warning': 'MAINNET ENCRYPTED WALLET. Password required for signing and deterministic address generation.',
        'address': normalized['address'],
        'public_key': normalized['public_key'],
        'encryption': encryption,
    }


def _write_json_atomic(data: Dict[str, Any], path: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({k: v for k, v in data.items() if not str(k).startswith('_')}, f, indent=2, sort_keys=True)
        f.write('\n')
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def save_wallet(wallet: Dict[str, Any], path: str) -> None:
    """Save a legacy plaintext wallet or a locked wallet's display selection.

    New v1.0.0 wallets should use save_encrypted_wallet(). This function is
    retained for compatibility with consensus tests and older tooling.
    """
    if int(wallet.get('version', 0) or 0) == WALLET_VERSION and isinstance(wallet.get('encryption'), dict):
        save_locked_wallet(wallet, path)
        return
    if isinstance(wallet.get('_encrypted_storage'), dict):
        raise WalletPasswordError('Encrypted wallet changes must be saved with its password')
    normalized = _normalize_plain_wallet(wallet)
    _write_json_atomic(normalized, path)


def save_locked_wallet(wallet: Dict[str, Any], path: str) -> None:
    normalized = _normalize_encrypted_wallet(wallet)
    p = Path(path)
    if not p.exists():
        raise ValueError('Cannot create an encrypted wallet without encrypting its private seed')
    with open(p, 'r', encoding='utf-8') as f:
        original_raw = json.load(f)
    original = _normalize_encrypted_wallet(original_raw)
    if _public_metadata(original) != _public_metadata(normalized):
        raise WalletLockedError('Unlock the wallet before changing derived addresses or wallet metadata')
    # Only the already-derived address selection may change while locked.
    original_raw['current_receive_index'] = normalized['current_receive_index']
    original_raw['current_mining_index'] = normalized['current_mining_index']
    _write_json_atomic(original_raw, path)


def save_encrypted_wallet(wallet: Dict[str, Any], path: str, password: str) -> None:
    validate_new_password(password)
    normalized = _normalize_plain_wallet(wallet)
    source_meta = wallet.get('_encrypted_storage') if isinstance(wallet.get('_encrypted_storage'), dict) else {}
    wallet_id = str(source_meta.get('wallet_id') or os.urandom(16).hex())
    iterations = int(source_meta.get('iterations', KDF_ITERATIONS))
    lanes = int(source_meta.get('lanes', KDF_LANES))
    memory_cost = int(source_meta.get('memory_cost_kib', KDF_MEMORY_KIB))
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    placeholder_enc = {
        'scheme': ENCRYPTION_SCHEME,
        'kdf': KDF_NAME,
        'cipher': CIPHER_NAME,
        'iterations': iterations,
        'lanes': lanes,
        'memory_cost_kib': memory_cost,
        'salt': '',
        'nonce': '',
        'ciphertext': '',
    }
    storage = _storage_from_plain(normalized, wallet_id, placeholder_enc)
    payload = canonical_json({
        'master_seed': _master_seed_bytes(normalized).hex(),
        'public_metadata_sha256': _public_metadata_hash(storage),
    })
    key = _derive_encryption_key(password, salt, iterations, lanes, memory_cost)
    ciphertext = AESGCM(key).encrypt(nonce, payload, _aad(wallet_id))
    storage['encryption'] = {
        'scheme': ENCRYPTION_SCHEME,
        'kdf': KDF_NAME,
        'cipher': CIPHER_NAME,
        'iterations': iterations,
        'lanes': lanes,
        'memory_cost_kib': memory_cost,
        'salt': base64.b64encode(salt).decode('ascii'),
        'nonce': base64.b64encode(nonce).decode('ascii'),
        'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
    }
    _write_json_atomic(storage, path)


def unlock_wallet(wallet: Dict[str, Any], password: str) -> Dict[str, Any]:
    locked = _normalize_encrypted_wallet(wallet)
    enc = locked['encryption']
    salt = base64.b64decode(enc['salt'])
    nonce = base64.b64decode(enc['nonce'])
    ciphertext = base64.b64decode(enc['ciphertext'])
    try:
        key = _derive_encryption_key(password, salt, enc['iterations'], enc['lanes'], enc['memory_cost_kib'])
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _aad(locked['wallet_id']))
    except (InvalidTag, WalletPasswordError) as exc:
        raise WalletPasswordError('Incorrect wallet password or encrypted wallet data is corrupted') from exc
    try:
        secret = json.loads(plaintext.decode('utf-8'))
    except Exception as exc:
        raise WalletPasswordError('Encrypted wallet payload is corrupted') from exc
    if not isinstance(secret, dict):
        raise WalletPasswordError('Encrypted wallet payload is invalid')
    seed_hex = secret.get('master_seed')
    if not isinstance(seed_hex, str):
        raise WalletPasswordError('Encrypted wallet seed is missing')
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise WalletPasswordError('Encrypted wallet seed is invalid') from exc
    if len(seed) != 32:
        raise WalletPasswordError('Encrypted wallet seed has invalid length')
    expected_meta_hash = str(secret.get('public_metadata_sha256', ''))
    if not hmac.compare_digest(expected_meta_hash, _public_metadata_hash(locked)):
        raise WalletPasswordError('Wallet public metadata was modified or is corrupted')

    plain = _base_wallet(seed, locked['label'])
    for field in (
        'receive_addresses', 'change_addresses', 'mining_addresses',
        'next_receive_index', 'next_change_index', 'next_mining_index',
        'current_receive_index', 'current_mining_index',
    ):
        plain[field] = locked[field]
    plain = _normalize_plain_wallet(plain)
    # This marker causes future encrypted saves to preserve the same wallet ID
    # and KDF work factor while rotating salt/nonce/ciphertext.
    plain['_encrypted_storage'] = {
        'wallet_id': locked['wallet_id'],
        'iterations': int(enc['iterations']),
        'lanes': int(enc['lanes']),
        'memory_cost_kib': int(enc['memory_cost_kib']),
    }
    plain['warning'] = 'MAINNET ENCRYPTED WALLET. Private seed is decrypted only in memory for this operation.'
    return plain


def load_wallet(path: str, password: Optional[str] = None) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        wallet = json.load(f)
    if not isinstance(wallet, dict):
        raise ValueError('Wallet file must contain a JSON object')
    if int(wallet.get('version', 0) or 0) == WALLET_VERSION and isinstance(wallet.get('encryption'), dict):
        locked = _normalize_encrypted_wallet(wallet)
        if password is None:
            return locked
        return unlock_wallet(locked, password)
    return _normalize_plain_wallet(wallet)


def migrate_wallet_file_to_encrypted(path: str, password: str, backup_path: Optional[str] = None) -> str:
    validate_new_password(password)
    p = Path(path)
    wallet = load_wallet(str(p))
    if is_encrypted_wallet(wallet):
        raise ValueError('Wallet is already encrypted')
    if backup_path:
        backup = Path(backup_path)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, backup)
    save_encrypted_wallet(wallet, str(p), password)
    return str(p)


def change_wallet_password(path: str, old_password: str, new_password: str) -> None:
    validate_new_password(new_password)
    wallet = load_wallet(path, old_password)
    if not isinstance(wallet.get('_encrypted_storage'), dict):
        raise ValueError('Wallet is not encrypted')
    save_encrypted_wallet(wallet, path, new_password)


def _branch_records(wallet: Dict[str, Any], branch: str) -> List[Dict[str, Any]]:
    field = {'receive': 'receive_addresses', 'change': 'change_addresses', 'mining': 'mining_addresses'}[branch]
    return list(wallet.get(field, []))


def all_wallet_key_records(wallet: Dict[str, Any]) -> List[Dict[str, Any]]:
    normalized = normalize_wallet(wallet)
    out: List[Dict[str, Any]] = []
    seen = set()
    for branch in ('receive', 'change', 'mining'):
        for item in _branch_records(normalized, branch):
            if item['address'] not in seen:
                seen.add(item['address'])
                out.append(item)
    return out


def wallet_addresses(wallet: Dict[str, Any]) -> List[str]:
    return [str(x['address']) for x in all_wallet_key_records(wallet)]


def current_receive_record(wallet: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_wallet(wallet)
    index = int(normalized.get('current_receive_index', 0))
    for item in normalized['receive_addresses']:
        if int(item['index']) == index:
            return item
    return normalized['receive_addresses'][-1]


def current_mining_record(wallet: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_wallet(wallet)
    index = int(normalized.get('current_mining_index', 0))
    for item in normalized['mining_addresses']:
        if int(item['index']) == index:
            return item
    return normalized['mining_addresses'][0]


def generate_receive_address(wallet: Dict[str, Any], label: str = '') -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized = normalize_wallet(wallet)
    seed = _master_seed_bytes(normalized)
    index = int(normalized['next_receive_index'])
    item = _record(seed, 'receive', index, label or f'Receive {index}')
    normalized['receive_addresses'].append(item)
    normalized['next_receive_index'] = index + 1
    normalized['current_receive_index'] = index
    return normalized, item


def generate_change_address(wallet: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    normalized = normalize_wallet(wallet)
    seed = _master_seed_bytes(normalized)
    index = int(normalized['next_change_index'])
    item = _record(seed, 'change', index, f'Change {index}')
    normalized['change_addresses'].append(item)
    normalized['next_change_index'] = index + 1
    return normalized, item


def set_current_receive_index(wallet: Dict[str, Any], index: int) -> Dict[str, Any]:
    normalized = normalize_wallet(wallet)
    if not any(int(x['index']) == int(index) for x in normalized['receive_addresses']):
        raise ValueError('Receive address index is not in this wallet')
    normalized['current_receive_index'] = int(index)
    return normalized


def _record_for_address(wallet: Dict[str, Any], address: str) -> Dict[str, Any]:
    normalized = normalize_wallet(wallet)
    for item in all_wallet_key_records(normalized):
        if item['address'] == address:
            return item
    raise ValueError('Address is not owned by this wallet')


def private_key_for_address(wallet: Dict[str, Any], address: str) -> Ed25519PrivateKey:
    normalized = normalize_wallet(wallet)
    item = _record_for_address(normalized, address)
    seed = _master_seed_bytes(normalized)
    private_seed = _derive_private_seed(seed, str(item['branch']), int(item['index']))
    private = Ed25519PrivateKey.from_private_bytes(private_seed)
    if private.public_key().public_bytes_raw().hex() != item['public_key']:
        raise ValueError('Derived signing key does not match wallet public key')
    return private


def public_key_for_address(wallet: Dict[str, Any], address: str) -> str:
    return str(_record_for_address(wallet, address)['public_key'])


def signing_message(tx: Dict[str, Any], input_index: int) -> bytes:
    body = {
        'timestamp': int(tx['timestamp']),
        'inputs': [
            {'txid': i['txid'], 'vout': int(i['vout']), 'pubkey': i['pubkey'], 'signature': ''}
            for i in tx['inputs']
        ],
        'outputs': tx['outputs'],
        'signing_input': int(input_index),
    }
    return canonical_json(body)


def sign_transaction_input(tx: Dict[str, Any], input_index: int, wallet: Dict[str, Any], address: Optional[str] = None) -> str:
    if address is None:
        item = tx['inputs'][input_index]
        try:
            address = address_from_pubkey(bytes.fromhex(str(item['pubkey'])))
        except Exception as exc:
            raise ValueError('Cannot determine signing address for transaction input') from exc
    private = private_key_for_address(wallet, address)
    return private.sign(signing_message(tx, input_index)).hex()


def verify_signature(tx: Dict[str, Any], input_index: int) -> bool:
    item = tx['inputs'][input_index]
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(item['pubkey']))
        public.verify(bytes.fromhex(item['signature']), signing_message(tx, input_index))
        return True
    except Exception:
        return False
