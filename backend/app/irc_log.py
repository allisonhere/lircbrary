from collections import deque
from typing import Deque, List

LOG_LIMIT = 200
_buffer: Deque[str] = deque(maxlen=LOG_LIMIT)


def append_log(line: str) -> None:
    _buffer.append(line)


def get_logs() -> List[str]:
    return list(_buffer)


def clear_logs() -> None:
    _buffer.clear()
