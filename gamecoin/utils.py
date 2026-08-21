import hashlib
import json
from typing import Any, Dict, Iterable, List

ALPHABET = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
DIFFICULTY_SCALE = 1_000_000
BASE_EXPECTED_HASHES = 4096
MAX_HASH_INT = (1 << 256) - 1


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    return sha256(sha256(data))


def hash_hex(obj: Any) -> str:
    return sha256d(canonical_json(obj)).hex()


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, 'big')
    out = bytearray()
    while n:
        n, rem = divmod(n, 58)
        out.append(ALPHABET[rem])
    pad = 0
    for b in data:
        if b == 0:
            pad += 1
        else:
            break
    return (ALPHABET[:1] * pad + bytes(reversed(out or b'1'))).decode('ascii')


def b58decode(text: str) -> bytes:
    raw = str(text).encode('ascii')
    if not raw:
        raise ValueError('Empty base58 value')
    indexes = {char: index for index, char in enumerate(ALPHABET)}
    n = 0
    for char in raw:
        if char not in indexes:
            raise ValueError('Invalid base58 character')
        n = n * 58 + indexes[char]
    decoded = b'' if n == 0 else n.to_bytes((n.bit_length() + 7) // 8, 'big')
    pad = 0
    for char in raw:
        if char == ALPHABET[0]:
            pad += 1
        else:
            break
    return b'\x00' * pad + decoded


def address_from_pubkey(pubkey: bytes) -> str:
    payload = hashlib.sha256(pubkey).digest()[:20]
    checksum = sha256d(payload)[:4]
    return 'M' + b58encode(payload + checksum)


def validate_address(address: str) -> bool:
    value = str(address or '')
    if not value.startswith('M') or len(value) < 2:
        return False
    try:
        decoded = b58decode(value[1:])
    except (ValueError, UnicodeEncodeError):
        return False
    if len(decoded) != 24:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    if checksum != sha256d(payload)[:4]:
        return False
    return 'M' + b58encode(decoded) == value


def tx_id(tx: Dict[str, Any]) -> str:
    body = dict(tx)
    body.pop('txid', None)
    return hash_hex(body)


def merkle_root(txids: Iterable[str]) -> str:
    level: List[bytes] = [bytes.fromhex(x) for x in txids]
    if not level:
        return sha256d(b'').hex()
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [sha256d(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def block_header(block: Dict[str, Any]) -> Dict[str, Any]:
    # Version 1 used integer "leading hex zeroes" difficulty.
    # Version 2 keeps the field integer but interprets it as millionths of
    # a smooth work factor, where 1.000000x ~= 4096 expected hashes.
    return {
        'version': int(block['version']),
        'height': int(block['height']),
        'prev_hash': str(block['prev_hash']),
        'timestamp': int(block['timestamp']),
        'difficulty': int(block['difficulty']),
        'merkle_root': str(block['merkle_root']),
        'nonce': int(block['nonce']),
    }


def block_hash(block: Dict[str, Any]) -> str:
    return hash_hex(block_header(block))


def target_for_difficulty(difficulty_units: int) -> int:
    units = max(1, int(difficulty_units))
    denominator = BASE_EXPECTED_HASHES * units
    return max(1, (MAX_HASH_INT * DIFFICULTY_SCALE) // denominator)


def meets_work(hash_string: str, difficulty: int, version: int = 2) -> bool:
    if int(version) <= 1:
        return hash_string.startswith('0' * int(difficulty))
    return int(hash_string, 16) <= target_for_difficulty(int(difficulty))


def meets_difficulty(hash_string: str, difficulty: int) -> bool:
    # Backward-compatible helper for the old v0.1/v0.2 miner and tests.
    return hash_string.startswith('0' * int(difficulty))


def difficulty_units_from_legacy(leading_zeroes: int) -> int:
    expected = 16 ** max(0, int(leading_zeroes))
    return max(1, int(round(expected * DIFFICULTY_SCALE / BASE_EXPECTED_HASHES)))


def difficulty_factor(difficulty_units: int) -> float:
    return max(1, int(difficulty_units)) / DIFFICULTY_SCALE


def expected_hashes_for_block(block: Dict[str, Any]) -> float:
    if int(block.get('version', 1)) <= 1:
        return float(16 ** max(0, int(block.get('difficulty', 0))))
    return BASE_EXPECTED_HASHES * difficulty_factor(int(block.get('difficulty', DIFFICULTY_SCALE)))
