#!/usr/bin/env python3
import argparse
import multiprocessing as mp
import os
import queue
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote

from gamecoin.logging_utils import log_line
from gamecoin.rpc import request_json
from gamecoin.utils import difficulty_factor, block_hash, meets_work
from gamecoin.wallet_core import current_mining_record, load_wallet

DEFAULT_NODE = 'http://127.0.0.1:22444'


def worker(template: Dict[str, Any], worker_id: int, step: int, found: mp.Event, out: mp.Queue, report_every: int) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    block = dict(template)
    nonce = worker_id
    hashes = 0
    started = time.time()
    difficulty = int(block['difficulty'])
    version = int(block.get('version', 2))
    winner_sent = False
    try:
        while not found.is_set():
            block['nonce'] = nonce
            digest = block_hash(block)
            hashes += 1
            if meets_work(digest, difficulty, version):
                if not found.is_set():
                    found.set()
                    winner_sent = True
                    out.put(('found', worker_id, nonce, int(block['timestamp']), digest, hashes, time.time() - started))
                break
            nonce += step
            if hashes % report_every == 0:
                # Keep nTime fresh while a difficult block is being solved.
                # Otherwise a template can be mined for an hour while retaining
                # the timestamp from when mining started, corrupting difficulty
                # timing on the next block.
                block['timestamp'] = max(int(block['timestamp']), int(time.time()))
                out.put(('stats', worker_id, hashes, time.time() - started))
    finally:
        out.put(('done', worker_id, hashes, time.time() - started, winner_sent))


def format_rate(rate: float) -> str:
    if rate >= 1_000_000:
        return f'{rate / 1_000_000:.2f} MH/s'
    if rate >= 1_000:
        return f'{rate / 1_000:.2f} kH/s'
    return f'{rate:.0f} H/s'


def mine_one(node: str, wallet_address: str, threads: int, report_every: int, miner_log: Path) -> Optional[Dict[str, Any]]:
    template_resp = request_json(node, '/mining/template?address=' + quote(wallet_address))
    template = template_resp['block']
    height = int(template['height'])
    factor = difficulty_factor(int(template['difficulty']))
    print(f'Mining block {height} at difficulty {factor:.6f}x with {threads} CPU process(es)...', flush=True)
    log_line(miner_log, f'block={height} started difficulty={factor:.6f}x threads={threads}')

    found = mp.Event()
    out: mp.Queue = mp.Queue()
    workers = [
        mp.Process(target=worker, args=(template, i, threads, found, out, report_every), daemon=True)
        for i in range(threads)
    ]
    started = time.time()
    for p in workers:
        p.start()

    hashes_by_worker = {i: 0 for i in range(threads)}
    elapsed_by_worker = {i: 0.001 for i in range(threads)}
    result = None
    last_console = 0.0
    stopped = False
    stale = False
    last_tip_check = 0.0
    try:
        while any(p.is_alive() for p in workers):
            try:
                msg = out.get(timeout=0.25)
            except queue.Empty:
                msg = None
            if msg:
                kind = msg[0]
                if kind == 'stats':
                    _, wid, hashes, elapsed = msg
                    hashes_by_worker[int(wid)] = int(hashes)
                    elapsed_by_worker[int(wid)] = max(float(elapsed), 0.001)
                elif kind == 'done':
                    _, wid, hashes, elapsed, _winner = msg
                    hashes_by_worker[int(wid)] = int(hashes)
                    elapsed_by_worker[int(wid)] = max(float(elapsed), 0.001)
                elif kind == 'found':
                    result = msg
                    break

            now = time.time()
            # On a network with multiple miners, another machine may solve the
            # block while these workers are still hashing. Poll the local node
            # and abandon stale work quickly instead of wasting CPU until we
            # eventually find a block that will be rejected.
            if now - last_tip_check >= 1.5:
                last_tip_check = now
                try:
                    status = request_json(node, '/status')
                    if int(status.get('height', -1)) >= height or int(status.get('sync_lag', 0) or 0) > 0:
                        stale = True
                        found.set()
                        print(f'Network advanced while mining block {height}; switching to the new tip...')
                        log_line(miner_log, f'block={height} stale network_height={status.get("height")} sync_lag={status.get("sync_lag", 0)}')
                        break
                except Exception:
                    pass
            if now - last_console >= 1.0:
                total_attempts = sum(hashes_by_worker.values())
                elapsed = max(0.001, now - started)
                rate = total_attempts / elapsed
                print(
                    f'Mining stats: block {height} | attempts {total_attempts:,} | '
                    f'hash rate {rate:,.0f} H/s | elapsed {elapsed:.1f}s',
                    flush=True,
                )
                last_console = now
    except KeyboardInterrupt:
        stopped = True
        print('\nMining stopped by user.')
        found.set()
    finally:
        found.set()
        for p in workers:
            p.join(timeout=2)
            if p.is_alive():
                p.terminate()
        for p in workers:
            p.join()

        # Pull final per-worker counts after every process has exited.
        while True:
            try:
                msg = out.get_nowait()
            except queue.Empty:
                break
            if msg[0] == 'done':
                _, wid, hashes, elapsed, _winner = msg
                hashes_by_worker[int(wid)] = int(hashes)
                elapsed_by_worker[int(wid)] = max(float(elapsed), 0.001)
            elif msg[0] == 'found' and result is None:
                result = msg

    if stopped:
        return None
    if stale:
        return {'accepted': False, 'stale': True, 'height': height}
    if not result:
        return None

    _, wid, nonce, solved_timestamp, digest, _winner_hashes, _winner_elapsed = result
    total_attempts = max(1, sum(hashes_by_worker.values()))
    elapsed = max(0.001, time.time() - started)
    rate = total_attempts / elapsed
    template['timestamp'] = int(solved_timestamp)
    template['nonce'] = int(nonce)

    print(f'Found block hash {digest} by worker {wid} (nonce {nonce}).', flush=True)
    print(f'Block result: attempts={total_attempts} elapsed={elapsed:.3f} hashrate={rate:.0f}', flush=True)
    log_line(
        miner_log,
        f'block={height} found hash={digest} worker={wid} nonce={nonce} attempts={total_attempts} '
        f'elapsed={elapsed:.3f}s hashrate={rate:.2f}H/s difficulty={factor:.6f}x',
    )

    try:
        response = request_json(node, '/mining/submit', method='POST', body={'block': template})
    except RuntimeError as exc:
        print(f'Block rejected: {exc}')
        log_line(miner_log, f'block={height} rejected error={exc}')
        return {'accepted': False, 'attempts': total_attempts, 'elapsed': elapsed, 'hashrate': rate, 'height': height}

    print(f'Accepted block {response["height"]}: {response["hash"]}', flush=True)
    log_line(miner_log, f'block={height} accepted hash={response["hash"]}')
    return {
        'accepted': True,
        'attempts': total_attempts,
        'elapsed': elapsed,
        'hashrate': rate,
        'height': int(response['height']),
    }


