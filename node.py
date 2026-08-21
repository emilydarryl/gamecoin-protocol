#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from gamecoin.consensus import (
    COINBASE_MATURITY, HALVING_INTERVAL_BLOCKS, INITIAL_BLOCK_REWARD, MAX_SUPPLY,
    MAX_BLOCK_BYTES, MAX_BLOCK_TRANSACTIONS, MAX_MEMPOOL_TRANSACTIONS, MAX_TX_BYTES,
    MAX_TX_INPUTS, MAX_TX_OUTPUTS, TARGET_BLOCK_SECONDS, block_subsidy,
    blocks_until_halving, circulating_supply, coinbase_is_mature, next_halving_height,
)
from gamecoin.chainwork import chain_work
from gamecoin.logging_utils import log_line
from gamecoin.network import NETWORK_NAME, P2P_PROTOCOL, p2p_request, unique_peers
from gamecoin.time_rules import median_time_past, validate_block_timestamp
from gamecoin.transaction_rules import expected_coinbase_value, transaction_fee
from gamecoin.utils import (
    BASE_EXPECTED_HASHES,
    DIFFICULTY_SCALE,
    address_from_pubkey,
    block_hash,
    canonical_json,
    difficulty_factor,
    difficulty_units_from_legacy,
    expected_hashes_for_block,
    merkle_root,
    meets_work,
    target_for_difficulty,
    tx_id,
    validate_address,
)
from gamecoin.wallet_core import signing_message

