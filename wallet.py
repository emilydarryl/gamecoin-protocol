#!/usr/bin/env python3
import argparse
import getpass
import json
import os
import shutil
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from gamecoin.policy import DEFAULT_TRANSACTION_FEE
from gamecoin.rpc import request_json
from gamecoin.utils import tx_id, validate_address
from gamecoin.wallet_core import (
    all_wallet_key_records, change_wallet_password, create_wallet, current_receive_record,
    generate_change_address, generate_receive_address, is_encrypted_wallet, load_wallet,
    migrate_wallet_file_to_encrypted, public_key_for_address, save_encrypted_wallet,
    save_wallet, sign_transaction_input, validate_new_password,
)

COIN = 100_000_000
DEFAULT_NODE = 'http://127.0.0.1:22444'


def amount_to_atoms(text: str) -> int:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('Invalid amount') from exc
    if value <= 0:
        raise ValueError('Amount must be positive')
    atoms = int((value * COIN).quantize(Decimal('1'), rounding=ROUND_DOWN))
    if atoms <= 0:
        raise ValueError('Amount is too small')
    return atoms


def fee_to_atoms(text: str) -> int:
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('Invalid fee') from exc
    if value < 0:
        raise ValueError('Fee cannot be negative')
    return int((value * COIN).quantize(Decimal('1'), rounding=ROUND_DOWN))


def format_amount(atoms: int) -> str:
    return f'{Decimal(atoms) / COIN:.8f}'


def get_utxos(node: str, address: str) -> List[Dict[str, Any]]:
    return request_json(node, '/utxos/' + quote(address))['utxos']


