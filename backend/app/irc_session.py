import threading
from typing import Optional

from .irc_client import IrcClient
from .irc_log import append_log


class IrcSession:
    """
    Simple singleton-like session manager for a persistent IRC connection.
    Uses threads to avoid blocking the async API loop.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: Optional[threading.Thread] = None
        self.client: Optional[IrcClient] = None
        self.connected = False
        self.error: Optional[str] = None
        self.stop_event = threading.Event()

    def connect(self) -> None:
        with self.lock:
            if self.connected:
                append_log("Session already connected")
                return
            self.error = None
            self.stop_event.clear()
            self.client = IrcClient()
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()

    def _run_loop(self) -> None:
        reactor = None
        server = None
        try:
            reactor, server = self.client._connect_and_join()  # type: ignore[attr-defined]
            self.connected = True
            append_log("Session connected and idle")
            while not self.stop_event.is_set():
                reactor.process_once(timeout=0.5)
        except Exception as e:
            append_log(f"Session error: {e}")
            self.error = str(e)
            self.connected = False
        finally:
            if server:
                try:
                    server.disconnect("done")
                except Exception:
                    pass
            self.client = None

    def disconnect(self) -> None:
        with self.lock:
            self.connected = False
            self.stop_event.set()
            self.client = None
            append_log("Session disconnected")

    def status(self) -> dict:
        return {"connected": self.connected, "error": self.error}


session = IrcSession()