VERSION = 2
NODE_VERSION = '1.0.0'
GENESIS_MESSAGE = 'GameCoin mainnet genesis 2026-08-18 | v1.0.0 | subsidy 5 GAME | halving 2102400 | target 150s | no premine'
GENESIS_TIMESTAMP = 1787103720
LEGACY_V1_GENESIS_HASH = '383154a7a3749ac7451830c45175c31ef03f51ffbd9397d6817d6b38129de5c7'
LEGACY_V2_080_GENESIS_HASH = 'bc1419ce96585bb62bbdad430cb2fc3492ada89cac7bab77dbf9dd5264366289'
LEGACY_V2_STABLE_GENESIS_HASH = '15318ffdacb299fcf99464f9b98e5796f6629144db5b2c7f2bc2554168ea1b9b'
LEGACY_V3_CANDIDATE_GENESIS_HASH = 'a39239d64e406bb6ec343176cdd7c0b3efd00022293d07bb5546c98628175b69'
ZERO_HASH = '0' * 64
ADJUST_WINDOW = 12
DISPLAY_WINDOW = 20
MAX_ADJUST_UP_STABLE = 1.10
MAX_ADJUST_UP_NEAR = 1.25
MAX_ADJUST_UP_FAST = 1.50
MAX_ADJUST_UP_VERY_FAST = 1.75
MAX_ADJUST_DOWN = 0.67
DIFFICULTY_SAMPLE_MIN_SECONDS = max(1, TARGET_BLOCK_SECONDS // 4)
DIFFICULTY_SAMPLE_MAX_SECONDS = TARGET_BLOCK_SECONDS * 4
INITIAL_DIFFICULTY_FACTOR = 1_000
INITIAL_DIFFICULTY_UNITS = INITIAL_DIFFICULTY_FACTOR * DIFFICULTY_SCALE
MIN_DIFFICULTY_UNITS = 25_000
MAX_DIFFICULTY_UNITS = 1_000_000_000_000
P2P_MAX_BODY = 4 * 1024 * 1024
P2P_BLOCK_BATCH = 100
P2P_MEMPOOL_LIMIT = 250
SYNC_INTERVAL = 2.0


def make_genesis() -> Dict[str, Any]:
    tx = {
        'timestamp': GENESIS_TIMESTAMP,
        'inputs': [],
        'outputs': [],
        'coinbase': GENESIS_MESSAGE,
    }
    tx['txid'] = tx_id(tx)
    block = {
        'version': 1,
        'height': 0,
        'prev_hash': ZERO_HASH,
        'timestamp': GENESIS_TIMESTAMP,
        'difficulty': 0,
        'merkle_root': merkle_root([tx['txid']]),
        'nonce': 0,
        'transactions': [tx],
    }
    block['hash'] = block_hash(block)
    return block


GENESIS_HASH = make_genesis()['hash']


class ChainState:
    def __init__(self, data_dir: str, log_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.chain_path = self.data_dir / 'chain.json'
        self.mempool_path = self.data_dir / 'mempool.json'
        self.node_log = self.log_dir / 'node.log'
        self.tx_log = self.log_dir / 'transactions.log'
        self.difficulty_log = self.log_dir / 'difficulty.log'
        self.network_log = self.log_dir / 'network.log'
        self.lock = threading.RLock()
        self.chain: List[Dict[str, Any]] = []
        self.mempool: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.chain_path.exists():
            self.chain = json.loads(self.chain_path.read_text(encoding='utf-8'))
        else:
            self.chain = [make_genesis()]
            self._save_chain()

        existing_genesis = str(self.chain[0].get('hash', '')) if self.chain else ''
        if existing_genesis != GENESIS_HASH:
            raise RuntimeError(
                'chain.json does not belong to GameCoin Mainnet (genesis mismatch). '
                'Mainnet will not modify or archive a foreign/testnet chain automatically.'
            )

        if self.mempool_path.exists():
            self.mempool = json.loads(self.mempool_path.read_text(encoding='utf-8'))
        else:
            self.mempool = []
            self._save_mempool()

    def _atomic_write(self, path: Path, value: Any) -> None:
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        os.replace(tmp, path)

    def _save_chain(self) -> None:
        self._atomic_write(self.chain_path, self.chain)

    def _save_mempool(self) -> None:
        self._atomic_write(self.mempool_path, self.mempool)

    def tip(self) -> Dict[str, Any]:
        return self.chain[-1]

    def total_work(self, chain: Optional[List[Dict[str, Any]]] = None) -> int:
        items = chain if chain is not None else self.chain
        return chain_work(items)

    @staticmethod
    def _apply_tx_to_utxos(
        tx: Dict[str, Any],
        utxos: Dict[Tuple[str, int], Dict[str, Any]],
        *,
        created_height: Optional[int] = None,
    ) -> None:
        for inp in tx.get('inputs', []):
            utxos.pop((inp['txid'], int(inp['vout'])), None)
        tid = tx['txid']
        is_coinbase = 'coinbase' in tx
        for idx, out in enumerate(tx.get('outputs', [])):
            record = dict(out)
            record['_created_height'] = None if created_height is None else int(created_height)
            record['_coinbase'] = bool(is_coinbase)
            utxos[(tid, idx)] = record

    def build_utxos(self, include_mempool: bool = False) -> Dict[Tuple[str, int], Dict[str, Any]]:
        utxos: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for block in self.chain:
            height = int(block.get('height', 0))
            for tx in block['transactions']:
                self._apply_tx_to_utxos(tx, utxos, created_height=height)
        if include_mempool:
            for tx in self.mempool:
                self._apply_tx_to_utxos(tx, utxos)
        return utxos

    def validate_normal_tx(
        self,
        tx: Dict[str, Any],
        utxos: Dict[Tuple[str, int], Dict[str, Any]],
        *,
        spend_height: Optional[int] = None,
    ) -> int:
        if not isinstance(tx.get('inputs'), list) or not tx['inputs']:
            raise ValueError('Transaction needs at least one input')
        if not isinstance(tx.get('outputs'), list) or not tx['outputs']:
            raise ValueError('Transaction needs at least one output')
        if len(tx['inputs']) > MAX_TX_INPUTS:
            raise ValueError(f'Transaction has too many inputs (max {MAX_TX_INPUTS})')
        if len(tx['outputs']) > MAX_TX_OUTPUTS:
            raise ValueError(f'Transaction has too many outputs (max {MAX_TX_OUTPUTS})')
        if len(canonical_json(tx)) > MAX_TX_BYTES:
            raise ValueError(f'Transaction exceeds {MAX_TX_BYTES} byte consensus limit')
        if 'coinbase' in tx:
            raise ValueError('Normal transaction cannot contain coinbase')
        if tx_id(tx) != tx.get('txid'):
            raise ValueError('Invalid transaction ID')

        seen = set()
        input_total = 0
        for idx, inp in enumerate(tx['inputs']):
            key = (str(inp['txid']), int(inp['vout']))
            if key in seen:
                raise ValueError('Duplicate input')
            seen.add(key)
            if key not in utxos:
                raise ValueError('Input is missing or already spent')
            prev = utxos[key]
            if bool(prev.get('_coinbase')):
                created_height = prev.get('_created_height')
                if created_height is None:
                    raise ValueError('Coinbase UTXO is missing its creation height')
                candidate_height = len(self.chain) if spend_height is None else int(spend_height)
                if not coinbase_is_mature(int(created_height), candidate_height):
                    remaining = COINBASE_MATURITY - (candidate_height - int(created_height))
                    raise ValueError(f'Coinbase output is immature ({max(1, remaining)} blocks remaining)')
            pubkey = bytes.fromhex(inp['pubkey'])
            if address_from_pubkey(pubkey) != prev['address']:
                raise ValueError('Input public key does not own referenced output')
            try:
                Ed25519PublicKey.from_public_bytes(pubkey).verify(
                    bytes.fromhex(inp['signature']), signing_message(tx, idx)
                )
            except Exception as exc:
                raise ValueError('Invalid signature') from exc
            input_total += int(prev['amount'])

        output_total = 0
        for out in tx['outputs']:
            amount = int(out['amount'])
            if amount <= 0:
                raise ValueError('Output amount must be positive')
            if not validate_address(str(out['address'])):
                raise ValueError('Invalid GameCoin address checksum or encoding')
            output_total += amount
        return transaction_fee(input_total, output_total)

    def add_transaction(self, tx: Dict[str, Any], source: str = 'local') -> str:
        with self.lock:
            # Coinbase transactions are block-only. Reject them before the
            # idempotent already-known TXID path so RPC/P2P submission can
            # never report a coinbase as an accepted mempool transaction.
            if 'coinbase' in tx:
                raise ValueError('Coinbase transactions cannot be submitted to the mempool')
            if any(existing['txid'] == tx.get('txid') for existing in self.mempool):
                return tx['txid']
            # A confirmed transaction is already known and does not need to re-enter the mempool.
            for block in self.chain[-200:]:
                if any(t.get('txid') == tx.get('txid') for t in block.get('transactions', [])):
                    return tx['txid']
            if len(self.mempool) >= MAX_MEMPOOL_TRANSACTIONS:
                raise ValueError('Mempool transaction limit reached')
            utxos = self.build_utxos(include_mempool=True)
            fee = self.validate_normal_tx(tx, utxos, spend_height=len(self.chain))
            self.mempool.append(tx)
            self._save_mempool()
            log_line(
                self.tx_log,
                f'accepted tx={tx["txid"]} source={source} inputs={len(tx["inputs"])} '
                f'outputs={len(tx["outputs"])} fee_atoms={fee}',
            )
            return tx['txid']

    @staticmethod
    def _last_difficulty_units_for(chain: List[Dict[str, Any]]) -> int:
        tip = chain[-1]
        if int(tip.get('height', 0)) <= 0:
            return INITIAL_DIFFICULTY_UNITS
        if int(tip.get('version', 1)) >= 2:
            return max(1, int(tip.get('difficulty', DIFFICULTY_SCALE)))
        return difficulty_units_from_legacy(int(tip.get('difficulty', 3)))

    @staticmethod
    def _recent_work_samples_for(chain: List[Dict[str, Any]], window: int = ADJUST_WINDOW) -> List[Tuple[float, float]]:
        if len(chain) < 2:
            return []
        smooth_indices = [i for i in range(1, len(chain)) if int(chain[i].get('version', 1)) >= 2]
        indices = smooth_indices[-window:] if smooth_indices else list(range(max(1, len(chain) - window), len(chain)))
        samples: List[Tuple[float, float]] = []
        for i in indices:
            cur = chain[i]
            prev_time = int(chain[i - 1].get('timestamp', 0))
            cur_time = int(cur.get('timestamp', 0))
            if prev_time <= 0 or cur_time <= 0:
                continue
            # MTP remains the consensus validity rule, but difficulty must measure
            # the actual adjacent block timestamps.  Using successive MTP values
            # hides long solve times and can massively over-estimate hash rate.
            elapsed = float(cur_time - prev_time)
            if elapsed <= 0:
                elapsed = float(DIFFICULTY_SAMPLE_MIN_SECONDS)
            # Clamp individual samples so a lucky burst or one skewed timestamp
            # cannot dominate the rolling work/time estimate.
            elapsed = max(float(DIFFICULTY_SAMPLE_MIN_SECONDS), elapsed)
            elapsed = min(float(DIFFICULTY_SAMPLE_MAX_SECONDS), elapsed)
            samples.append((elapsed, expected_hashes_for_block(cur)))
        return samples

    @classmethod
    def _difficulty_plan_for(cls, chain: List[Dict[str, Any]]) -> Dict[str, Any]:
        current = cls._last_difficulty_units_for(chain)
        samples = cls._recent_work_samples_for(chain)
        if not samples:
            return {
                'current_units': current,
                'desired_units': current,
                'next_units': current,
                'status': 'CALIBRATING',
                'max_up': MAX_ADJUST_UP_VERY_FAST,
                'active_average_seconds': None,
            }
        total_seconds = sum(s[0] for s in samples)
        total_expected_hashes = sum(s[1] for s in samples)
        active_average = total_seconds / len(samples)
        rate = total_expected_hashes / max(1.0, total_seconds)
        desired_expected_hashes = rate * TARGET_BLOCK_SECONDS
        desired_units = int(round(desired_expected_hashes * DIFFICULTY_SCALE / BASE_EXPECTED_HASHES))
        desired_units = max(MIN_DIFFICULTY_UNITS, min(MAX_DIFFICULTY_UNITS, desired_units))

        if active_average < 15.0:
            max_up = MAX_ADJUST_UP_VERY_FAST
        elif active_average < 60.0:
            max_up = MAX_ADJUST_UP_FAST
        elif active_average < 120.0:
            max_up = MAX_ADJUST_UP_NEAR
        else:
            max_up = MAX_ADJUST_UP_STABLE

        ratio = desired_units / max(1, current)
        ratio = max(MAX_ADJUST_DOWN, min(max_up, ratio))
        adjusted = int(round(current * ratio))
        adjusted = max(MIN_DIFFICULTY_UNITS, min(MAX_DIFFICULTY_UNITS, adjusted))

        if adjusted > current * 1.05:
            status = 'RAMPING UP'
        elif adjusted < current * 0.95:
            status = 'RAMPING DOWN'
        else:
            status = 'STABLE'
        return {
            'current_units': current,
            'desired_units': desired_units,
            'next_units': adjusted,
            'status': status,
            'max_up': max_up,
            'active_average_seconds': active_average,
        }

    def difficulty_plan(self) -> Dict[str, Any]:
        return self._difficulty_plan_for(self.chain)

    def next_difficulty_units(self) -> int:
        return int(self.difficulty_plan()['next_units'])

    def estimated_hashrate(self) -> float:
        samples = self._recent_work_samples_for(self.chain)
        if not samples:
            current = self._last_difficulty_units_for(self.chain)
            return BASE_EXPECTED_HASHES * difficulty_factor(current) / TARGET_BLOCK_SECONDS
        return sum(s[1] for s in samples) / max(1.0, sum(s[0] for s in samples))

    def block_intervals(self, window: int = DISPLAY_WINDOW) -> List[float]:
        if len(self.chain) < 3:
            return []
        intervals: List[float] = []
        start = max(2, len(self.chain) - window)
        for i in range(start, len(self.chain)):
            elapsed = float(int(self.chain[i].get('timestamp', 0)) - int(self.chain[i - 1].get('timestamp', 0)))
            if elapsed >= 0:
                intervals.append(elapsed)
        return intervals

    def network_stats(self) -> Dict[str, Any]:
        plan = self.difficulty_plan()
        next_units = int(plan['next_units'])
        current_units = int(plan['current_units'])
        desired_units = int(plan['desired_units'])
        intervals = self.block_intervals()
        return {
            'difficulty_units': next_units,
            'difficulty_factor': difficulty_factor(next_units),
            'current_difficulty_units': current_units,
            'current_difficulty_factor': difficulty_factor(current_units),
            'next_difficulty_units': next_units,
            'next_difficulty_factor': difficulty_factor(next_units),
            'estimated_needed_difficulty_units': desired_units,
            'estimated_needed_difficulty_factor': difficulty_factor(desired_units),
            'difficulty_status': plan['status'],
            'max_adjust_up': float(plan['max_up']),
            'active_average_block_seconds': plan['active_average_seconds'],
            'expected_hashes': BASE_EXPECTED_HASHES * difficulty_factor(next_units),
            'target_block_seconds': TARGET_BLOCK_SECONDS,
            'initial_difficulty_units': INITIAL_DIFFICULTY_UNITS,
            'initial_difficulty_factor': float(INITIAL_DIFFICULTY_FACTOR),
            'average_block_seconds': mean(intervals) if intervals else None,
            'last_block_seconds': intervals[-1] if intervals else None,
            'estimated_hashrate': self.estimated_hashrate(),
            'adjustment_window': ADJUST_WINDOW,
            'v2_blocks': sum(1 for b in self.chain if int(b.get('version', 1)) >= 2),
            'pow_version': VERSION,
            'target_hex': f'{target_for_difficulty(next_units):064x}',
        }

    def mining_template(self, address: str) -> Dict[str, Any]:
        if not validate_address(address):
            raise ValueError('Invalid GameCoin mining address')
        with self.lock:
            height = len(self.chain)
            difficulty_units = self.next_difficulty_units()
            working_utxos = self.build_utxos(include_mempool=False)
            selected_txs: List[Dict[str, Any]] = []
            total_fees = 0
            for tx in self.mempool:
                if len(selected_txs) + 1 >= MAX_BLOCK_TRANSACTIONS:
                    break
                try:
                    fee = self.validate_normal_tx(tx, working_utxos, spend_height=height)
                    self._apply_tx_to_utxos(tx, working_utxos, created_height=height)
                except Exception:
                    continue
                selected_txs.append(dict(tx))
                total_fees += fee
            block_timestamp = max(int(time.time()), median_time_past(self.chain) + 1)
            coinbase = {
                'timestamp': block_timestamp,
                'inputs': [],
                'outputs': [{'address': address, 'amount': expected_coinbase_value(height, total_fees)}],
                'coinbase': f'height:{height}',
            }
            coinbase['txid'] = tx_id(coinbase)
            txs = [coinbase] + selected_txs
            block = {
                'version': VERSION,
                'height': height,
                'prev_hash': self.tip()['hash'],
                'timestamp': block_timestamp,
                'difficulty': difficulty_units,
                'merkle_root': merkle_root([t['txid'] for t in txs]),
                'nonce': 0,
                'transactions': txs,
            }
            # Stop adding mempool transactions before a template can exceed the block byte limit.
            while len(canonical_json(block)) > MAX_BLOCK_BYTES and len(selected_txs) > 0:
                removed = selected_txs.pop()
                working_utxos = self.build_utxos(include_mempool=False)
                total_fees = 0
                for chosen in selected_txs:
                    fee = self.validate_normal_tx(chosen, working_utxos, spend_height=height)
                    self._apply_tx_to_utxos(chosen, working_utxos, created_height=height)
                    total_fees += fee
                coinbase['outputs'][0]['amount'] = expected_coinbase_value(height, total_fees)
                coinbase['txid'] = tx_id(coinbase)
                txs = [coinbase] + selected_txs
                block['transactions'] = txs
                block['merkle_root'] = merkle_root([t['txid'] for t in txs])
            return block

    def _validate_block_against(self, block: Dict[str, Any], chain: List[Dict[str, Any]],
                                utxos: Dict[Tuple[str, int], Dict[str, Any]]) -> Dict[str, Any]:
        expected_height = len(chain)
        if int(block.get('height', -1)) != expected_height:
            raise ValueError('Wrong block height')
        if block.get('prev_hash') != chain[-1]['hash']:
            raise ValueError('Wrong previous block hash')
        validate_block_timestamp(chain, int(block.get('timestamp', 0)))
        if len(canonical_json(block)) > MAX_BLOCK_BYTES:
            raise ValueError(f'Block exceeds {MAX_BLOCK_BYTES} byte consensus limit')
        version = int(block.get('version', -1))
        difficulty = int(block.get('difficulty', -1))
        if version != VERSION:
            raise ValueError(f'Unsupported block version for GameCoin Mainnet: {version}')
        expected_difficulty = int(self._difficulty_plan_for(chain)['next_units'])
        if difficulty != expected_difficulty:
            raise ValueError('Wrong or stale difficulty')

        txs = block.get('transactions')
        if not isinstance(txs, list) or not txs:
            raise ValueError('Block contains no transactions')
        if len(txs) > MAX_BLOCK_TRANSACTIONS:
            raise ValueError(f'Block contains too many transactions (max {MAX_BLOCK_TRANSACTIONS})')
        if merkle_root([t.get('txid', '') for t in txs]) != block.get('merkle_root'):
            raise ValueError('Invalid Merkle root')
        bhash = block_hash(block)
        if block.get('hash') not in (None, bhash):
            raise ValueError('Stored block hash is invalid')
        if not meets_work(bhash, difficulty, version):
            raise ValueError('Proof of work does not meet target')

        coinbase = txs[0]
        if coinbase.get('inputs') != [] or 'coinbase' not in coinbase:
            raise ValueError('First transaction must be coinbase')
        if tx_id(coinbase) != coinbase.get('txid'):
            raise ValueError('Invalid coinbase transaction ID')
        outputs = coinbase.get('outputs', [])
        if len(outputs) != 1:
            raise ValueError('Coinbase must contain exactly one output')
        if int(outputs[0].get('amount', -1)) < 0:
            raise ValueError('Coinbase output amount cannot be negative')
        if not validate_address(str(outputs[0].get('address', ''))):
            raise ValueError('Invalid coinbase address checksum or encoding')
        seen_txids = {coinbase['txid']}
        total_fees = 0
        for tx in txs[1:]:
            if tx.get('txid') in seen_txids:
                raise ValueError('Duplicate transaction in block')
            fee = self.validate_normal_tx(tx, utxos, spend_height=expected_height)
            self._apply_tx_to_utxos(tx, utxos, created_height=expected_height)
            total_fees += fee
            seen_txids.add(tx['txid'])
        expected_reward = expected_coinbase_value(expected_height, total_fees)
        if int(outputs[0].get('amount', -1)) != expected_reward:
            raise ValueError(
                f'Invalid coinbase reward: expected {expected_reward} atoms at height {expected_height} '
                f'(subsidy {block_subsidy(expected_height)} + fees {total_fees})'
            )
        self._apply_tx_to_utxos(coinbase, utxos, created_height=expected_height)
        final = dict(block)
        final['hash'] = bhash
        return final

    def submit_block(self, block: Dict[str, Any], source: str = 'local') -> str:
        with self.lock:
            expected_height = len(self.chain)
            utxos = self.build_utxos(include_mempool=False)
            final_block = self._validate_block_against(block, self.chain, utxos)
            self.chain.append(final_block)
            included = {tx['txid'] for tx in final_block['transactions'][1:]}
            self.mempool = [tx for tx in self.mempool if tx['txid'] not in included]
            self._save_chain()
            self._save_mempool()

            stats = self.network_stats()
            factor = difficulty_factor(int(final_block['difficulty'])) if int(final_block.get('version', 1)) >= 2 else float(16 ** int(final_block['difficulty'])) / BASE_EXPECTED_HASHES
            interval = stats.get('last_block_seconds')
            interval_text = 'n/a' if interval is None else f'{float(interval):.1f}s'
            log_line(self.node_log, f'accepted block={expected_height} hash={final_block["hash"]} source={source} difficulty={factor:.6f}x interval={interval_text}')
            log_line(
                self.difficulty_log,
                f'block={expected_height} used={factor:.6f}x next={float(stats["difficulty_factor"]):.6f}x '
                f'needed={float(stats.get("estimated_needed_difficulty_factor", stats["difficulty_factor"])):.6f}x '
                f'status={stats.get("difficulty_status")} max_up={float(stats.get("max_adjust_up", 1.0)):.2f}x '
                f'avg_block={stats.get("average_block_seconds")}s active_avg={stats.get("active_average_block_seconds")}s '
                f'estimated_hashrate={float(stats["estimated_hashrate"]):.2f}H/s',
            )
            return final_block['hash']

    def validate_chain_candidate(self, candidate: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(candidate, list) or not candidate:
            raise ValueError('Candidate chain is empty')
        genesis = candidate[0]
        if genesis.get('hash') != GENESIS_HASH or block_hash(genesis) != GENESIS_HASH:
            raise ValueError('Candidate genesis mismatch')
        chain: List[Dict[str, Any]] = [dict(genesis)]
        utxos: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for tx in genesis.get('transactions', []):
            self._apply_tx_to_utxos(tx, utxos, created_height=0)
        for raw in candidate[1:]:
            final = self._validate_block_against(raw, chain, utxos)
            chain.append(final)
        return chain

    def replace_chain(self, candidate: List[Dict[str, Any]], source: str) -> bool:
        validated = self.validate_chain_candidate(candidate)
        with self.lock:
            if validated[-1]['hash'] == self.tip()['hash']:
                return False
            remote_work = self.total_work(validated)
            local_work = self.total_work(self.chain)
            if remote_work <= local_work:
                raise ValueError(
                    f'Candidate chain does not have greater cumulative work '
                    f'(remote={remote_work}, local={local_work})'
                )

            old_chain = self.chain
            confirmed = {tx.get('txid') for b in validated for tx in b.get('transactions', [])}
            orphaned: List[Dict[str, Any]] = []
            for b in old_chain:
                for tx in b.get('transactions', [])[1:]:
                    if tx.get('txid') not in confirmed:
                        orphaned.append(tx)

            self.chain = validated
            self.mempool = [tx for tx in self.mempool if tx.get('txid') not in confirmed]
            self._save_chain()
            self._save_mempool()
            # Best effort: return valid orphaned transactions to the mempool.
            for tx in orphaned:
                try:
                    self.add_transaction(tx, source='reorg')
                except Exception:
                    pass
            log_line(self.network_log, f'chain replaced source={source} old_height={old_chain[-1]["height"]} new_height={validated[-1]["height"]}')
            return True

    def utxos_for(self, address: str) -> List[Dict[str, Any]]:
        if not validate_address(address):
            raise ValueError('Invalid GameCoin address checksum or encoding')
        with self.lock:
            utxos = self.build_utxos(include_mempool=True)
            result = []
            tip_height = int(self.tip().get('height', 0))
            next_block_height = len(self.chain)
            for (tid, vout), out in utxos.items():
                if out['address'] != address:
                    continue
                created_height = out.get('_created_height')
                is_coinbase = bool(out.get('_coinbase'))
                confirmations = 0 if created_height is None else max(1, tip_height - int(created_height) + 1)
                mature = (
                    True
                    if not is_coinbase
                    else created_height is not None and coinbase_is_mature(int(created_height), next_block_height)
                )
                result.append({
                    'txid': tid,
                    'vout': vout,
                    'address': address,
                    'amount': int(out['amount']),
                    'created_height': created_height,
                    'confirmations': confirmations,
                    'coinbase': is_coinbase,
                    'mature': bool(mature),
                    'spendable': bool(mature),
                })
            return sorted(result, key=lambda x: (x['txid'], x['vout']))

    def wallet_stats(self, address: str) -> Dict[str, Any]:
        with self.lock:
            mined_blocks = 0
            mining_rewards = 0
            for block in self.chain:
                txs = block.get('transactions', [])
                if not txs:
                    continue
                coinbase = txs[0]
                if 'coinbase' not in coinbase:
                    continue
                reward = sum(int(o.get('amount', 0)) for o in coinbase.get('outputs', []) if o.get('address') == address)
                if reward:
                    mined_blocks += 1
                    mining_rewards += reward
            return {'address': address, 'mined_blocks': mined_blocks, 'mining_rewards': mining_rewards}


    def find_block(self, identifier: str) -> Optional[Dict[str, Any]]:
        value = str(identifier or '').strip()
        with self.lock:
            if value.isdigit():
                height = int(value)
                if 0 <= height < len(self.chain):
                    block = self.chain[height]
                    if int(block.get('height', -1)) == height:
                        return dict(block)
            lowered = value.lower()
            for block in self.chain:
                if str(block.get('hash', '')).lower() == lowered:
                    return dict(block)
        return None

    def find_transaction(self, txid: str) -> Optional[Dict[str, Any]]:
        wanted = str(txid or '').strip().lower()
        with self.lock:
            for tx in self.mempool:
                if str(tx.get('txid', '')).lower() == wanted:
                    return {'status': 'mempool', 'confirmations': 0, 'transaction': dict(tx)}
            tip_height = int(self.chain[-1].get('height', 0))
            for block in reversed(self.chain):
                for tx in block.get('transactions', []):
                    if str(tx.get('txid', '')).lower() == wanted:
                        height = int(block.get('height', 0))
                        return {
                            'status': 'confirmed',
                            'block_height': height,
                            'block_hash': block.get('hash'),
                            'confirmations': max(1, tip_height - height + 1),
                            'transaction': dict(tx),
                        }
        return None

    def address_summary(self, address: str) -> Dict[str, Any]:
        wanted = str(address or '').strip()
        if not wanted:
            raise ValueError('Address is required')
        with self.lock:
            items = self.utxos_for(wanted)
            balance = sum(x['amount'] for x in items)
            spendable_balance = sum(x['amount'] for x in items if x.get('spendable', True))
            stats = self.wallet_stats(wanted)
            received = 0
            appearances = []
            for block in reversed(self.chain):
                matched = []
                for tx in block.get('transactions', []):
                    amount = sum(int(o.get('amount', 0)) for o in tx.get('outputs', []) if o.get('address') == wanted)
                    if amount:
                        received += amount
                        matched.append({'txid': tx.get('txid'), 'received': amount})
                if matched and len(appearances) < 25:
                    appearances.append({'height': block.get('height'), 'hash': block.get('hash'), 'transactions': matched})
            return {
                'address': wanted,
                'balance': balance,
                'spendable_balance': spendable_balance,
                'immature_balance': balance - spendable_balance,
                'total_received': received,
                'mined_blocks': stats['mined_blocks'],
                'mining_rewards': stats['mining_rewards'],
                'recent_appearances': appearances,
            }


class PeerSyncManager:
    def __init__(self, state: ChainState, peers: List[str], seed_mode: bool, interval: float = SYNC_INTERVAL):
        self.state = state
        self.peers = unique_peers(peers)
        self.seed_mode = seed_mode
        self.interval = max(1.0, float(interval))
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
        self.connected: List[str] = []
        self.primary_peer = self.peers[0] if self.peers else None
        self.network_height = int(state.tip()['height'])
        self.network_tip = state.tip()['hash']
        self.sync_status = 'SEED' if seed_mode else ('NO PEERS' if not self.peers else 'STARTING')
        self.last_error = ''
        self.last_sync_at: Optional[int] = None

    def start(self) -> None:
        if self.seed_mode or not self.peers:
            return
        self.thread = threading.Thread(target=self._loop, name='gamecoin-peer-sync', daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)

    def info(self) -> Dict[str, Any]:
        with self.lock:
            local_height = int(self.state.tip()['height'])
            return {
                'seed_mode': self.seed_mode,
                'configured_peers': list(self.peers),
                'connected_peers': list(self.connected),
                'peer_count': len(self.connected),
                'primary_peer': self.primary_peer,
                'network_height': int(self.network_height),
                'network_tip': self.network_tip,
                'sync_lag': max(0, int(self.network_height) - local_height),
                'sync_status': self.sync_status,
                'last_sync_at': self.last_sync_at,
                'last_network_error': self.last_error,
            }

    def _peer_status(self, peer: str) -> Dict[str, Any]:
        status = p2p_request(peer, '/p2p/status', timeout=3.0)
        if status.get('network') != NETWORK_NAME:
            raise RuntimeError('Peer network mismatch')
        if status.get('genesis_hash') != GENESIS_HASH:
            raise RuntimeError('Peer genesis mismatch')
        if int(status.get('p2p_protocol', 0)) != P2P_PROTOCOL:
            raise RuntimeError('Peer protocol mismatch')
        return status

    def _fetch_chain(self, peer: str, remote_height: int) -> List[Dict[str, Any]]:
        chain: List[Dict[str, Any]] = []
        start = 0
        while start <= remote_height:
            limit = min(P2P_BLOCK_BATCH, remote_height - start + 1)
            resp = p2p_request(peer, f'/p2p/blocks?from={start}&limit={limit}', timeout=10.0)
            blocks = resp.get('blocks', [])
            if not blocks:
                raise RuntimeError(f'Peer returned no blocks at height {start}')
            chain.extend(blocks)
            start += len(blocks)
        if int(chain[-1].get('height', -1)) != remote_height:
            raise RuntimeError('Peer chain download ended at wrong height')
        return chain

    def _sync_from_peer(self, peer: str, status: Dict[str, Any]) -> None:
        remote_height = int(status['height'])
        remote_tip = str(status['tip_hash'])
        with self.lock:
            self.network_height = remote_height
            self.network_tip = remote_tip
            self.primary_peer = peer

        local_height = int(self.state.tip()['height'])
        local_tip = self.state.tip()['hash']
        if remote_height == local_height and remote_tip == local_tip:
            with self.lock:
                self.sync_status = 'SYNCED'
            return

        # If the remote chain extends our exact tip, download only the missing blocks.
        can_increment = False
        if remote_height > local_height:
            try:
                resp = p2p_request(peer, f'/p2p/blocks?from={local_height}&limit=1', timeout=5.0)
                anchor = resp.get('blocks', [None])[0]
                can_increment = bool(anchor and anchor.get('hash') == local_tip)
            except Exception:
                can_increment = False

        if can_increment:
            with self.lock:
                self.sync_status = 'SYNCING'
            start = local_height + 1
            while start <= remote_height:
                resp = p2p_request(peer, f'/p2p/blocks?from={start}&limit={P2P_BLOCK_BATCH}', timeout=10.0)
                blocks = resp.get('blocks', [])
                if not blocks:
                    raise RuntimeError('Peer stopped returning missing blocks')
                for block in blocks:
                    self.state.submit_block(block, source=f'peer:{peer}')
                start += len(blocks)
        else:
            # Conflicting histories are fully validated and adopted only when
            # they carry strictly greater deterministic cumulative proof-of-work.
            with self.lock:
                self.sync_status = 'REORG/SYNC'
            candidate = self._fetch_chain(peer, remote_height)
            self.state.replace_chain(candidate, source=f'peer:{peer}')

        # Pull pending transactions so every miner sees the same mempool.
        try:
            mp_resp = p2p_request(peer, f'/p2p/mempool?limit={P2P_MEMPOOL_LIMIT}', timeout=5.0)
            for tx in mp_resp.get('transactions', []):
                try:
                    self.state.add_transaction(tx, source=f'peer:{peer}')
                except Exception:
                    pass
        except Exception:
            pass

        with self.lock:
            self.sync_status = 'SYNCED' if self.state.tip()['hash'] == remote_tip else 'SYNCING'
            self.last_sync_at = int(time.time())

    def _loop(self) -> None:
        while not self.stop_event.is_set():
            connected: List[str] = []
            last_error = ''
            chosen: Optional[Tuple[str, Dict[str, Any]]] = None
            chosen_key: Optional[Tuple[int, int, str]] = None
            for peer in self.peers:
                try:
                    status = self._peer_status(peer)
                    connected.append(peer)
                    candidate_key = (
                        int(status.get('total_work', 0)),
                        int(status.get('height', 0)),
                        str(status.get('tip_hash', '')),
                    )
                    if chosen is None or chosen_key is None or candidate_key > chosen_key:
                        chosen = (peer, status)
                        chosen_key = candidate_key
                except Exception as exc:
                    last_error = f'{peer}: {exc}'
            with self.lock:
                self.connected = connected
                self.last_error = last_error
                if not connected:
                    self.sync_status = 'OFFLINE'
            if chosen:
                peer, status = chosen
                try:
                    self._sync_from_peer(peer, status)
                    with self.lock:
                        self.last_error = ''
                except Exception as exc:
                    with self.lock:
                        self.sync_status = 'SYNC ERROR'
                        self.last_error = str(exc)
                    log_line(self.state.network_log, f'sync error peer={peer} error={exc}')
            self.stop_event.wait(self.interval)

    def broadcast_transaction(self, tx: Dict[str, Any]) -> None:
        for peer in self.peers:
            try:
                p2p_request(peer, '/p2p/tx', method='POST', body={'tx': tx}, timeout=4.0)
            except Exception as exc:
                log_line(self.state.network_log, f'tx broadcast failed peer={peer} tx={tx.get("txid")} error={exc}')

    def broadcast_block(self, block: Dict[str, Any]) -> None:
        for peer in self.peers:
            try:
                p2p_request(peer, '/p2p/block', method='POST', body={'block': block}, timeout=8.0)
            except Exception as exc:
                log_line(self.state.network_log, f'block broadcast failed peer={peer} height={block.get("height")} error={exc}')


class RateLimiter:
    def __init__(self, max_per_minute: int = 240):
        self.max_per_minute = max_per_minute
        self.lock = threading.Lock()
        self.entries: Dict[str, Tuple[int, int]] = {}

    def allow(self, ip: str) -> bool:
        minute = int(time.time() // 60)
        with self.lock:
            old_minute, count = self.entries.get(ip, (minute, 0))
            if old_minute != minute:
                count = 0
                old_minute = minute
            count += 1
            self.entries[ip] = (old_minute, count)
            return count <= self.max_per_minute


class BaseJSONHandler(BaseHTTPRequestHandler):
    server_version = 'GameCoinTestnet/0.9'

    def _json(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-GameCoin-Network', NETWORK_NAME)
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, exc: Exception) -> None:
        self._json(status, {'ok': False, 'error': str(exc)})

    @property
    def state(self) -> ChainState:
        return self.server.state  # type: ignore[attr-defined]

    @property
    def sync(self) -> PeerSyncManager:
        return self.server.sync  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _read_json(self, max_bytes: int = P2P_MAX_BODY) -> Dict[str, Any]:
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > max_bytes:
            raise ValueError('Request body is too large')
        return json.loads(self.rfile.read(length).decode('utf-8')) if length else {}


class RPCHandler(BaseJSONHandler):
    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == '/status':
                tip = self.state.tip()
                stats = self.state.network_stats()
                self._json(200, {
                    'ok': True,
                    'network': NETWORK_NAME,
                    'node_version': NODE_VERSION,
                    'difficulty_algorithm': 'adaptive-window-v0.6',
                    'height': tip['height'],
                    'tip_hash': tip['hash'],
                    'genesis_hash': GENESIS_HASH,
                    'p2p_protocol': P2P_PROTOCOL,
                    'difficulty': stats['difficulty_units'],
                    **stats,
                    **self.sync.info(),
                    'block_reward': block_subsidy(int(tip['height']) + 1),
                    'initial_block_reward': INITIAL_BLOCK_REWARD,
                    'coinbase_maturity': COINBASE_MATURITY,
                    'halving_interval_blocks': HALVING_INTERVAL_BLOCKS,
                    'max_block_transactions': MAX_BLOCK_TRANSACTIONS,
                    'max_block_bytes': MAX_BLOCK_BYTES,
                    'max_mempool_transactions': MAX_MEMPOOL_TRANSACTIONS,
                    'circulating_supply': circulating_supply(int(tip['height'])),
                    'max_supply': MAX_SUPPLY,
                    'next_halving_height': next_halving_height(int(tip['height'])),
                    'blocks_until_halving': blocks_until_halving(int(tip['height'])),
                    'mempool_transactions': len(self.state.mempool),
                })
                return
            if parsed.path == '/mining/template':
                if self.sync.info().get('sync_lag', 0) > 0:
                    raise ValueError('Node is still synchronizing; wait until Sync Status is SYNCED')
                address = parse_qs(parsed.query).get('address', [''])[0]
                self._json(200, {'ok': True, 'block': self.state.mining_template(address)})
                return
            if parsed.path.startswith('/utxos/'):
                address = parsed.path.split('/utxos/', 1)[1]
                self._json(200, {'ok': True, 'utxos': self.state.utxos_for(address)})
                return
            if parsed.path.startswith('/balance/'):
                address = parsed.path.split('/balance/', 1)[1]
                items = self.state.utxos_for(address)
                total = sum(x['amount'] for x in items)
                spendable = sum(x['amount'] for x in items if x.get('spendable', True))
                self._json(200, {
                    'ok': True,
                    'address': address,
                    'balance': total,
                    'spendable_balance': spendable,
                    'immature_balance': total - spendable,
                })
                return
            if parsed.path.startswith('/walletstats/'):
                address = parsed.path.split('/walletstats/', 1)[1]
                self._json(200, {'ok': True, **self.state.wallet_stats(address)})
                return
            if parsed.path.startswith('/block/'):
                identifier = parsed.path.split('/block/', 1)[1]
                block = self.state.find_block(identifier)
                if block is None:
                    self._json(404, {'ok': False, 'error': 'Block not found'})
                else:
                    self._json(200, {'ok': True, 'block': block})
                return
            if parsed.path.startswith('/transaction/'):
                txid = parsed.path.split('/transaction/', 1)[1]
                result = self.state.find_transaction(txid)
                if result is None:
                    self._json(404, {'ok': False, 'error': 'Transaction not found'})
                else:
                    self._json(200, {'ok': True, **result})
                return
            if parsed.path.startswith('/address/'):
                address = parsed.path.split('/address/', 1)[1]
                self._json(200, {'ok': True, **self.state.address_summary(address)})
                return
            if parsed.path == '/blocks':
                limit = max(1, min(int(parse_qs(parsed.query).get('limit', ['10'])[0]), 100))
                self._json(200, {'ok': True, 'blocks': self.state.chain[-limit:]})
                return
            if parsed.path == '/mempool':
                limit = max(1, min(int(parse_qs(parsed.query).get('limit', [str(P2P_MEMPOOL_LIMIT)])[0]), P2P_MEMPOOL_LIMIT))
                with self.state.lock:
                    transactions = [dict(tx) for tx in self.state.mempool[:limit]]
                self._json(200, {'ok': True, 'transactions': transactions})
                return
            self._json(404, {'ok': False, 'error': 'Not found'})
        except Exception as exc:
            self._error(400, exc)

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == '/tx':
                tid = self.state.add_transaction(payload['tx'], source='wallet')
                self.sync.broadcast_transaction(payload['tx'])
                self._json(200, {'ok': True, 'txid': tid})
                return
            if self.path == '/mining/submit':
                block = payload['block']
                bhash = self.state.submit_block(block, source='local-miner')
                final_block = dict(block)
                final_block['hash'] = bhash
                self.sync.broadcast_block(final_block)
                self._json(200, {'ok': True, 'hash': bhash, 'height': self.state.tip()['height']})
                return
            if self.path == '/shutdown':
                self._json(200, {'ok': True, 'message': 'Node shutdown requested'})
                threading.Thread(target=self.server.shutdown, name='gamecoin-rpc-shutdown', daemon=True).start()
                return
            self._json(404, {'ok': False, 'error': 'Not found'})
        except Exception as exc:
            self._error(400, exc)


class P2PHandler(BaseJSONHandler):
    def _allowed(self) -> bool:
        limiter: RateLimiter = self.server.rate_limiter  # type: ignore[attr-defined]
        ip = self.client_address[0]
        if not limiter.allow(ip):
            self._json(429, {'ok': False, 'error': 'Rate limit exceeded'})
            return False
        seen: Dict[str, float] = self.server.seen_peers  # type: ignore[attr-defined]
        seen[ip] = time.time()
        return True

    def do_GET(self) -> None:
        if not self._allowed():
            return
        try:
            parsed = urlparse(self.path)
            if parsed.path == '/p2p/status':
                tip = self.state.tip()
                self._json(200, {
                    'ok': True,
                    'network': NETWORK_NAME,
                    'node_version': NODE_VERSION,
                    'p2p_protocol': P2P_PROTOCOL,
                    'initial_difficulty_units': INITIAL_DIFFICULTY_UNITS,
                    'initial_difficulty_factor': float(INITIAL_DIFFICULTY_FACTOR),
                    'genesis_hash': GENESIS_HASH,
                    'height': int(tip['height']),
                    'tip_hash': tip['hash'],
                    'total_work': self.state.total_work(),
                    'block_reward': block_subsidy(int(tip['height']) + 1),
                    'halving_interval_blocks': HALVING_INTERVAL_BLOCKS,
                    'circulating_supply': circulating_supply(int(tip['height'])),
                    'max_supply': MAX_SUPPLY,
                    'blocks_until_halving': blocks_until_halving(int(tip['height'])),
                    'mempool_transactions': len(self.state.mempool),
                })
                return
            if parsed.path == '/p2p/blocks':
                qs = parse_qs(parsed.query)
                start = max(0, int(qs.get('from', ['0'])[0]))
                limit = max(1, min(int(qs.get('limit', [str(P2P_BLOCK_BATCH)])[0]), P2P_BLOCK_BATCH))
                with self.state.lock:
                    blocks = self.state.chain[start:start + limit]
                self._json(200, {'ok': True, 'from': start, 'blocks': blocks})
                return
            if parsed.path == '/p2p/mempool':
                limit = max(1, min(int(parse_qs(parsed.query).get('limit', [str(P2P_MEMPOOL_LIMIT)])[0]), P2P_MEMPOOL_LIMIT))
                with self.state.lock:
                    txs = self.state.mempool[:limit]
                self._json(200, {'ok': True, 'transactions': txs})
                return
            self._json(404, {'ok': False, 'error': 'P2P endpoint not found'})
        except Exception as exc:
            self._error(400, exc)

    def do_POST(self) -> None:
        if not self._allowed():
            return
        try:
            payload = self._read_json()
            if self.path == '/p2p/tx':
                tid = self.state.add_transaction(payload['tx'], source=f'p2p:{self.client_address[0]}')
                self._json(200, {'ok': True, 'txid': tid})
                return
            if self.path == '/p2p/block':
                block = payload['block']
                bhash = self.state.submit_block(block, source=f'p2p:{self.client_address[0]}')
                self._json(200, {'ok': True, 'height': self.state.tip()['height'], 'hash': bhash})
                return
            self._json(404, {'ok': False, 'error': 'P2P endpoint not found'})
        except Exception as exc:
            self._error(400, exc)


def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise SystemExit(f'Could not read {path}: {exc}')


def main() -> None:
    parser = argparse.ArgumentParser(description='GameCoin Mainnet node v1.0.0')
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--rpc-host', default=None, help='Local wallet/miner RPC bind address')
    parser.add_argument('--rpc-port', type=int, default=None)
    parser.add_argument('--p2p-host', default=None, help='P2P bind address')
    parser.add_argument('--p2p-port', type=int, default=None)
    parser.add_argument('--peer', action='append', default=None, help='P2P peer/seed host:port (repeatable)')
    parser.add_argument('--seed-mode', action='store_true', help='Run as the public seed; do not sync from an upstream peer')
    parser.add_argument('--data-dir', default=None)
    parser.add_argument('--log-dir', default=None)
    parser.add_argument('--sync-interval', type=float, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    rpc_host = args.rpc_host or cfg.get('rpc_host', '127.0.0.1')
    rpc_port = args.rpc_port or int(cfg.get('rpc_port', 22444))
    p2p_host = args.p2p_host or cfg.get('p2p_host', '127.0.0.1')
    p2p_port = args.p2p_port or int(cfg.get('p2p_port', 22445))
    data_dir = args.data_dir or cfg.get('data_dir', 'data-mainnet')
    log_dir = args.log_dir or cfg.get('log_dir', 'logs-mainnet')
    seed_mode = bool(args.seed_mode or cfg.get('seed_mode', False))
    peers = args.peer if args.peer is not None else list(cfg.get('peers', []))
    sync_interval = args.sync_interval or float(cfg.get('sync_interval_seconds', SYNC_INTERVAL))

    # Mainnet deliberately keeps wallet/miner RPC local-only. Public Internet traffic
    # belongs on the separate P2P port, not on wallet administration endpoints.
    if rpc_host not in ('127.0.0.1', 'localhost', '::1'):
        raise SystemExit('For GameCoin Mainnet, --rpc-host must be localhost/127.0.0.1/::1. Expose only the P2P port.')

    state = ChainState(data_dir, log_dir)
    sync = PeerSyncManager(state, peers, seed_mode=seed_mode, interval=sync_interval)

    rpc_server = ThreadingHTTPServer((rpc_host, rpc_port), RPCHandler)
    rpc_server.state = state  # type: ignore[attr-defined]
    rpc_server.sync = sync  # type: ignore[attr-defined]

    p2p_server = ThreadingHTTPServer((p2p_host, p2p_port), P2PHandler)
    p2p_server.state = state  # type: ignore[attr-defined]
    p2p_server.sync = sync  # type: ignore[attr-defined]
    p2p_server.rate_limiter = RateLimiter()  # type: ignore[attr-defined]
    p2p_server.seen_peers = {}  # type: ignore[attr-defined]

    print('GameCoin MAINNET node v1.0.0')
    print(f'Chain ID / genesis: {GENESIS_HASH}')
    print(f'Wallet/miner RPC: http://{rpc_host}:{rpc_port}')
    print(f'P2P service:      http://{p2p_host}:{p2p_port}')
    print(f'Mode: {"PUBLIC SEED" if seed_mode else "CLIENT NODE"}')
    if peers:
        print('Configured peer(s): ' + ', '.join(unique_peers(peers)))
    print(f'Height: {state.tip()["height"]}')
    print('Target block time: 150 seconds')
    print('Initial block reward: 5 GAME')
    print(f'Halving interval: {HALVING_INTERVAL_BLOCKS:,} blocks (~10 years)')
    print(f'Maximum supply: {MAX_SUPPLY / 100_000_000:,.8f} GAME')
    print('Press Ctrl+C to stop.')
    log_line(state.node_log, f'node v1.0.0-mainnet started height={state.tip()["height"]} seed_mode={seed_mode} peers={unique_peers(peers)}')

    p2p_thread = threading.Thread(target=p2p_server.serve_forever, name='gamecoin-p2p-server', daemon=True)
    p2p_thread.start()
    sync.start()
    try:
        rpc_server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopping node.')
    finally:
        sync.stop()
        rpc_server.server_close()
        p2p_server.shutdown()
        p2p_server.server_close()
        log_line(state.node_log, 'node v1.0.0-mainnet stopped')


if __name__ == '__main__':
    main()