def main() -> None:
    mp.freeze_support()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    parser = argparse.ArgumentParser(description='GameCoin Mainnet CPU miner v1.0.0')
    parser.add_argument('--wallet', required=True, help='Path to the wallet receiving mining rewards')
    parser.add_argument('--node', default=DEFAULT_NODE)
    parser.add_argument('--threads', type=int, default=max(1, (os.cpu_count() or 2) // 2), help='CPU processes to use')
    parser.add_argument('--blocks', type=int, default=0, help='Number of accepted blocks to mine; 0 means continue until Ctrl+C')
    parser.add_argument('--report-every', type=int, default=5000)
    parser.add_argument('--log-dir', default='logs')
    args = parser.parse_args()
    max_threads = max(1, os.cpu_count() or 1)
    if args.threads < 1 or args.threads > max_threads:
        raise SystemExit(f'--threads must be from 1 to {max_threads} on this computer')
    if args.report_every < 100:
        raise SystemExit('--report-every must be at least 100')

    wallet = load_wallet(args.wallet)
    miner_log = Path(args.log_dir) / 'miner.log'
    reward_address = str(current_mining_record(wallet)['address'])
    print('GameCoin MAINNET CPU Miner v1.0.0', flush=True)
    print(f'Reward address: {reward_address}', flush=True)
    print(f'CPU processes: {args.threads} of {max_threads} available')
    print(f'Log file: {miner_log.resolve()}')
    print('This miner runs only while this process is open. Press Ctrl+C to stop.')
    log_line(miner_log, f'miner started address={reward_address} threads={args.threads}')

    mined = 0
    try:
        while args.blocks == 0 or mined < args.blocks:
            result = mine_one(args.node, reward_address, args.threads, args.report_every, miner_log)
            if result and result.get('accepted'):
                mined += 1
                print(f'Session blocks mined: {mined}', flush=True)
            elif result is None:
                break
            elif result and result.get('stale'):
                time.sleep(0.1)
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nMiner stopped.')
    finally:
        log_line(miner_log, f'miner stopped session_blocks={mined}')


if __name__ == '__main__':
    main()
