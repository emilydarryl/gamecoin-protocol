import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


def request_json(base_url: str, path: str, method: str = 'GET', body: Optional[Dict[str, Any]] = None) -> Any:
    url = base_url.rstrip('/') + path
    data = None
    headers = {'Accept': 'application/json'}
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode('utf-8'))
            message = payload.get('error', str(exc))
        except Exception:
            message = str(exc)
        raise RuntimeError(message) from exc
