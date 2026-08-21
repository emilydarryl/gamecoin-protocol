from datetime import datetime
from pathlib import Path
import threading
from typing import Union

_lock = threading.Lock()


def log_line(path: Union[str, Path], message: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S%z')
    line = f'{stamp}  {message.rstrip()}\n'
    with _lock:
        with p.open('a', encoding='utf-8') as f:
            f.write(line)
