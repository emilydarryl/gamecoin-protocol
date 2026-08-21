#!/usr/bin/env python3
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from gamecoin.consensus import TARGET_BLOCK_SECONDS
from gamecoin.policy import DEFAULT_TRANSACTION_FEE
from gamecoin.network import NETWORK_NAME, P2P_PROTOCOL
from gamecoin.rpc import request_json
from gamecoin.utils import address_from_pubkey, tx_id, validate_address
from gamecoin.wallet_core import (
    WalletPasswordError, all_wallet_key_records, change_wallet_password, create_wallet,
    current_mining_record, current_receive_record, generate_change_address,
    generate_receive_address, is_encrypted_wallet, load_wallet, migrate_wallet_file_to_encrypted,
    public_key_for_address, save_encrypted_wallet, save_wallet, set_current_receive_index,
    sign_transaction_input, validate_new_password,
)

APP_VERSION = '1.0.0'
UPDATE_MANIFEST_URL = 'https://emilygaming.com/gamecoin/mainnet-latest.json'
DOWNLOAD_PAGE_URL = 'https://emilygaming.com/gamecoin/'

if getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).resolve().parent
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or str(Path.home())
    APP_DATA_DIR = Path(base) / 'GameCoinMainnet'
else:
    APP_DIR = Path(__file__).resolve().parent
    APP_DATA_DIR = Path(os.environ.get('GAMECOIN_DATA_HOME', str(APP_DIR)))

WALLETS_DIR = APP_DATA_DIR / 'wallets'
DATA_DIR = APP_DATA_DIR / 'data'
LOGS_DIR = APP_DATA_DIR / 'logs'
NODE_URL = 'http://127.0.0.1:22444'
COIN = 100_000_000
REFRESH_MS = 4000

