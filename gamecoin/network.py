import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

NETWORK_NAME = 'gamecoin-mainnet'
P2P_PROTOCOL = 6
DEFAULT_P2P_PORT = 22445
MAX_P2P_RESPONSE_BYTES = 8 * 1024 * 1024


def normalize_peer(peer: str) -> str:
    value = (peer or '').strip()
    if not value:
        raise ValueError('Empty peer')
    if '://' not in value:
        value = 'http://' + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError('Peer must use http or https')
    if not parsed.hostname:
        raise ValueError('Peer host is missing')
    port = parsed.port or DEFAULT_P2P_PORT
    host = parsed.hostname
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    return f'{parsed.scheme}://{host}:{port}'


def unique_peers(peers: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for peer in peers:
        try:
            normalized = normalize_peer(peer)
        except Exception:
            continue
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def p2p_request(peer: str, path: str, method: str = 'GET', body: Optional[Dict[str, Any]] = None,
                timeout: float = 5.0) -> Any:
    base = normalize_peer(peer)
    url = base.rstrip('/') + path
    data = None
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'GameCoinMainnet/1.0.0',
    }
    if body is not None:
        data = json.dumps(body, separators=(',', ':')).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_P2P_RESPONSE_BYTES + 1)
            if len(raw) > MAX_P2P_RESPONSE_BYTES:
                raise RuntimeError('Peer response exceeded safety limit')
            return json.loads(raw.decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(65536)
            payload = json.loads(raw.decode('utf-8'))
            message = payload.get('error', str(exc))
        except Exception:
            message = str(exc)
        raise RuntimeError(message) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f'Peer connection failed: {exc}') from exc