def wallet_utxos(node: str, wallet: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for record in all_wallet_key_records(wallet):
        address = str(record['address'])
        for item in get_utxos(node, address):
            owned = dict(item)
            owned['owner_address'] = address
            out.append(owned)
    return out


def _password_from_env(args: argparse.Namespace) -> Optional[str]:
    name = getattr(args, 'password_env', None)
    if not name:
        return None
    value = os.environ.get(name)
    if value is None:
        raise SystemExit(f'Environment variable {name} is not set')
    return value


def _new_password(args: argparse.Namespace, prompt: str = 'New wallet password: ') -> str:
    from_env = _password_from_env(args)
    if from_env is not None:
        validate_new_password(from_env)
        return from_env
    first = getpass.getpass(prompt)
    validate_new_password(first)
    second = getpass.getpass('Confirm wallet password: ')
    if first != second:
        raise SystemExit('Wallet passwords do not match')
    return first


def _existing_password(args: argparse.Namespace, prompt: str = 'Wallet password: ') -> str:
    from_env = _password_from_env(args)
    if from_env is not None:
        return from_env
    return getpass.getpass(prompt)


def _load_for_secret_action(path: str, args: argparse.Namespace) -> tuple[Dict[str, Any], Optional[str]]:
    public = load_wallet(path)
    if is_encrypted_wallet(public):
        password = _existing_password(args)
        return load_wallet(path, password), password
    return public, None


def _save_after_secret_action(wallet: Dict[str, Any], path: str, password: Optional[str]) -> None:
    if password is not None or is_encrypted_wallet(wallet):
        if password is None:
            raise ValueError('Wallet password is required to save encrypted wallet changes')
        save_encrypted_wallet(wallet, path, password)
    else:
        save_wallet(wallet, path)


def cmd_create(args: argparse.Namespace) -> None:
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    password = _new_password(args)
    for i in range(args.count):
        label = args.label or f'wallet_{i + 1:03d}'
        if args.count > 1 and args.label:
            label = f'{args.label}_{i + 1:03d}'
        wallet = create_wallet(label)
        path = out / f'{label}.wallet.json'
        if path.exists() and not args.force:
            raise SystemExit(f'{path} already exists. Use --force only if you intend to replace it.')
        save_encrypted_wallet(wallet, str(path), password)
        print(f'Created encrypted wallet {path}')
        print(f'  Receive address: {current_receive_record(wallet)["address"]}')


def cmd_list(args: argparse.Namespace) -> None:
    paths = sorted(Path(args.dir).glob('*.wallet.json'))
    if not paths:
        print('No wallet files found.')
        return
    for path in paths:
        wallet = load_wallet(str(path))
        current = current_receive_record(wallet)
        security = 'encrypted' if is_encrypted_wallet(wallet) else 'UNENCRYPTED LEGACY'
        print(f'{path.name}: {current["address"]}  [{wallet.get("label", "")}]  receive addresses={len(wallet["receive_addresses"])}  {security}')


def cmd_show(args: argparse.Namespace) -> None:
    wallet = load_wallet(args.wallet)
    safe = json.loads(json.dumps({k: v for k, v in wallet.items() if not str(k).startswith('_')}))
    if 'private_key' in safe:
        safe['private_key'] = '<hidden>'
    if 'master_seed' in safe:
        safe['master_seed'] = '<hidden>'
    if isinstance(safe.get('encryption'), dict):
        safe['encryption']['ciphertext'] = '<encrypted secret payload hidden>'
    print(json.dumps(safe, indent=2))


def cmd_new_address(args: argparse.Namespace) -> None:
    wallet, password = _load_for_secret_action(args.wallet, args)
    wallet, item = generate_receive_address(wallet, args.label or '')
    _save_after_secret_action(wallet, args.wallet, password)
    print(item['address'])


def cmd_balance(args: argparse.Namespace) -> None:
    wallet = load_wallet(args.wallet)
    items = wallet_utxos(args.node, wallet)
    total = sum(int(item['amount']) for item in items)
    spendable = sum(int(item['amount']) for item in items if item.get('spendable', True))
    print(f'Wallet total: {format_amount(total)} GAME')
    if spendable != total:
        print(f'Spendable: {format_amount(spendable)} GAME')
        print(f'Immature: {format_amount(total - spendable)} GAME')


def cmd_send(args: argparse.Namespace) -> None:
    wallet, password = _load_for_secret_action(args.wallet, args)
    amount = amount_to_atoms(args.amount)
    if not validate_address(args.to):
        raise SystemExit('Destination is not a valid GameCoin address')
    fee = DEFAULT_TRANSACTION_FEE if args.fee is None else fee_to_atoms(args.fee)
    needed = amount + fee
    utxos = [item for item in wallet_utxos(args.node, wallet) if item.get('spendable', True)]
    selected: List[Dict[str, Any]] = []
    total = 0
    for item in utxos:
        selected.append(item)
        total += int(item['amount'])
        if total >= needed:
            break
    if total < needed:
        raise SystemExit(
            f'Insufficient spendable funds: have {format_amount(total)} GAME; '
            f'need {format_amount(needed)} GAME including fee'
        )
    inputs = []
    owners: List[str] = []
    for u in selected:
        owner = str(u['owner_address'])
        owners.append(owner)
        inputs.append({'txid': u['txid'], 'vout': int(u['vout']), 'pubkey': public_key_for_address(wallet, owner), 'signature': ''})
    outputs = [{'address': args.to, 'amount': amount}]
    change = total - amount - fee
    if change:
        wallet, change_record = generate_change_address(wallet)
        _save_after_secret_action(wallet, args.wallet, password)
        outputs.append({'address': change_record['address'], 'amount': change})
    tx = {'timestamp': int(time.time()), 'inputs': inputs, 'outputs': outputs}
    for idx, owner in enumerate(owners):
        tx['inputs'][idx]['signature'] = sign_transaction_input(tx, idx, wallet, owner)
    tx['txid'] = tx_id(tx)
    response = request_json(args.node, '/tx', method='POST', body={'tx': tx})
    print(f'Transaction submitted: {response["txid"]}')
    print(f'Fee: {format_amount(fee)} GAME')


def cmd_encrypt(args: argparse.Namespace) -> None:
    public = load_wallet(args.wallet)
    if is_encrypted_wallet(public):
        raise SystemExit('Wallet is already encrypted')
    password = _new_password(args)
    path = Path(args.wallet)
    backup = Path(args.backup) if args.backup else path.with_name(path.name + '.unencrypted-backup')
    if backup.exists() and not args.force:
        raise SystemExit(f'Backup path already exists: {backup}')
    shutil.copy2(path, backup)
    migrate_wallet_file_to_encrypted(str(path), password)
    print(f'Encrypted wallet in place: {path}')
    print(f'Plaintext safety backup retained at: {backup}')
    print('Protect or securely destroy that plaintext backup after verifying the encrypted wallet.')


def cmd_change_password(args: argparse.Namespace) -> None:
    public = load_wallet(args.wallet)
    if not is_encrypted_wallet(public):
        raise SystemExit('Wallet is not encrypted; use the encrypt command first')
    old_password = _existing_password(args, 'Current wallet password: ')
    # Do not use the same environment variable for both old and new password.
    if getattr(args, 'new_password_env', None):
        value = os.environ.get(args.new_password_env)
        if value is None:
            raise SystemExit(f'Environment variable {args.new_password_env} is not set')
        validate_new_password(value)
        new_password = value
    else:
        new_password = getpass.getpass('New wallet password: ')
        validate_new_password(new_password)
        confirm = getpass.getpass('Confirm new wallet password: ')
        if new_password != confirm:
            raise SystemExit('New wallet passwords do not match')
    change_wallet_password(args.wallet, old_password, new_password)
    print('Wallet password changed. Existing addresses and funds are unchanged.')


def _add_password_env(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--password-env', default=None, help='Read wallet password from this environment variable instead of prompting')


def main() -> None:
    parser = argparse.ArgumentParser(description='GameCoin Mainnet wallet tool v1.0.0')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('create'); p.add_argument('--count', type=int, default=1); p.add_argument('--dir', default='wallets'); p.add_argument('--label', default=''); p.add_argument('--force', action='store_true'); _add_password_env(p); p.set_defaults(func=cmd_create)
    p = sub.add_parser('list'); p.add_argument('--dir', default='wallets'); p.set_defaults(func=cmd_list)
    p = sub.add_parser('show'); p.add_argument('wallet'); p.set_defaults(func=cmd_show)
    p = sub.add_parser('new-address'); p.add_argument('wallet'); p.add_argument('--label', default=''); _add_password_env(p); p.set_defaults(func=cmd_new_address)
    p = sub.add_parser('balance'); p.add_argument('wallet'); p.add_argument('--node', default=DEFAULT_NODE); p.set_defaults(func=cmd_balance)
    p = sub.add_parser('send'); p.add_argument('wallet'); p.add_argument('--to', required=True); p.add_argument('--amount', required=True); p.add_argument('--fee', default=None, help='Transaction fee in GAME (default: 0.001)'); p.add_argument('--node', default=DEFAULT_NODE); _add_password_env(p); p.set_defaults(func=cmd_send)
    p = sub.add_parser('encrypt'); p.add_argument('wallet'); p.add_argument('--backup', default=None); p.add_argument('--force', action='store_true'); _add_password_env(p); p.set_defaults(func=cmd_encrypt)
    p = sub.add_parser('change-password'); p.add_argument('wallet'); _add_password_env(p); p.add_argument('--new-password-env', default=None); p.set_defaults(func=cmd_change_password)
    args = parser.parse_args()
    if getattr(args, 'count', 1) < 1 or getattr(args, 'count', 1) > 1000:
        raise SystemExit('--count must be from 1 to 1000')
    args.func(args)


if __name__ == '__main__':
    main()
