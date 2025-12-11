import socket
from typing import Tuple

from .irc_log import append_log


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            append_log(f"TCP connect OK to {host}:{port}")
            return True, "ok"
    except Exception as e:
        append_log(f"TCP connect FAILED to {host}:{port}: {e}")
        return False, str(e)