for _dir in (WALLETS_DIR, DATA_DIR, LOGS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def bundled_resource(relative_path: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', APP_DIR))
    return base / relative_path


def configure_windows_app_identity() -> None:
    if os.name != 'nt':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            'EmilyGaming.GameCoin.Mainnet'
        )
    except Exception:
        pass


configure_windows_app_identity()


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for item in str(value).strip().lstrip('vV').split('.'):
        try:
            parts.append(int(item))
        except ValueError:
            digits = ''.join(ch for ch in item if ch.isdigit())
            parts.append(int(digits or 0))
    return tuple(parts)


def terminate_process_tree(proc: subprocess.Popen[str], graceful_timeout: float = 0.75) -> None:
    """Stop the miner parent and every multiprocessing worker it spawned.

    On Windows the frozen miner runs without a console, so CTRL_BREAK alone is
    not reliable. taskkill /T is used as the authoritative fallback because it
    terminates the full descendant tree instead of leaving Python worker
    processes hashing after the GUI says mining has stopped.
    """
    if proc.poll() is not None:
        return

    if os.name == 'nt':
        # Do not wait for a console control event here. The frozen miner uses
        # CREATE_NO_WINDOW and multiprocessing children can survive if the
        # parent exits before it has a chance to reap them. taskkill /T walks
        # and terminates the tree while the parent PID is still alive.
        try:
            subprocess.run(
                ['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        return

    try:
        os.killpg(proc.pid, signal.SIGINT)
        proc.wait(timeout=graceful_timeout)
        return
    except Exception:
        pass
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=1.5)
        return
    except Exception:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass



def format_amount(atoms: int) -> str:
    return f'{Decimal(int(atoms)) / COIN:.8f}'


def format_seconds(seconds: Any) -> str:
    if seconds is None:
        return '—'
    try:
        value = float(seconds)
    except Exception:
        return '—'
    if value < 60:
        return f'{value:.1f}s'
    minutes = int(value // 60)
    rem = value - minutes * 60
    if minutes < 60:
        return f'{minutes}m {rem:.0f}s'
    hours = minutes // 60
    mins = minutes % 60
    return f'{hours}h {mins}m'


def format_hashrate(rate: Any) -> str:
    try:
        value = float(rate)
    except Exception:
        return '—'
    if value >= 1_000_000_000:
        return f'{value / 1_000_000_000:.2f} GH/s'
    if value >= 1_000_000:
        return f'{value / 1_000_000:.2f} MH/s'
    if value >= 1_000:
        return f'{value / 1_000:.2f} kH/s'
    return f'{value:.0f} H/s'


def format_attempts(value: Any) -> str:
    try:
        return f'{int(float(value)):,}'
    except Exception:
        return '—'


def amount_to_atoms(text: str) -> int:
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError('Enter a valid amount.') from exc
    if value <= 0:
        raise ValueError('Amount must be greater than 0.')
    atoms = int((value * COIN).quantize(Decimal('1'), rounding=ROUND_DOWN))
    if atoms <= 0:
        raise ValueError('Amount is too small.')
    return atoms


def prompt_wallet_password(parent: tk.Misc, title: str = 'Unlock Wallet') -> Optional[str]:
    return simpledialog.askstring(title, 'Wallet password:', parent=parent, show='*')


def prompt_new_wallet_password(parent: tk.Misc, title: str = 'Set Wallet Password') -> Optional[str]:
    first = simpledialog.askstring(
        title,
        'Choose a wallet password (at least 12 characters):',
        parent=parent, show='*',
    )
    if first is None:
        return None
    validate_new_password(first)
    second = simpledialog.askstring(title, 'Confirm wallet password:', parent=parent, show='*')
    if second is None:
        return None
    if first != second:
        raise ValueError('Wallet passwords do not match.')
    return first


def save_wallet_after_secret_action(wallet: Dict[str, Any], wallet_path: Path, password: Optional[str]) -> None:
    if is_encrypted_wallet(wallet):
        if password is None:
            raise WalletPasswordError('Wallet password is required to save encrypted wallet changes.')
        save_encrypted_wallet(wallet, str(wallet_path), password)
    else:
        save_wallet(wallet, str(wallet_path))


def wallet_files() -> List[Path]:
    WALLETS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(WALLETS_DIR.glob('*.wallet.json'))


def next_wallet_path() -> Path:
    WALLETS_DIR.mkdir(parents=True, exist_ok=True)
    i = 1
    while True:
        candidate = WALLETS_DIR / f'wallet_{i:03d}.wallet.json'
        if not candidate.exists():
            return candidate
        i += 1


def node_status() -> Dict[str, Any]:
    return request_json(NODE_URL, '/status')


def balance_for(address: str) -> int:
    return int(request_json(NODE_URL, '/balance/' + quote(address))['balance'])


def wallet_balance(wallet: Dict[str, Any]) -> int:
    return sum(balance_for(str(item['address'])) for item in all_wallet_key_records(wallet))


def wallet_stats(wallet: Dict[str, Any]) -> Dict[str, int]:
    mined_blocks = 0
    mining_rewards = 0
    for item in all_wallet_key_records(wallet):
        stats = request_json(NODE_URL, '/walletstats/' + quote(str(item['address'])))
        mined_blocks += int(stats.get('mined_blocks', 0))
        mining_rewards += int(stats.get('mining_rewards', 0))
    return {'mined_blocks': mined_blocks, 'mining_rewards': mining_rewards}


def build_and_submit_transaction(wallet_path: Path, to_address: str, amount_text: str, password: Optional[str] = None) -> str:
    public_wallet = load_wallet(str(wallet_path))
    wallet = load_wallet(str(wallet_path), password) if is_encrypted_wallet(public_wallet) else public_wallet
    to_address = to_address.strip()
    if not validate_address(to_address):
        raise ValueError('Destination is not a valid GameCoin address.')
    amount = amount_to_atoms(amount_text)
    needed = amount + DEFAULT_TRANSACTION_FEE
    utxos: List[Dict[str, Any]] = []
    for record in all_wallet_key_records(wallet):
        owner = str(record['address'])
        for item in request_json(NODE_URL, '/utxos/' + quote(owner))['utxos']:
            owned = dict(item)
            owned['owner_address'] = owner
            utxos.append(owned)
    spendable_utxos = [item for item in utxos if item.get('spendable', True)]
    selected: List[Dict[str, Any]] = []
    total = 0
    for item in spendable_utxos:
        selected.append(item)
        total += int(item['amount'])
        if total >= needed:
            break
    if total < needed:
        raise ValueError(
            f'Insufficient spendable funds. Available: {format_amount(total)} GAME; '
            f'fee: {format_amount(DEFAULT_TRANSACTION_FEE)} GAME'
        )
    inputs: List[Dict[str, Any]] = []
    owners: List[str] = []
    for u in selected:
        owner = str(u['owner_address'])
        owners.append(owner)
        inputs.append({'txid': u['txid'], 'vout': int(u['vout']), 'pubkey': public_key_for_address(wallet, owner), 'signature': ''})
    outputs = [{'address': to_address, 'amount': amount}]
    change = total - amount - DEFAULT_TRANSACTION_FEE
    if change:
        wallet, change_record = generate_change_address(wallet)
        save_wallet_after_secret_action(wallet, wallet_path, password)
        outputs.append({'address': change_record['address'], 'amount': change})
    tx = {'timestamp': int(time.time()), 'inputs': inputs, 'outputs': outputs}
    for idx, owner in enumerate(owners):
        tx['inputs'][idx]['signature'] = sign_transaction_input(tx, idx, wallet, owner)
    tx['txid'] = tx_id(tx)
    response = request_json(NODE_URL, '/tx', method='POST', body={'tx': tx})
    return str(response['txid'])


def input_owned_by_addresses(inp: Dict[str, Any], addresses: set[str]) -> bool:
    try:
        pubkey = bytes.fromhex(str(inp.get('pubkey', '')))
        return address_from_pubkey(pubkey) in addresses
    except Exception:
        return False


def format_timestamp(value: Any) -> str:
    try:
        ts = int(value)
        if ts <= 0:
            return '-'
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %I:%M %p')
    except Exception:
        return '-'


def _activity_row_for_tx(
    tx: Dict[str, Any], addresses: set[str], status: str, height: Optional[int],
    confirmations: int, block_timestamp: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    outputs = tx.get('outputs', [])
    inputs = tx.get('inputs', [])
    received_outputs = [o for o in outputs if str(o.get('address', '')) in addresses]
    external_outputs = [o for o in outputs if str(o.get('address', '')) not in addresses]
    received = sum(int(o.get('amount', 0)) for o in received_outputs)
    owns_input = any(input_owned_by_addresses(inp, addresses) for inp in inputs)
    tid = str(tx.get('txid', ''))
    timestamp = int(tx.get('timestamp') or block_timestamp or 0)
    address = ''
    kind = ''
    atoms = 0

    if 'coinbase' in tx and received:
        kind = 'Mining reward'
        atoms = received
        address = str(received_outputs[0].get('address', '')) if received_outputs else ''
    elif owns_input:
        sent_elsewhere = sum(int(o.get('amount', 0)) for o in external_outputs)
        if sent_elsewhere:
            kind = 'Sent'
            atoms = -sent_elsewhere
            address = ', '.join(str(o.get('address', '')) for o in external_outputs[:2])
            if len(external_outputs) > 2:
                address += ' ...'
        elif received:
            kind = 'Self transfer'
            atoms = 0
            address = str(received_outputs[0].get('address', '')) if received_outputs else ''
        else:
            return None
    elif received:
        kind = 'Received'
        atoms = received
        address = str(received_outputs[0].get('address', '')) if received_outputs else ''
    else:
        return None

    return {
        'status': status,
        'timestamp': timestamp,
        'date': format_timestamp(timestamp),
        'type': kind,
        'amount': atoms,
        'confirmations': confirmations,
        'height': height,
        'address': address,
        'txid': tid,
    }


def _authoritative_activity_block(block: Dict[str, Any], addresses: set[str]) -> Dict[str, Any]:
    """Re-check fee-bearing wallet-mined blocks through the single-block endpoint.

    The live v4 height-101 fee test exposed one GUI refresh where the block list
    row showed the base 5 GAME subsidy even though /block/101 and wallet stats
    correctly contained the 5.001 GAME fee-bearing coinbase.  Consensus was
    correct; this helper makes the activity renderer prefer the exact stored
    block detail for the small subset of blocks where the distinction matters.
    """
    txs = list(block.get('transactions', []) or [])
    if len(txs) <= 1:
        return block
    coinbase = txs[0] if txs else {}
    if 'coinbase' not in coinbase:
        return block
    pays_wallet = any(str(o.get('address', '')) in addresses for o in coinbase.get('outputs', []))
    if not pays_wallet:
        return block
    try:
        height = int(block.get('height', -1))
        if height < 0:
            return block
        detail = request_json(NODE_URL, f'/block/{height}').get('block')
        if not isinstance(detail, dict) or int(detail.get('height', -1)) != height:
            return block
        listed_hash = str(block.get('hash', '') or '')
        detail_hash = str(detail.get('hash', '') or '')
        if listed_hash and detail_hash and listed_hash != detail_hash:
            return block
        return detail
    except Exception:
        return block


def recent_activity(wallet: Dict[str, Any], current_height: int, limit: int = 100) -> List[Dict[str, Any]]:
    addresses = {str(item['address']) for item in all_wallet_key_records(wallet)}
    rows: List[Dict[str, Any]] = []

    try:
        mempool = request_json(NODE_URL, '/mempool?limit=250').get('transactions', [])
    except Exception:
        mempool = []
    for tx in reversed(mempool):
        row = _activity_row_for_tx(tx, addresses, 'Pending', None, 0)
        if row:
            rows.append(row)

    blocks = request_json(NODE_URL, f'/blocks?limit={max(1, min(limit, 100))}')['blocks']
    for listed_block in reversed(blocks):
        block = _authoritative_activity_block(listed_block, addresses)
        height = int(block.get('height', 0))
        confirmations = max(1, current_height - height + 1)
        block_timestamp = int(block.get('timestamp', 0) or 0)
        for tx in reversed(block.get('transactions', [])):
            row = _activity_row_for_tx(tx, addresses, 'Confirmed', height, confirmations, block_timestamp)
            if row:
                rows.append(row)
    return rows


class WalletApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f'GameCoin Mainnet Wallet v{APP_VERSION}')
        self.geometry('1280x820')
        self.minsize(1050, 680)
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        try:
            icon_path = bundled_resource('assets/gamecoin_protocol_mark.ico')
            if os.name == 'nt' and icon_path.exists():
                self.iconbitmap(default=str(icon_path))
        except Exception:
            pass

        self.wallet_map: Dict[str, Path] = {}
        self.receive_map: Dict[str, int] = {}
        self.current_wallet: Optional[Path] = None
        self.current_wallet_data: Optional[Dict[str, Any]] = None
        self.current_address = ''
        self.node_process: Optional[subprocess.Popen[str]] = None
        self.node_started_by_gui = False
        self.miner_process: Optional[subprocess.Popen[str]] = None
        self.miner_reader_thread: Optional[threading.Thread] = None
        self.miner_queue: 'queue.Queue[str]' = queue.Queue()
        self._closing = False
        self._refresh_in_progress = False

        self.wallet_var = tk.StringVar()
        self.receive_choice_var = tk.StringVar()
        self.address_var = tk.StringVar(value='—')
        self.mining_address_var = tk.StringVar(value='Reward address: —')
        self.balance_var = tk.StringVar(value='0.00000000 GAME')
        self.wallet_mined_var = tk.StringVar(value='Blocks mined by wallet: —')
        self.wallet_rewards_var = tk.StringVar(value='Mining rewards earned: —')
        self.node_var = tk.StringVar(value='Node: checking...')
        self.node_detail_var = tk.StringVar(value='Local node: checking...')
        self.height_var = tk.StringVar(value='Height: —')
        self.difficulty_var = tk.StringVar(value='Current difficulty: —')
        self.next_difficulty_var = tk.StringVar(value='Next difficulty: —')
        self.needed_difficulty_var = tk.StringVar(value='Estimated needed: —')
        self.difficulty_status_var = tk.StringVar(value='Difficulty status: —')
        self.target_time_var = tk.StringVar(value='Target block time: —')
        self.avg_time_var = tk.StringVar(value='Average last 20: —')
        self.active_avg_var = tk.StringVar(value='Adjustment average: —')
        self.last_time_var = tk.StringVar(value='Last block time: —')
        self.network_rate_var = tk.StringVar(value='Estimated network rate: —')
        self.expected_attempts_var = tk.StringVar(value='Expected next attempts: —')
        self.ramp_limit_var = tk.StringVar(value='Max increase this block: —')
        self.sync_status_var = tk.StringVar(value='Sync: —')
        self.network_height_var = tk.StringVar(value='Network height: —')
        self.peer_count_var = tk.StringVar(value='Peers: —')
        self.primary_peer_var = tk.StringVar(value='Seed: —')
        self.network_id_var = tk.StringVar(value=f'Network: {NETWORK_NAME}')
        self.version_var = tk.StringVar(value=f'App version: {APP_VERSION}')
        self.update_var = tk.StringVar(value='Update: checking...')
        self.update_download_url = DOWNLOAD_PAGE_URL
        self.mempool_var = tk.StringVar(value='Network mempool: -')
        self.block_reward_var = tk.StringVar(value='Block reward: —')
        self.circulating_supply_var = tk.StringVar(value='Circulating supply: —')
        self.max_supply_var = tk.StringVar(value='Maximum supply: —')
        self.halving_var = tk.StringVar(value='Next halving: —')
        self.wallet_pending_var = tk.StringVar(value='Wallet pending: 0')
        self.transaction_rows_by_iid: Dict[str, Dict[str, Any]] = {}
        self.sync_progress_var = tk.DoubleVar(value=0.0)
        self.sync_progress_text_var = tk.StringVar(value='Sync progress: waiting for local node...')
        self.node_synced = False

        self.miner_status_var = tk.StringVar(value='GUI miner: stopped')
        self.hashrate_var = tk.StringVar(value='Hash rate: —')
        self.attempts_var = tk.StringVar(value='Attempts this block: —')
        self.elapsed_var = tk.StringVar(value='Elapsed this block: —')
        self.session_blocks_var = tk.StringVar(value='Blocks this session: 0')
        self.last_block_var = tk.StringVar(value='Last block: —')
        self.threads_var = tk.IntVar(value=max(1, min(2, os.cpu_count() or 1)))
        self.to_var = tk.StringVar()
        self.amount_var = tk.StringVar()

        self._build_ui()
        self.reload_wallets()
        self.after(100, self._drain_miner_queue)
        # Bitcoin-Core-like startup flow: opening the wallet starts the local
        # node, and the node immediately begins syncing from configured peers.
        self.after(250, lambda: self.start_node(automatic=True))
        self.after(900, self.refresh_async)
        self.after(1400, self.check_for_updates_async)
        if not self.wallet_map:
            self.after(650, self.first_run_prompt)

    def _build_ui(self) -> None:
        # EmilyGaming-inspired palette: pink, cyan, purple, amber, lime and soft cream.
        colors = {
            'bg': '#fff7ed',
            'surface': '#ffffff',
            'ink': '#24324a',
            'muted': '#64748b',
            'pink': '#d946ef',
            'pink_dark': '#a21caf',
            'cyan': '#38bdf8',
            'cyan_dark': '#0369a1',
            'purple': '#7c3aed',
            'purple_dark': '#5b21b6',
            'amber': '#fbbf24',
            'lime': '#84cc16',
            'red': '#8b1f24',
            'border': '#e9d5ff',
            'soft_purple': '#f5f3ff',
            'soft_cyan': '#ecfeff',
            'soft_pink': '#fdf2f8',
            'soft_amber': '#fffbeb',
        }
        self.configure(bg=colors['bg'])
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TFrame', background=colors['bg'])
        style.configure('TLabel', background=colors['bg'], foreground=colors['ink'])
        style.configure('TLabelframe', background=colors['bg'], bordercolor=colors['border'])
        style.configure('TLabelframe.Label', background=colors['bg'], foreground=colors['purple_dark'], font=('Segoe UI', 10, 'bold'))
        style.configure('TNotebook', background=colors['bg'], borderwidth=0, tabmargins=(0, 8, 0, 0))
        style.configure('TNotebook.Tab', padding=(18, 10), background='#ede9fe', foreground=colors['purple_dark'], font=('Segoe UI', 10, 'bold'))
        style.map('TNotebook.Tab', background=[('selected', colors['pink'])], foreground=[('selected', '#ffffff')])
        style.configure('Accent.TButton', background=colors['pink'], foreground='#ffffff', borderwidth=0, padding=(14, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', colors['pink_dark'])])
        style.configure('Sky.TButton', background=colors['cyan'], foreground='#10233f', borderwidth=0, padding=(14, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Sky.TButton', background=[('active', '#0ea5e9')])
        style.configure('Purple.TButton', background=colors['purple'], foreground='#ffffff', borderwidth=0, padding=(14, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Purple.TButton', background=[('active', colors['purple_dark'])])
        style.configure('Amber.TButton', background=colors['amber'], foreground='#422006', borderwidth=0, padding=(14, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Amber.TButton', background=[('active', '#f59e0b')])
        style.configure('Lime.TButton', background=colors['lime'], foreground='#1a2e05', borderwidth=0, padding=(14, 8), font=('Segoe UI', 10, 'bold'))
        style.map('Lime.TButton', background=[('active', '#65a30d')])
        style.configure('Treeview', rowheight=28, background='#ffffff', fieldbackground='#ffffff', foreground=colors['ink'])
        style.configure('Treeview.Heading', background='#ede9fe', foreground=colors['purple_dark'], font=('Segoe UI', 9, 'bold'), padding=(6, 7))
        style.map('Treeview', background=[('selected', colors['cyan'])], foreground=[('selected', '#10233f')])
        style.configure('Emily.Horizontal.TProgressbar', troughcolor='#e0f2fe', background=colors['lime'], bordercolor='#bae6fd')

        outer = tk.Frame(self, bg=colors['bg'], padx=16, pady=12)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        header = tk.Frame(outer, bg=colors['surface'], padx=16, pady=12, highlightthickness=1, highlightbackground='#f5d0fe')
        header.grid(row=0, column=0, sticky='ew')
        header.columnconfigure(1, weight=1)
        logo = tk.Frame(header, bg=colors['surface'])
        logo.grid(row=0, column=0, sticky='w')
        tk.Label(logo, text='GAMECOIN', bg=colors['surface'], fg=colors['pink_dark'], font=('Segoe UI', 21, 'bold')).pack(side='left')
        tk.Label(logo, text=f'  MAINNET v{APP_VERSION}', bg=colors['surface'], fg=colors['cyan_dark'], font=('Segoe UI', 10, 'bold')).pack(side='left', pady=(7, 0))
        node_controls = tk.Frame(header, bg=colors['surface'])
        node_controls.grid(row=0, column=2, sticky='e')
        tk.Label(node_controls, textvariable=self.node_var, bg=colors['surface'], fg=colors['purple_dark'], font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 10))
        self.start_node_button = ttk.Button(node_controls, text='Start Node', command=self.start_node, style='Sky.TButton')
        self.start_node_button.pack(side='left')
        self.stop_node_button = ttk.Button(node_controls, text='Stop Node', command=self.stop_node, style='Purple.TButton', state='disabled')
        self.stop_node_button.pack(side='left', padx=(7, 0))

        wallet_bar = tk.Frame(outer, bg='#ffffff', padx=12, pady=9, highlightthickness=1, highlightbackground='#e0e7ff')
        wallet_bar.grid(row=1, column=0, sticky='ew', pady=(9, 0))
        wallet_bar.columnconfigure(1, weight=1)
        tk.Label(wallet_bar, text='Wallet', bg='#ffffff', fg=colors['ink'], font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, sticky='w')
        self.wallet_combo = ttk.Combobox(wallet_bar, textvariable=self.wallet_var, state='readonly', width=34)
        self.wallet_combo.grid(row=0, column=1, sticky='ew', padx=(10, 10))
        self.wallet_combo.bind('<<ComboboxSelected>>', lambda _e: self.select_wallet())
        actions = tk.Frame(wallet_bar, bg='#ffffff')
        actions.grid(row=0, column=2, sticky='e')
        ttk.Button(actions, text='Create New', command=self.create_new_wallet, style='Accent.TButton').pack(side='left')
        ttk.Button(actions, text='Import', command=self.import_wallet).pack(side='left', padx=(6, 0))
        ttk.Button(actions, text='Backup', command=self.backup_wallet).pack(side='left', padx=(6, 0))
        ttk.Button(actions, text='Security', command=self.wallet_security).pack(side='left', padx=(6, 0))
        ttk.Button(actions, text='Wallet Folder', command=self.open_wallet_folder).pack(side='left', padx=(6, 0))
        ttk.Button(actions, text='Refresh', command=self.refresh_async).pack(side='left', padx=(6, 0))

        banner = tk.Label(
            outer,
            text='GAMECOIN MAINNET - REAL NETWORK - VERIFY ADDRESSES AND BACK UP YOUR WALLET',
            bg=colors['red'], fg='white', font=('Segoe UI', 10, 'bold'), padx=10, pady=6,
        )
        banner.grid(row=2, column=0, sticky='ew', pady=(8, 0))

        self.notebook = ttk.Notebook(outer)
        self.notebook.grid(row=3, column=0, sticky='nsew', pady=(4, 0))

        self.overview_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.send_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.receive_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.transactions_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.mining_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.network_tab = tk.Frame(self.notebook, bg=colors['bg'], padx=14, pady=14)
        self.notebook.add(self.overview_tab, text='Overview')
        self.notebook.add(self.send_tab, text='Send')
        self.notebook.add(self.receive_tab, text='Receive')
        self.notebook.add(self.transactions_tab, text='Transactions')
        self.notebook.add(self.mining_tab, text='Mining')
        self.notebook.add(self.network_tab, text='Network')

        def value_card(parent: tk.Widget, title: str, variable: tk.StringVar, accent: str, column: int) -> None:
            frame = tk.Frame(parent, bg='#ffffff', padx=16, pady=13, highlightthickness=2, highlightbackground=accent)
            frame.grid(row=0, column=column, sticky='nsew', padx=(0 if column == 0 else 7, 0))
            tk.Label(frame, text=title, bg='#ffffff', fg=colors['muted'], font=('Segoe UI', 9, 'bold')).pack(anchor='w')
            tk.Label(frame, textvariable=variable, bg='#ffffff', fg=colors['ink'], font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(4, 0))

        # Overview
        for c in range(4):
            self.overview_tab.columnconfigure(c, weight=1)
        self.overview_tab.rowconfigure(3, weight=1)
        value_card(self.overview_tab, 'COMBINED BALANCE', self.balance_var, colors['pink'], 0)
        value_card(self.overview_tab, 'WALLET MINING', self.wallet_mined_var, colors['cyan'], 1)
        value_card(self.overview_tab, 'MINING REWARDS', self.wallet_rewards_var, colors['purple'], 2)
        value_card(self.overview_tab, 'CHAIN HEIGHT', self.height_var, colors['amber'], 3)

        status_strip = tk.Frame(self.overview_tab, bg='#ffffff', padx=14, pady=10, highlightthickness=1, highlightbackground='#dbeafe')
        status_strip.grid(row=1, column=0, columnspan=4, sticky='ew', pady=(12, 10))
        tk.Label(status_strip, textvariable=self.sync_status_var, bg='#ffffff', fg='#15803d', font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Label(status_strip, text='  |  ', bg='#ffffff', fg=colors['muted']).pack(side='left')
        tk.Label(status_strip, textvariable=self.peer_count_var, bg='#ffffff', fg=colors['cyan_dark'], font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Label(status_strip, text='  |  ', bg='#ffffff', fg=colors['muted']).pack(side='left')
        tk.Label(status_strip, textvariable=self.wallet_pending_var, bg='#ffffff', fg=colors['purple_dark'], font=('Segoe UI', 10, 'bold')).pack(side='left')
        tk.Label(status_strip, textvariable=self.node_detail_var, bg='#ffffff', fg=colors['muted'], font=('Segoe UI', 9)).pack(side='right')

        tk.Label(self.overview_tab, text='Recent wallet activity', bg=colors['bg'], fg=colors['purple_dark'], font=('Segoe UI', 13, 'bold')).grid(row=2, column=0, columnspan=4, sticky='w', pady=(0, 7))
        overview_box = tk.Frame(self.overview_tab, bg='#ffffff', highlightthickness=1, highlightbackground='#e9d5ff')
        overview_box.grid(row=3, column=0, columnspan=4, sticky='nsew')
        overview_box.rowconfigure(0, weight=1)
        overview_box.columnconfigure(0, weight=1)
        ocols = ('status', 'date', 'type', 'amount', 'confirmations')
        self.overview_tree = ttk.Treeview(overview_box, columns=ocols, show='headings', height=10)
        for key, title, width, anchor in [
            ('status', 'Status', 95, 'center'), ('date', 'Date / Time', 175, 'w'), ('type', 'Type', 130, 'w'),
            ('amount', 'Amount', 150, 'e'), ('confirmations', 'Confirmations', 110, 'center')]:
            self.overview_tree.heading(key, text=title)
            self.overview_tree.column(key, width=width, anchor=anchor, stretch=(key == 'date'))
        self.overview_tree.grid(row=0, column=0, sticky='nsew')
        oscroll = ttk.Scrollbar(overview_box, orient='vertical', command=self.overview_tree.yview)
        self.overview_tree.configure(yscrollcommand=oscroll.set)
        oscroll.grid(row=0, column=1, sticky='ns')

        # Send
        self.send_tab.columnconfigure(0, weight=1)
        send_card = tk.Frame(self.send_tab, bg='#ffffff', padx=24, pady=22, highlightthickness=2, highlightbackground=colors['pink'])
        send_card.grid(row=0, column=0, sticky='new')
        send_card.columnconfigure(1, weight=1)
        tk.Label(send_card, text='Send GAME', bg='#ffffff', fg=colors['pink_dark'], font=('Segoe UI', 18, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        tk.Label(send_card, text='Recipient address', bg='#ffffff', fg=colors['ink'], font=('Segoe UI', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=(22, 0))
        ttk.Entry(send_card, textvariable=self.to_var, font=('Segoe UI', 11)).grid(row=1, column=1, sticky='ew', padx=(14, 0), pady=(22, 0))
        tk.Label(send_card, text='Amount', bg='#ffffff', fg=colors['ink'], font=('Segoe UI', 10, 'bold')).grid(row=2, column=0, sticky='w', pady=(16, 0))
        amount_row = tk.Frame(send_card, bg='#ffffff')
        amount_row.grid(row=2, column=1, sticky='ew', padx=(14, 0), pady=(16, 0))
        amount_row.columnconfigure(0, weight=1)
        ttk.Entry(amount_row, textvariable=self.amount_var, font=('Segoe UI', 11)).grid(row=0, column=0, sticky='ew')
        tk.Label(amount_row, text='GAME', bg='#ffffff', fg=colors['purple_dark'], font=('Segoe UI', 10, 'bold')).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(send_card, text='Send GAME', command=self.send_clicked, style='Accent.TButton').grid(row=3, column=1, sticky='e', pady=(22, 0))
        tk.Label(send_card, text=f'Default network fee: {format_amount(DEFAULT_TRANSACTION_FEE)} GAME. Fees are paid to the miner that confirms the transaction. A send is Pending until a miner includes it in a block.', bg='#ffffff', fg=colors['muted'], wraplength=850, justify='left').grid(row=4, column=0, columnspan=2, sticky='w', pady=(20, 0))

        # Receive
        self.receive_tab.columnconfigure(0, weight=1)
        receive_card = tk.Frame(self.receive_tab, bg='#ffffff', padx=24, pady=22, highlightthickness=2, highlightbackground=colors['cyan'])
        receive_card.grid(row=0, column=0, sticky='new')
        receive_card.columnconfigure(0, weight=1)
        tk.Label(receive_card, text='Receive GAME', bg='#ffffff', fg=colors['cyan_dark'], font=('Segoe UI', 18, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        tk.Label(receive_card, text='Current receive address', bg='#ffffff', fg=colors['muted'], font=('Segoe UI', 9, 'bold')).grid(row=1, column=0, columnspan=3, sticky='w', pady=(20, 5))
        address_entry = ttk.Entry(receive_card, textvariable=self.address_var, state='readonly', font=('Consolas', 11))
        address_entry.grid(row=2, column=0, sticky='ew')
        ttk.Button(receive_card, text='Copy Address', command=self.copy_address, style='Sky.TButton').grid(row=2, column=1, padx=(9, 0))
        ttk.Button(receive_card, text='New Address', command=self.new_receive_address, style='Accent.TButton').grid(row=2, column=2, padx=(9, 0))
        tk.Label(receive_card, text='Address history', bg='#ffffff', fg=colors['muted'], font=('Segoe UI', 9, 'bold')).grid(row=3, column=0, columnspan=3, sticky='w', pady=(22, 5))
        self.receive_combo = ttk.Combobox(receive_card, textvariable=self.receive_choice_var, state='readonly')
        self.receive_combo.grid(row=4, column=0, columnspan=3, sticky='ew')
        self.receive_combo.bind('<<ComboboxSelected>>', lambda _e: self.select_receive_address())
        tk.Label(receive_card, text='Each new receive address belongs to this same wallet. Old receive addresses remain valid.', bg='#ffffff', fg=colors['muted']).grid(row=5, column=0, columnspan=3, sticky='w', pady=(14, 0))

        # Transactions
        self.transactions_tab.columnconfigure(0, weight=1)
        self.transactions_tab.rowconfigure(1, weight=1)
        tx_top = tk.Frame(self.transactions_tab, bg=colors['bg'])
        tx_top.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        tk.Label(tx_top, text='Transactions', bg=colors['bg'], fg=colors['purple_dark'], font=('Segoe UI', 18, 'bold')).pack(side='left')
        tk.Label(tx_top, textvariable=self.wallet_pending_var, bg=colors['bg'], fg=colors['pink_dark'], font=('Segoe UI', 10, 'bold')).pack(side='left', padx=(16, 0), pady=(5, 0))
        ttk.Button(tx_top, text='Refresh', command=self.refresh_async, style='Sky.TButton').pack(side='right')
        ttk.Button(tx_top, text='View Details', command=self.show_transaction_details).pack(side='right', padx=(0, 7))
        tx_box = tk.Frame(self.transactions_tab, bg='#ffffff', highlightthickness=1, highlightbackground='#ddd6fe')
        tx_box.grid(row=1, column=0, sticky='nsew')
        tx_box.rowconfigure(0, weight=1)
        tx_box.columnconfigure(0, weight=1)
        columns = ('status', 'date', 'type', 'amount', 'confirmations', 'address', 'txid')
        self.activity_tree = ttk.Treeview(tx_box, columns=columns, show='headings', height=16)
        specs = [
            ('status', 'Status', 90, 'center'), ('date', 'Date / Time', 155, 'w'), ('type', 'Type', 115, 'w'),
            ('amount', 'Amount', 135, 'e'), ('confirmations', 'Conf.', 65, 'center'), ('address', 'Address', 275, 'w'),
            ('txid', 'Transaction ID', 310, 'w')]
        for key, title, width, anchor in specs:
            self.activity_tree.heading(key, text=title)
            self.activity_tree.column(key, width=width, anchor=anchor, stretch=(key in ('address', 'txid')))
        self.activity_tree.tag_configure('pending', background=colors['soft_amber'])
        self.activity_tree.tag_configure('mining', background='#f0fdf4')
        self.activity_tree.tag_configure('sent', background=colors['soft_pink'])
        self.activity_tree.tag_configure('received', background=colors['soft_cyan'])
        self.activity_tree.bind('<Double-1>', lambda _e: self.show_transaction_details())
        tx_scroll_y = ttk.Scrollbar(tx_box, orient='vertical', command=self.activity_tree.yview)
        tx_scroll_x = ttk.Scrollbar(tx_box, orient='horizontal', command=self.activity_tree.xview)
        self.activity_tree.configure(yscrollcommand=tx_scroll_y.set, xscrollcommand=tx_scroll_x.set)
        self.activity_tree.grid(row=0, column=0, sticky='nsew')
        tx_scroll_y.grid(row=0, column=1, sticky='ns')
        tx_scroll_x.grid(row=1, column=0, sticky='ew')

        # Mining
        self.mining_tab.columnconfigure(0, weight=1)
        mining_card = tk.Frame(self.mining_tab, bg='#ffffff', padx=24, pady=22, highlightthickness=2, highlightbackground=colors['lime'])
        mining_card.grid(row=0, column=0, sticky='new')
        mining_card.columnconfigure(1, weight=1)
        tk.Label(mining_card, text='CPU Mining', bg='#ffffff', fg='#4d7c0f', font=('Segoe UI', 18, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        tk.Label(mining_card, text='CPU processes', bg='#ffffff', fg=colors['ink'], font=('Segoe UI', 10, 'bold')).grid(row=1, column=0, sticky='w', pady=(20, 0))
        max_threads = max(1, os.cpu_count() or 1)
        ttk.Spinbox(mining_card, from_=1, to=max_threads, textvariable=self.threads_var, width=7).grid(row=1, column=1, sticky='w', padx=(12, 0), pady=(20, 0))
        tk.Label(mining_card, textvariable=self.mining_address_var, bg='#ffffff', fg=colors['muted'], font=('Consolas', 9)).grid(row=2, column=0, columnspan=2, sticky='w', pady=(12, 0))
        stats = tk.Frame(mining_card, bg=colors['soft_purple'], padx=15, pady=15)
        stats.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(18, 0))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        tk.Label(stats, textvariable=self.miner_status_var, bg=colors['soft_purple'], fg=colors['purple_dark'], font=('Segoe UI', 10, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        tk.Label(stats, textvariable=self.hashrate_var, bg=colors['soft_purple'], fg=colors['ink']).grid(row=1, column=0, sticky='w', pady=(9, 0))
        tk.Label(stats, textvariable=self.attempts_var, bg=colors['soft_purple'], fg=colors['ink']).grid(row=1, column=1, sticky='w', pady=(9, 0))
        tk.Label(stats, textvariable=self.elapsed_var, bg=colors['soft_purple'], fg=colors['ink']).grid(row=2, column=0, sticky='w', pady=(6, 0))
        tk.Label(stats, textvariable=self.session_blocks_var, bg=colors['soft_purple'], fg=colors['ink']).grid(row=2, column=1, sticky='w', pady=(6, 0))
        tk.Label(stats, textvariable=self.last_block_var, bg=colors['soft_purple'], fg=colors['ink']).grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
        mine_buttons = tk.Frame(mining_card, bg='#ffffff')
        mine_buttons.grid(row=4, column=0, columnspan=2, sticky='w', pady=(18, 0))
        self.start_mining_button = ttk.Button(mine_buttons, text='Start Mining', command=self.start_mining, style='Lime.TButton', state='disabled')
        self.start_mining_button.pack(side='left')
        self.stop_mining_button = ttk.Button(mine_buttons, text='Stop Mining', command=self.stop_mining, style='Purple.TButton', state='disabled')
        self.stop_mining_button.pack(side='left', padx=(8, 0))
        ttk.Button(mine_buttons, text='Open Logs', command=self.open_logs).pack(side='left', padx=(8, 0))

        # Network
        self.network_tab.columnconfigure(0, weight=1)
        network = tk.Frame(self.network_tab, bg='#ffffff', padx=20, pady=18, highlightthickness=2, highlightbackground=colors['purple'])
        network.grid(row=0, column=0, sticky='new')
        for col in range(4):
            network.columnconfigure(col, weight=1)
        tk.Label(network, text='Network and Difficulty', bg='#ffffff', fg=colors['purple_dark'], font=('Segoe UI', 18, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 16))
        labels = [
            (self.difficulty_var, 1, 0), (self.next_difficulty_var, 1, 1), (self.needed_difficulty_var, 1, 2), (self.difficulty_status_var, 1, 3),
            (self.target_time_var, 2, 0), (self.avg_time_var, 2, 1), (self.active_avg_var, 2, 2), (self.last_time_var, 2, 3),
            (self.network_rate_var, 3, 0), (self.expected_attempts_var, 3, 1), (self.ramp_limit_var, 3, 2), (self.mempool_var, 3, 3),
            (self.sync_status_var, 4, 0), (self.network_height_var, 4, 1), (self.peer_count_var, 4, 2), (self.primary_peer_var, 4, 3),
        ]
        for var, row, col in labels:
            tk.Label(network, textvariable=var, bg='#ffffff', fg=colors['ink'], anchor='w', font=('Segoe UI', 9, 'bold' if var in (self.difficulty_status_var, self.sync_status_var) else 'normal')).grid(row=row, column=col, sticky='w', padx=(0, 10), pady=(5, 0))

        policy = tk.Frame(network, bg=colors['soft_amber'], padx=13, pady=11, highlightthickness=1, highlightbackground='#fde68a')
        policy.grid(row=5, column=0, columnspan=4, sticky='ew', pady=(18, 0))
        for col in range(4):
            policy.columnconfigure(col, weight=1)
        tk.Label(policy, text='MONETARY POLICY', bg=colors['soft_amber'], fg='#92400e', font=('Segoe UI', 9, 'bold')).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 6))
        for var, col in ((self.block_reward_var, 0), (self.circulating_supply_var, 1), (self.max_supply_var, 2), (self.halving_var, 3)):
            tk.Label(policy, textvariable=var, bg=colors['soft_amber'], fg=colors['ink'], anchor='w', justify='left', font=('Segoe UI', 9, 'bold')).grid(row=1, column=col, sticky='w', padx=(0, 10))

        self.sync_progress = ttk.Progressbar(network, maximum=100.0, variable=self.sync_progress_var, style='Emily.Horizontal.TProgressbar')
        self.sync_progress.grid(row=6, column=0, columnspan=4, sticky='ew', pady=(18, 0))
        tk.Label(network, textvariable=self.sync_progress_text_var, bg='#ffffff', fg=colors['muted']).grid(row=7, column=0, columnspan=4, sticky='w', pady=(5, 0))
        info = tk.Frame(network, bg='#ffffff')
        info.grid(row=8, column=0, columnspan=4, sticky='ew', pady=(18, 0))
        tk.Label(info, textvariable=self.network_id_var, bg='#ffffff', fg=colors['cyan_dark'], font=('Segoe UI', 9, 'bold')).pack(side='left')
        tk.Label(info, textvariable=self.version_var, bg='#ffffff', fg=colors['purple_dark'], font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(22, 0))
        tk.Label(info, textvariable=self.update_var, bg='#ffffff', fg=colors['pink_dark'], font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(22, 0))
        ttk.Button(info, text='Download Page', command=self.open_download_page, style='Accent.TButton').pack(side='right')
        ttk.Button(info, text='Check Updates', command=self.check_for_updates_async, style='Sky.TButton').pack(side='right', padx=(0, 7))
        ttk.Button(info, text='About', command=self.show_about, style='Purple.TButton').pack(side='right', padx=(0, 7))

        footer = tk.Label(outer, text=f'MAINNET - 5 GAME initial reward - ~10 year halvings - encrypted wallets. Network: {NETWORK_NAME}.', bg=colors['bg'], fg=colors['muted'], font=('Segoe UI', 8))
        footer.grid(row=4, column=0, sticky='w', pady=(7, 0))

    def show_about(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(f'About GameCoin v{APP_VERSION}')
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.configure(bg='#071a3a')
        try:
            icon_path = bundled_resource('assets/gamecoin_protocol_mark.ico')
            if os.name == 'nt' and icon_path.exists():
                dialog.iconbitmap(default=str(icon_path))
        except Exception:
            pass

        frame = tk.Frame(dialog, bg='#071a3a', padx=28, pady=24)
        frame.pack(fill='both', expand=True)
        try:
            logo_path = bundled_resource('assets/gamecoin_protocol_full.png')
            image = tk.PhotoImage(file=str(logo_path))
            max_side = 250
            divisor = max(1, int(max(image.width(), image.height()) / max_side))
            if divisor > 1:
                image = image.subsample(divisor, divisor)
            logo = tk.Label(frame, image=image, bg='#071a3a')
            logo.image = image
            logo.pack(pady=(0, 14))
        except Exception:
            tk.Label(frame, text='GAMECOIN PROTOCOL', bg='#071a3a', fg='#22d3ee',
                     font=('Segoe UI', 20, 'bold')).pack(pady=(0, 14))

        tk.Label(frame, text=f'GameCoin Mainnet v{APP_VERSION}', bg='#071a3a', fg='white',
                 font=('Segoe UI', 16, 'bold')).pack()
        details = (
            f'Network: {NETWORK_NAME}\n'
            f'P2P protocol: {P2P_PROTOCOL}\n'
            'Genesis: 0c47cce8ff7bd89c7eacd298299e6259c249be87c569c4939784952cdfb5f304\n'
            'Block target: 2 minutes 30 seconds\n'
            'Initial reward: 5 GAME'
        )
        tk.Label(frame, text=details, justify='left', bg='#071a3a', fg='#bae6fd',
                 font=('Consolas', 9)).pack(pady=(12, 18))
        ttk.Button(frame, text='Close', command=dialog.destroy, style='Sky.TButton').pack()
        dialog.grab_set()
        dialog.update_idletasks()
        x = self.winfo_rootx() + max(20, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_rooty() + max(20, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f'+{x}+{y}')

    def _receive_display(self, item: Dict[str, Any]) -> str:
        label = str(item.get('label') or f'Receive {item.get("index", 0)}')
        return f'#{int(item.get("index", 0))}  {label}  —  {item.get("address", "")}'

    def _load_receive_choices(self, wallet: Dict[str, Any]) -> None:
        self.receive_map = {}
        values: List[str] = []
        current_index = int(wallet.get('current_receive_index', 0))
        selected = ''
        for item in wallet.get('receive_addresses', []):
            display = self._receive_display(item)
            values.append(display)
            self.receive_map[display] = int(item['index'])
            if int(item['index']) == current_index:
                selected = display
        self.receive_combo['values'] = values
        if not selected and values:
            selected = values[-1]
        self.receive_choice_var.set(selected)
        if selected:
            index = self.receive_map[selected]
            item = next(x for x in wallet['receive_addresses'] if int(x['index']) == index)
            self.current_address = str(item['address'])
            self.address_var.set(self.current_address)
        mining = current_mining_record(wallet)
        self.mining_address_var.set(f'Reward address: {mining["address"]}')

    def reload_wallets(self, select_name: Optional[str] = None) -> None:
        paths = wallet_files()
        self.wallet_map = {p.name: p for p in paths}
        names = list(self.wallet_map)
        self.wallet_combo['values'] = names
        if not names:
            self.wallet_var.set('')
            self.current_wallet = None
            self.current_wallet_data = None
            self.current_address = ''
            self.address_var.set('No wallet files found')
            self.receive_combo['values'] = []
            self.receive_choice_var.set('')
            self.mining_address_var.set('Reward address: —')
            self.balance_var.set('0.00000000 GAME')
            if hasattr(self, 'start_mining_button'):
                self._update_mining_buttons()
            return
        if select_name not in self.wallet_map:
            select_name = self.wallet_var.get() if self.wallet_var.get() in self.wallet_map else names[0]
        self.wallet_var.set(select_name)
        self.select_wallet(refresh=False)
        if hasattr(self, 'start_mining_button'):
            self._update_mining_buttons()

    def select_wallet(self, refresh: bool = True) -> None:
        name = self.wallet_var.get()
        path = self.wallet_map.get(name)
        if not path:
            return
        try:
            wallet = load_wallet(str(path))
            self.current_wallet = path
            self.current_wallet_data = wallet
            self._load_receive_choices(wallet)
            self._update_mining_buttons()
            if refresh:
                self.refresh_async()
        except Exception as exc:
            messagebox.showerror('Wallet Error', str(exc), parent=self)

    def select_receive_address(self) -> None:
        if not self.current_wallet:
            return
        display = self.receive_choice_var.get()
        index = self.receive_map.get(display)
        if index is None:
            return
        try:
            wallet = load_wallet(str(self.current_wallet))
            wallet = set_current_receive_index(wallet, index)
            save_wallet(wallet, str(self.current_wallet))
            self.current_wallet_data = wallet
            self._load_receive_choices(wallet)
        except Exception as exc:
            messagebox.showerror('Receive Address Error', str(exc), parent=self)

    def new_receive_address(self) -> None:
        if not self.current_wallet:
            messagebox.showwarning('No Wallet', 'Select or create a wallet first.', parent=self)
            return
        label = simpledialog.askstring('New Receive Address', 'Optional label for this receive address:', parent=self)
        if label is None:
            return
        try:
            public_wallet = load_wallet(str(self.current_wallet))
            password: Optional[str] = None
            wallet = public_wallet
            if is_encrypted_wallet(public_wallet):
                password = prompt_wallet_password(self, 'Unlock Wallet to Create Address')
                if password is None:
                    return
                wallet = load_wallet(str(self.current_wallet), password)
            wallet, item = generate_receive_address(wallet, label.strip())
            save_wallet_after_secret_action(wallet, self.current_wallet, password)
            self.current_wallet_data = wallet
            self._load_receive_choices(wallet)
            self.clipboard_clear()
            self.clipboard_append(str(item['address']))
            self.update_idletasks()
            messagebox.showinfo(
                'Receive Address Created',
                f'New receive address:\n\n{item["address"]}\n\nThe address has been copied to the clipboard. Back up your wallet file after creating new addresses.',
                parent=self,
            )
            self.refresh_async()
        except Exception as exc:
            messagebox.showerror('New Address Failed', str(exc), parent=self)

    def create_new_wallet(self) -> None:
        try:
            password = prompt_new_wallet_password(self)
            if password is None:
                return
            path = next_wallet_path()
            label = path.name.removesuffix('.wallet.json')
            wallet = create_wallet(label)
            save_encrypted_wallet(wallet, str(path), password)
            self.reload_wallets(path.name)
            receive = current_receive_record(wallet)
            messagebox.showinfo(
                'Encrypted Wallet Created',
                f'Created {path.name}\n\nReceive address:\n{receive["address"]}\n\nThe private seed is encrypted with your password. Back up the .wallet.json file and keep the password separately.',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror('Create Wallet Failed', str(exc), parent=self)

    def first_run_prompt(self) -> None:
        if self._closing or self.wallet_map:
            return
        choice = messagebox.askyesnocancel(
            'Welcome to GameCoin Mainnet',
            'No wallet is installed yet.\n\nYes = create a new wallet\nNo = import an existing .wallet.json file\nCancel = do this later',
            parent=self,
        )
        if choice is True:
            self.create_new_wallet()
        elif choice is False:
            self.import_wallet()

    def import_wallet(self) -> None:
        source_name = filedialog.askopenfilename(
            parent=self, title='Import GameCoin Wallet',
            filetypes=[('GameCoin wallet', '*.wallet.json'), ('JSON files', '*.json'), ('All files', '*.*')],
        )
        if not source_name:
            return
        source = Path(source_name)
        try:
            wallet = load_wallet(str(source))
            base = source.name if source.name.endswith('.wallet.json') else source.stem + '.wallet.json'
            destination = WALLETS_DIR / base
            if destination.exists():
                i = 1
                while True:
                    candidate = WALLETS_DIR / f'imported_{i:03d}.wallet.json'
                    if not candidate.exists():
                        destination = candidate
                        break
                    i += 1
            if is_encrypted_wallet(wallet):
                shutil.copy2(source, destination)
                imported = load_wallet(str(destination))
                security_text = 'Encrypted backup imported. Its existing password is still required for spending.'
            else:
                password = prompt_new_wallet_password(self, 'Encrypt Imported Legacy Wallet')
                if password is None:
                    return
                save_encrypted_wallet(wallet, str(destination), password)
                imported = load_wallet(str(destination))
                security_text = 'Legacy plaintext mainnet wallet was imported as an encrypted v1.0.0 wallet. The source file was not changed.'
            self.reload_wallets(destination.name)
            receive = current_receive_record(imported)
            messagebox.showinfo(
                'Wallet Imported',
                f'Imported {destination.name}\n\nReceive address:\n{receive["address"]}\n\n{security_text}',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror('Import Wallet Failed', str(exc), parent=self)

    def backup_wallet(self) -> None:
        if not self.current_wallet:
            messagebox.showwarning('No Wallet', 'Select or create a wallet first.', parent=self)
            return
        dest_name = filedialog.asksaveasfilename(
            parent=self,
            title='Back Up GameCoin Wallet',
            initialfile=self.current_wallet.name,
            defaultextension='.wallet.json',
            filetypes=[('GameCoin wallet', '*.wallet.json'), ('JSON files', '*.json')],
        )
        if not dest_name:
            return
        try:
            destination = Path(dest_name)
            if destination.resolve() == self.current_wallet.resolve():
                messagebox.showinfo('Wallet Backup', "That is the wallet's current location. Choose another folder or drive for a real backup.", parent=self)
                return
            shutil.copy2(self.current_wallet, destination)
            messagebox.showinfo('Wallet Backed Up', f'Backup saved to:\n\n{destination}', parent=self)
        except Exception as exc:
            messagebox.showerror('Backup Wallet Failed', str(exc), parent=self)

    def wallet_security(self) -> None:
        if not self.current_wallet:
            messagebox.showwarning('No Wallet', 'Select or create a wallet first.', parent=self)
            return
        try:
            public_wallet = load_wallet(str(self.current_wallet))
            if is_encrypted_wallet(public_wallet):
                if not messagebox.askyesno(
                    'Wallet Security',
                    'This wallet is encrypted with Argon2id + AES-256-GCM.\n\nChange its password now?',
                    parent=self,
                ):
                    return
                old_password = prompt_wallet_password(self, 'Current Wallet Password')
                if old_password is None:
                    return
                # Validate the old password before asking for a replacement.
                load_wallet(str(self.current_wallet), old_password)
                new_password = prompt_new_wallet_password(self, 'New Wallet Password')
                if new_password is None:
                    return
                change_wallet_password(str(self.current_wallet), old_password, new_password)
                messagebox.showinfo('Wallet Security', 'Wallet password changed. Addresses and funds are unchanged.', parent=self)
            else:
                if not messagebox.askyesno(
                    'Encrypt Legacy Wallet',
                    'This wallet stores its master seed in plaintext.\n\nEncrypt it now? A plaintext safety backup will be retained so migration is never destructive.',
                    parent=self,
                ):
                    return
                password = prompt_new_wallet_password(self, 'Encrypt Legacy Wallet')
                if password is None:
                    return
                stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                backup = self.current_wallet.with_name(self.current_wallet.name + f'.unencrypted-backup-{stamp}.json')
                shutil.copy2(self.current_wallet, backup)
                migrate_wallet_file_to_encrypted(str(self.current_wallet), password)
                self.reload_wallets(self.current_wallet.name)
                messagebox.showinfo(
                    'Wallet Encrypted',
                    f'Wallet encrypted successfully.\n\nPlaintext safety backup retained at:\n{backup}\n\nAfter verifying the encrypted wallet, protect or securely delete that plaintext backup.',
                    parent=self,
                )
        except Exception as exc:
            messagebox.showerror('Wallet Security Failed', str(exc), parent=self)

    def open_wallet_folder(self) -> None:
        WALLETS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == 'nt':
                os.startfile(str(WALLETS_DIR))  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(WALLETS_DIR)])
            else:
                subprocess.Popen(['xdg-open', str(WALLETS_DIR)])
        except Exception as exc:
            messagebox.showerror('Open Wallet Folder Failed', str(exc), parent=self)

    def open_download_page(self) -> None:
        try:
            webbrowser.open(self.update_download_url or DOWNLOAD_PAGE_URL)
        except Exception as exc:
            messagebox.showerror('Open Download Page Failed', str(exc), parent=self)

    def check_for_updates_async(self) -> None:
        if self._closing:
            return
        self.update_var.set('Update: checking...')

        def work() -> None:
            try:
                req = urllib.request.Request(
                    UPDATE_MANIFEST_URL,
                    headers={'Accept': 'application/json', 'User-Agent': f'GameCoinWallet/{APP_VERSION}'},
                )
                with urllib.request.urlopen(req, timeout=5.0) as response:
                    payload = json.loads(response.read(65536).decode('utf-8'))
                latest = str(payload.get('version', '')).strip()
                network = str(payload.get('release_network') or payload.get('network', '')).strip()
                url = str(payload.get('download_page_url') or payload.get('installer_url') or DOWNLOAD_PAGE_URL)
                if network and network != NETWORK_NAME:
                    raise RuntimeError('Update manifest is for a different GameCoin network')
                self.after(0, lambda: self._apply_update_check(latest, url))
            except Exception:
                self.after(0, lambda: self.update_var.set('Update: unable to check'))

        threading.Thread(target=work, daemon=True).start()

    def _apply_update_check(self, latest: str, url: str) -> None:
        if self._closing:
            return
        if url:
            self.update_download_url = url
        if latest and version_tuple(latest) > version_tuple(APP_VERSION):
            self.update_var.set(f'Update available: v{latest}')
        elif latest:
            self.update_var.set('Update: current')
        else:
            self.update_var.set('Update: no version returned')

    def copy_address(self) -> None:
        if not self.current_address:
            return
        self.clipboard_clear()
        self.clipboard_append(self.current_address)
        self.update_idletasks()

    def _node_process_running(self) -> bool:
        return bool(self.node_process and self.node_process.poll() is None)

    def _update_node_buttons(self, connected: bool) -> None:
        if self._node_process_running() and self.node_started_by_gui:
            self.start_node_button.configure(state='disabled')
            self.stop_node_button.configure(state='normal')
            self.node_detail_var.set('Local node: running (started by this wallet)')
        elif connected:
            self.start_node_button.configure(state='disabled')
            self.stop_node_button.configure(state='disabled')
            self.node_detail_var.set('Local node: connected (started outside this wallet)')
        else:
            self.start_node_button.configure(state='normal')
            self.stop_node_button.configure(state='disabled')
            self.node_detail_var.set('Local node: stopped')

    def _update_mining_buttons(self) -> None:
        miner_running = bool(self.miner_process and self.miner_process.poll() is None)
        if miner_running:
            self.start_mining_button.configure(state='disabled')
            self.stop_mining_button.configure(state='normal')
            return
        self.stop_mining_button.configure(state='disabled')
        can_mine = bool(self.current_wallet and self.node_synced)
        self.start_mining_button.configure(state='normal' if can_mine else 'disabled')

    def start_node(self, automatic: bool = False) -> None:
        if self._node_process_running():
            return

        # Reuse an already-running v2 node. A leftover v1 node must not be
        # mistaken for the reset network just because it owns the same RPC port.
        try:
            status = node_status()
            if status.get('network') == NETWORK_NAME and str(status.get('node_version', '')) == APP_VERSION:
                self.node_var.set('Node: connected')
                self._update_node_buttons(True)
                self.refresh_async()
                return
            raise RuntimeError('An older or incompatible GameCoin node is still using local RPC port 22444.')
        except RuntimeError as exc:
            if 'older GameCoin node' in str(exc):
                messagebox.showerror(
                    'Old Node Still Running',
                    'An older or incompatible GameCoin node is still running on port 22444. Close it (or end GameCoinMainnetNode.exe in Task Manager), then click Start Node again.',
                    parent=self,
                )
                return
        except Exception:
            pass

        if getattr(sys, 'frozen', False):
            cmd = [
                str(APP_DIR / 'GameCoinMainnetNode.exe'),
                '--config', str(APP_DIR / 'config.json'),
                '--data-dir', str(DATA_DIR),
                '--log-dir', str(LOGS_DIR),
            ]
        else:
            cmd = [
                sys.executable, '-u', str(APP_DIR / 'node.py'),
                '--config', str(APP_DIR / 'config.json'),
                '--data-dir', str(DATA_DIR),
                '--log-dir', str(LOGS_DIR),
            ]
        kwargs: Dict[str, Any] = {
            'cwd': str(APP_DIR),
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'env': {**os.environ, 'PYTHONUNBUFFERED': '1'},
        }
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        else:
            kwargs['start_new_session'] = True

        try:
            self.node_process = subprocess.Popen(cmd, **kwargs)
            self.node_started_by_gui = True
        except Exception as exc:
            self.node_process = None
            self.node_started_by_gui = False
            messagebox.showerror('Node Failed', str(exc), parent=self)
            return

        self.node_var.set('Node: starting automatically...' if automatic else 'Node: starting...')
        self.start_node_button.configure(state='disabled')
        self.stop_node_button.configure(state='normal')
        self.node_detail_var.set('Local node: starting...')

        def wait_for_node() -> None:
            error = ''
            for _ in range(40):
                if self._closing:
                    return
                proc = self.node_process
                if not proc or proc.poll() is not None:
                    error = 'The node process exited before it became ready. Check logs\\node.log.'
                    break
                try:
                    status = node_status()
                    if status.get('network') != NETWORK_NAME or not str(status.get('node_version', '')) == APP_VERSION:
                        error = 'A node answered on port 22444, but it is not the GameCoin mainnet node.'
                        break
                    self.after(0, self._node_started_ok)
                    return
                except Exception:
                    time.sleep(0.2)
            if not error:
                error = 'The node did not become ready in time. Check logs\\node.log.'
            self.after(0, lambda e=error: self._node_start_failed(e))

        threading.Thread(target=wait_for_node, daemon=True).start()

    def _node_started_ok(self) -> None:
        if self._closing:
            return
        self.node_var.set('Node: connected')
        self._update_node_buttons(True)
        self.refresh_async()

    def _node_start_failed(self, error: str) -> None:
        if self._closing:
            return
        proc = self.node_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.node_process = None
        self.node_started_by_gui = False
        self.node_var.set('Node: offline')
        self._update_node_buttons(False)
        messagebox.showerror('Node Failed', error, parent=self)

    def stop_node(self, quiet: bool = False) -> None:
        proc = self.node_process
        if not proc or proc.poll() is not None or not self.node_started_by_gui:
            self.node_process = None
            self.node_started_by_gui = False
            self._update_node_buttons(False)
            return

        # Stop the GUI miner first so it does not keep submitting work to a
        # node that is shutting down.
        if self.miner_process and self.miner_process.poll() is None:
            self.stop_mining()

        self.node_var.set('Node: stopping...')
        self.stop_node_button.configure(state='disabled')
        self.node_detail_var.set('Local node: stopping...')

        def work() -> None:
            try:
                try:
                    request_json(NODE_URL, '/shutdown', method='POST', body={})
                except Exception:
                    if os.name == 'nt':
                        try:
                            proc.send_signal(signal.CTRL_BREAK_EVENT)
                        except Exception:
                            proc.terminate()
                    else:
                        try:
                            os.killpg(proc.pid, signal.SIGINT)
                        except Exception:
                            proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:
                pass
            self.after(0, self._node_stopped_ok)

        threading.Thread(target=work, daemon=True).start()

    def _node_stopped_ok(self) -> None:
        self.node_process = None
        self.node_started_by_gui = False
        if self._closing:
            return
        self.node_var.set('Node: offline')
        self.node_synced = False
        self.sync_progress_var.set(0.0)
        self.sync_progress_text_var.set('Sync progress: local node offline')
        self._update_node_buttons(False)
        self._update_mining_buttons()
        self.refresh_async()

    def open_logs(self) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == 'nt':
                os.startfile(str(LOGS_DIR))  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(LOGS_DIR)])
            else:
                subprocess.Popen(['xdg-open', str(LOGS_DIR)])
        except Exception as exc:
            messagebox.showerror('Open Logs Failed', str(exc), parent=self)

    def refresh_async(self) -> None:
        if self._closing or self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        wallet_path = self.current_wallet
        def work() -> None:
            result: Dict[str, Any] = {'wallet_path': str(wallet_path) if wallet_path else ''}
            try:
                status = node_status()
                result['status'] = status
                if wallet_path:
                    wallet = load_wallet(str(wallet_path))
                    result['balance'] = wallet_balance(wallet)
                    result['wallet_stats'] = wallet_stats(wallet)
                    result['activity'] = recent_activity(wallet, int(status.get('height', 0) or 0))
            except Exception as exc:
                result['error'] = str(exc)
            self.after(0, lambda: self._apply_refresh(result))
        threading.Thread(target=work, daemon=True).start()

    def _apply_refresh(self, result: Dict[str, Any]) -> None:
        self._refresh_in_progress = False
        if self._closing:
            return
        current_path = str(self.current_wallet) if self.current_wallet else ''
        if result.get('wallet_path', '') != current_path:
            self.after(10, self.refresh_async)
            return
        if 'error' in result:
            self.node_var.set('Node: offline')
            self._update_node_buttons(False)
            self.height_var.set('Height: —')
            self.difficulty_var.set('Current difficulty: —')
            self.next_difficulty_var.set('Next difficulty: —')
            self.needed_difficulty_var.set('Estimated needed: —')
            self.difficulty_status_var.set('Difficulty status: —')
            self.avg_time_var.set('Average last 20: —')
            self.active_avg_var.set('Adjustment average: —')
            self.last_time_var.set('Last block time: —')
            self.network_rate_var.set('Estimated network rate: —')
            self.expected_attempts_var.set('Expected next attempts: —')
            self.ramp_limit_var.set('Max increase this block: —')
            self.wallet_mined_var.set('Blocks mined by wallet: —')
            self.wallet_rewards_var.set('Mining rewards earned: —')
            self.sync_status_var.set('Sync: —')
            self.network_height_var.set('Network height: —')
            self.peer_count_var.set('Peers: —')
            self.primary_peer_var.set('Seed: —')
            self.mempool_var.set('Network mempool: -')
            self.block_reward_var.set('Block reward: —')
            self.circulating_supply_var.set('Circulating supply: —')
            self.max_supply_var.set('Maximum supply: —')
            self.halving_var.set('Next halving: —')
            self.node_synced = False
            self.sync_progress_var.set(0.0)
            self.sync_progress_text_var.set('Sync progress: local node offline')
            self._update_mining_buttons()
        else:
            status = result['status']
            self.node_var.set('Node: connected')
            self._update_node_buttons(True)
            self.height_var.set(f'Height: {status.get("height", "—")}')
            current_factor = status.get('current_difficulty_factor', status.get('difficulty_factor'))
            next_factor = status.get('next_difficulty_factor', status.get('difficulty_factor'))
            needed_factor = status.get('estimated_needed_difficulty_factor', next_factor)
            self.difficulty_var.set('Current difficulty: —' if current_factor is None else f'Current difficulty: {float(current_factor):,.3f}x')
            self.next_difficulty_var.set('Next difficulty: —' if next_factor is None else f'Next difficulty: {float(next_factor):,.3f}x')
            self.needed_difficulty_var.set('Estimated needed: —' if needed_factor is None else f'Estimated needed: {float(needed_factor):,.3f}x')
            self.difficulty_status_var.set(f'Difficulty status: {status.get("difficulty_status", "—")}')
            self.target_time_var.set(f'Target block time: {format_seconds(status.get("target_block_seconds"))}')
            self.avg_time_var.set(f'Average last 20: {format_seconds(status.get("average_block_seconds"))}')
            self.active_avg_var.set(f'Adjustment average: {format_seconds(status.get("active_average_block_seconds"))}')
            self.last_time_var.set(f'Last block time: {format_seconds(status.get("last_block_seconds"))}')
            self.network_rate_var.set(f'Estimated network rate: {format_hashrate(status.get("estimated_hashrate"))}')
            self.expected_attempts_var.set(f'Expected next attempts: {format_attempts(status.get("expected_hashes"))}')
            max_up = status.get('max_adjust_up')
            self.ramp_limit_var.set('Max increase this block: —' if max_up is None else f'Max increase this block: {float(max_up):.2f}x')
            sync_status = str(status.get('sync_status', '—'))
            lag = int(status.get('sync_lag', 0) or 0)
            local_height = int(status.get('height', 0) or 0)
            network_height = int(status.get('network_height', local_height) or 0)
            peer_count = int(status.get('peer_count', 0) or 0)
            seed_mode = bool(status.get('seed_mode', False))
            self.sync_status_var.set(f'Sync: {sync_status}' + (f' ({lag} behind)' if lag else ''))
            self.network_height_var.set(f'Network height: {network_height}')
            self.peer_count_var.set(f'Peers: {peer_count}')
            self.mempool_var.set(f'Network mempool: {int(status.get("mempool_transactions", 0) or 0):,}')
            reward = int(status.get('block_reward', 0) or 0)
            circulating = int(status.get('circulating_supply', 0) or 0)
            max_supply = int(status.get('max_supply', 0) or 0)
            blocks_left_raw = status.get('blocks_until_halving')
            self.block_reward_var.set(f'Block reward: {format_amount(reward)} GAME')
            self.circulating_supply_var.set(f'Circulating: {format_amount(circulating)} GAME')
            self.max_supply_var.set(f'Max: {format_amount(max_supply)} GAME')
            if blocks_left_raw is None:
                self.halving_var.set('Next halving: subsidy complete')
            else:
                blocks_left = max(0, int(blocks_left_raw))
                eta = datetime.fromtimestamp(time.time() + blocks_left * float(status.get('target_block_seconds', TARGET_BLOCK_SECONDS) or TARGET_BLOCK_SECONDS))
                self.halving_var.set(f'Halving: {blocks_left:,} blocks (~{eta:%Y-%m-%d})')
            peer = status.get('primary_peer') or ('this node' if seed_mode else '—')
            self.primary_peer_var.set(f'Seed: {peer}')
            if network_height > 0:
                progress = max(0.0, min(100.0, (local_height / network_height) * 100.0))
            elif sync_status in ('SYNCED', 'SEED'):
                progress = 100.0
            else:
                progress = 0.0
            self.sync_progress_var.set(progress)
            if sync_status in ('SYNCED', 'SEED') and lag == 0:
                self.sync_progress_text_var.set(f'Chain synchronized: {local_height:,} / {network_height:,} blocks (100%)')
            elif network_height > 0:
                self.sync_progress_text_var.set(f'Downloading and validating chain: {local_height:,} / {network_height:,} blocks ({progress:.1f}%)')
            elif sync_status in ('OFFLINE', 'NO PEERS', 'SYNC ERROR'):
                self.sync_progress_text_var.set('Waiting for seed network connection...')
            else:
                self.sync_progress_text_var.set('Discovering network height and starting synchronization...')
            self.node_synced = bool(seed_mode or (sync_status == 'SYNCED' and lag == 0 and peer_count > 0))
            self._update_mining_buttons()
            self.balance_var.set(f'{format_amount(result.get("balance", 0))} GAME')
            wstats = result.get('wallet_stats', {})
            self.wallet_mined_var.set(f'Blocks mined by wallet: {int(wstats.get("mined_blocks", 0)):,}')
            self.wallet_rewards_var.set(f'Mining rewards earned: {format_amount(int(wstats.get("mining_rewards", 0)))} GAME')
            self._fill_activity(result.get('activity', []))
        if not self._closing:
            self.after(REFRESH_MS, self.refresh_async)

    def _fill_activity(self, rows: List[Dict[str, Any]]) -> None:
        self.transaction_rows_by_iid = {}
        pending_count = sum(1 for row in rows if str(row.get('status', '')) == 'Pending')
        self.wallet_pending_var.set(f'Wallet pending: {pending_count:,}')
        children = self.activity_tree.get_children()
        if children:
            self.activity_tree.delete(*children)
        overview_children = self.overview_tree.get_children()
        if overview_children:
            self.overview_tree.delete(*overview_children)

        for row in rows[:250]:
            atoms = int(row.get('amount', 0) or 0)
            amount_text = ('+' if atoms > 0 else '') + format_amount(atoms) + ' GAME'
            confirmations = int(row.get('confirmations', 0) or 0)
            conf_text = str(confirmations) if confirmations else '-'
            status = str(row.get('status', '-'))
            kind = str(row.get('type', '-'))
            tag = 'pending' if status == 'Pending' else ('mining' if kind == 'Mining reward' else ('sent' if kind == 'Sent' else 'received'))
            iid = self.activity_tree.insert('', 'end', values=(
                status, row.get('date', '-'), kind, amount_text, conf_text,
                row.get('address', ''), row.get('txid', ''),
            ), tags=(tag,))
            self.transaction_rows_by_iid[iid] = row

        for row in rows[:12]:
            atoms = int(row.get('amount', 0) or 0)
            amount_text = ('+' if atoms > 0 else '') + format_amount(atoms) + ' GAME'
            confirmations = int(row.get('confirmations', 0) or 0)
            self.overview_tree.insert('', 'end', values=(
                row.get('status', '-'), row.get('date', '-'), row.get('type', '-'),
                amount_text, str(confirmations) if confirmations else '-',
            ))

    def show_transaction_details(self) -> None:
        selected = self.activity_tree.selection()
        if not selected:
            messagebox.showinfo('Transaction Details', 'Select a transaction first.', parent=self)
            return
        row = self.transaction_rows_by_iid.get(selected[0])
        if not row:
            return
        status = str(row.get('status', '-'))
        height = row.get('height')
        height_text = 'Pending / mempool' if height is None else str(height)
        confirmations = int(row.get('confirmations', 0) or 0)
        atoms = int(row.get('amount', 0) or 0)
        amount_text = ('+' if atoms > 0 else '') + format_amount(atoms) + ' GAME'
        details = (
            f'Status: {status}\n'
            f'Date / time: {row.get("date", "-")}\n'
            f'Type: {row.get("type", "-")}\n'
            f'Amount: {amount_text}\n'
            f'Block: {height_text}\n'
            f'Confirmations: {confirmations}\n'
            f'Address: {row.get("address", "")}\n\n'
            f'Transaction ID:\n{row.get("txid", "")}'
        )
        messagebox.showinfo('Transaction Details', details, parent=self)

    def send_clicked(self) -> None:
        if not self.current_wallet:
            messagebox.showwarning('No Wallet', 'Select a wallet first.', parent=self)
            return
        to_address = self.to_var.get().strip()
        amount_text = self.amount_var.get().strip()
        if not to_address or not amount_text:
            messagebox.showwarning('Missing Information', 'Enter a destination address and amount.', parent=self)
            return
        wallet_path = self.current_wallet
        password: Optional[str] = None
        try:
            public_wallet = load_wallet(str(wallet_path))
            if is_encrypted_wallet(public_wallet):
                password = prompt_wallet_password(self, 'Unlock Wallet to Send')
                if password is None:
                    return
                # Verify before the confirmation dialog so a typo cannot create
                # a confusing background send failure.
                load_wallet(str(wallet_path), password)
        except Exception as exc:
            messagebox.showerror('Unlock Wallet Failed', str(exc), parent=self)
            return

        if not messagebox.askyesno(
            'Confirm Testnet Send',
            f'Send {amount_text} GAME to:\n\n{to_address}\n\nNetwork fee: {format_amount(DEFAULT_TRANSACTION_FEE)} GAME\n\nThis is GameCoin Mainnet.',
            parent=self,
        ):
            return

        def work() -> None:
            try:
                tid = build_and_submit_transaction(wallet_path, to_address, amount_text, password)
                self.after(0, lambda: self._send_ok(tid))
            except Exception as exc:
                self.after(0, lambda e=str(exc): messagebox.showerror('Send Failed', e, parent=self))

        threading.Thread(target=work, daemon=True).start()

    def _send_ok(self, tid: str) -> None:
        self.to_var.set('')
        self.amount_var.set('')
        messagebox.showinfo(
            'Transaction Submitted',
            f'Transaction submitted:\n\n{tid}\n\nIt will appear as Pending on the Transactions tab until the next block is mined.',
            parent=self,
        )
        try:
            self.notebook.select(self.transactions_tab)
        except Exception:
            pass
        self.refresh_async()

    def start_mining(self) -> None:
        if self.miner_process and self.miner_process.poll() is None:
            return
        if not self.current_wallet:
            messagebox.showwarning('No Wallet', 'Select a wallet first.', parent=self)
            return
        if not self.node_synced:
            messagebox.showwarning(
                'Blockchain Still Syncing',
                'Wait until the wallet shows Chain synchronized before starting the miner.',
                parent=self,
            )
            return
        try:
            threads = int(self.threads_var.get())
        except Exception:
            threads = 1
        max_threads = max(1, os.cpu_count() or 1)
        if threads < 1 or threads > max_threads:
            messagebox.showwarning('CPU Processes', f'Choose between 1 and {max_threads}.', parent=self)
            return
        try:
            status = node_status()
            if status.get('difficulty_algorithm') != 'adaptive-window-v0.6':
                raise RuntimeError('The node is not running the compatible adaptive difficulty software.')
        except Exception as exc:
            messagebox.showerror('Node Offline / Old Version', f'Start the node using the Start Node button or start_node.bat.\n\n{exc}', parent=self)
            return

        if getattr(sys, 'frozen', False):
            cmd = [
                str(APP_DIR / 'GameCoinMainnetMiner.exe'),
                '--wallet', str(self.current_wallet),
                '--threads', str(threads),
                '--report-every', '2000',
                '--log-dir', str(LOGS_DIR),
            ]
        else:
            cmd = [
                sys.executable, '-u', str(APP_DIR / 'miner.py'),
                '--wallet', str(self.current_wallet),
                '--threads', str(threads),
                '--report-every', '2000',
                '--log-dir', str(LOGS_DIR),
            ]
        kwargs: Dict[str, Any] = {
            'cwd': str(APP_DIR),
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
            'text': True,
            'bufsize': 1,
            'env': {**os.environ, 'PYTHONUNBUFFERED': '1'},
        }
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | (getattr(subprocess, 'CREATE_NO_WINDOW', 0) if getattr(sys, 'frozen', False) else 0)
        else:
            kwargs['start_new_session'] = True

        try:
            self.miner_process = subprocess.Popen(cmd, **kwargs)
        except Exception as exc:
            messagebox.showerror('Miner Failed', str(exc), parent=self)
            return

        self.hashrate_var.set('Hash rate: —')
        self.attempts_var.set('Attempts this block: 0')
        self.elapsed_var.set('Elapsed this block: 0.0s')
        self.session_blocks_var.set('Blocks this session: 0')
        self.last_block_var.set('Last block: —')
        self.miner_status_var.set(f'GUI miner: mining with {threads} CPU process(es)')
        self.start_mining_button.configure(state='disabled')
        self.stop_mining_button.configure(state='normal')
        self.miner_reader_thread = threading.Thread(target=self._read_miner_output, daemon=True)
        self.miner_reader_thread.start()

    def _read_miner_output(self) -> None:
        proc = self.miner_process
        if not proc or not proc.stdout:
            return
        try:
            for line in proc.stdout:
                if line:
                    self.miner_queue.put(line.strip())
        finally:
            try:
                code = proc.wait(timeout=1)
            except Exception:
                code = proc.poll()
            self.miner_queue.put(f'__EXIT__:{proc.pid}:{code}')

    def _drain_miner_queue(self) -> None:
        if self._closing:
            return
        try:
            while True:
                line = self.miner_queue.get_nowait()
                if line.startswith('__EXIT__:'):
                    parts = line.split(':', 2)
                    exited_pid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                    current = self.miner_process
                    if current is None or exited_pid is None or current.pid == exited_pid:
                        self.miner_process = None
                        self.miner_status_var.set('GUI miner: stopped')
                        self._update_mining_buttons()
                        self.refresh_async()
                    continue

                stats = re.search(
                    r'Mining stats: block\s+(\d+)\s+\| attempts\s+([\d,]+)\s+\| hash rate\s+([\d,.]+)\s+H/s\s+\| elapsed\s+([\d.]+)s',
                    line,
                )
                if stats:
                    self.attempts_var.set(f'Attempts this block: {stats.group(2)}')
                    self.hashrate_var.set(f'Hash rate: {format_hashrate(stats.group(3).replace(",", ""))}')
                    self.elapsed_var.set(f'Elapsed this block: {float(stats.group(4)):.1f}s')
                    continue

                result = re.search(r'Block result: attempts=(\d+) elapsed=([\d.]+) hashrate=([\d.]+)', line)
                if result:
                    attempts = int(result.group(1))
                    elapsed = float(result.group(2))
                    rate = float(result.group(3))
                    self.attempts_var.set(f'Attempts this block: {attempts:,}')
                    self.hashrate_var.set(f'Hash rate: {format_hashrate(rate)}')
                    self.elapsed_var.set(f'Elapsed this block: {elapsed:.1f}s')
                    self.last_block_var.set(f'Last block: {attempts:,} attempts in {elapsed:.2f}s ({format_hashrate(rate)})')
                    continue

                session = re.search(r'Session blocks mined:\s*(\d+)', line)
                if session:
                    self.session_blocks_var.set(f'Blocks this session: {int(session.group(1)):,}')
                    continue

                mining = re.search(r'Mining block\s+(\d+)\s+at difficulty\s+([\d.]+)x', line)
                if mining:
                    self.miner_status_var.set(f'GUI miner: mining block {mining.group(1)} at {float(mining.group(2)):.6f}x')
                    self.attempts_var.set('Attempts this block: 0')
                    self.elapsed_var.set('Elapsed this block: 0.0s')
                    continue

                if line.startswith('Accepted block'):
                    self.miner_status_var.set('GUI miner: block accepted; mining next block')
                    self.refresh_async()
                elif line.startswith('Block rejected'):
                    self.miner_status_var.set('GUI miner: block rejected; retrying')
        except queue.Empty:
            pass
        self.after(100, self._drain_miner_queue)

    def stop_mining(self) -> None:
        proc = self.miner_process
        if not proc or proc.poll() is not None:
            self.miner_process = None
            self.miner_status_var.set('GUI miner: stopped')
            self._update_mining_buttons()
            return
        self.miner_status_var.set('GUI miner: stopping...')
        self.start_mining_button.configure(state='disabled')
        self.stop_mining_button.configure(state='disabled')

        def work() -> None:
            terminate_process_tree(proc)
            # The stdout reader normally posts the __EXIT__ message. If a
            # forced Windows tree kill closes the pipe before that reader gets
            # scheduled, post a process-specific exit marker here as well.
            self.miner_queue.put(f'__EXIT__:{proc.pid}:{proc.poll()}')

        threading.Thread(target=work, daemon=True).start()

    def on_close(self) -> None:
        miner_running = bool(self.miner_process and self.miner_process.poll() is None)
        node_running = self._node_process_running() and self.node_started_by_gui
        if miner_running or node_running:
            running = []
            if miner_running:
                running.append('the GUI miner')
            if node_running:
                running.append('the node started by this wallet')
            if not messagebox.askyesno(
                'Exit GameCoin Wallet',
                'Stop ' + ' and '.join(running) + ' and close the wallet?',
                parent=self,
            ):
                return

        self._closing = True
        if self.miner_process and self.miner_process.poll() is None:
            terminate_process_tree(self.miner_process)
        if self.node_process and self.node_process.poll() is None and self.node_started_by_gui:
            try:
                try:
                    request_json(NODE_URL, '/shutdown', method='POST', body={})
                except Exception:
                    self.node_process.terminate()
                try:
                    self.node_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.node_process.kill()
                    self.node_process.wait(timeout=2)
            except Exception:
                pass
        self.destroy()


def main() -> None:
    app = WalletApp()
    app.mainloop()


if __name__ == '__main__':
    main()
