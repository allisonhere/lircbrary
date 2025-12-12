import queue
import threading
import time
from typing import Optional, List

from .irc_client import IrcClient
from .irc_log import append_log
from .schemas import SearchResult


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
        self.request_q: "queue.Queue[dict]" = queue.Queue()

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
            active_req: Optional[dict] = None
            handlers: List[tuple] = []
            while not self.stop_event.is_set():
                # Start next queued search if none active
                if active_req is None:
                    try:
                        req = self.request_q.get_nowait()
                        active_req = req
                        handlers = self._start_search_request(req, server, reactor)
                    except queue.Empty:
                        pass
                # Pump IRC events
                reactor.process_once(timeout=0.2)
                # Check for timeout on active request
                if active_req:
                    started = active_req.get("started")
                    if started and time.time() - started > self.client.search_timeout:
                        append_log("Search timeout (session)")
                        active_req["error"] = "Search timeout"
                        active_req["done"].set()
                        self._teardown_handlers(server, handlers)
                        active_req = None
                        handlers = []
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

    def _start_search_request(self, req: dict, server, reactor) -> List[tuple]:
        """Wire handlers and kick off a search on the existing connection."""
        results: List[SearchResult] = []
        done = req["done"]
        error_ref = req
        temp_dir = self.client.cfg.temp_dir or self.client.settings.temp_dir
        allowed_bots = set([b.lower() for b in (self.client.cfg.allowed_bots or [])]) if self.client.cfg.allowed_bots else None
        parsed_results: List[SearchResult] = []
        req["started"] = time.time()

        def on_privmsg(conn, event):
            line = event.arguments[0]
            parsed = self.client._parse_search_line(line)
            if parsed:
                parsed.bot = event.source.split("!")[0] if event.source else None
                results.append(parsed)

        def on_ctcp(conn, event):
            if not event.arguments:
                return
            payload = (
                f"DCC {event.arguments[1]}"
                if len(event.arguments) >= 2 and event.arguments[0].upper() == "DCC" and event.arguments[1].upper().startswith("SEND")
                else event.arguments[0]
            )
            if payload.upper().startswith("DCC SEND"):
                sender = event.source.split("!")[0] if event.source else ""
                if allowed_bots and sender.lower() not in allowed_bots:
                    append_log(f"DCC from {sender} rejected (not allowed)")
                    error_ref["error"] = f"Sender {sender} not allowed"
                    done.set()
                    return
                try:
                    filename, host, port, size = self.client._parse_dcc_send(payload)
                    dest = (self.client.cfg.temp_dir or self.client.settings.temp_dir)
                    dest_path = None
                    if dest:
                        dest_path = self.client.resolve_path(dest) / filename
                    append_log(f"Accepting search DCC {filename} from {sender} at {host}:{port} size {size or 'unknown'}")
                    if not self.client._probe(host, port):
                        append_log(f"DCC probe failed to {host}:{port}")
                    if dest_path:
                        self.client._receive_dcc(host, port, size, dest_path)
                        append_log(f"Saved search results to {dest_path}")
                        self.client._parse_search_results_file(dest_path, parsed_results)
                except Exception as e:
                    append_log(f"DCC error: {e}")
                    error_ref["error"] = str(e)
                    done.set()

        handlers = [
            ("privmsg", on_privmsg),
            ("ctcp", on_ctcp),
        ]
        for name, handler in handlers:
            server.add_global_handler(name, handler)

        search_text = req["query"] if not req.get("author") else f"{req['query']} {req['author']}"
        append_log(f"SEARCH {search_text}")
        server.privmsg(self.client.cfg.irc_channel or self.client.settings.irc_channel, self.client.search_command.format(query=search_text))
        # Stash holders so we can return parsed results on completion
        req["results"] = parsed_results or results
        return handlers

    def _teardown_handlers(self, server, handlers: List[tuple]) -> None:
        for name, handler in handlers:
            try:
                server.remove_global_handler(name, handler)
            except Exception:
                pass

    def search(self, query: str, author: Optional[str] = None, timeout: int = 30) -> List[SearchResult]:
        if not self.connected or not self.client:
            raise RuntimeError("IRC session not connected")
        req = {"query": query, "author": author, "done": threading.Event(), "error": None, "results": []}
        self.request_q.put(req)
        done = req["done"].wait(timeout)
        if not done:
            raise RuntimeError("Search timed out")
        if req.get("error"):
            raise RuntimeError(req["error"])
        return req.get("results", [])

    def disconnect(self) -> None:
        with self.lock:
            self.connected = False
            self.stop_event.set()
            self.client = None
            append_log("Session disconnected")

    def status(self) -> dict:
        return {"connected": self.connected, "error": self.error}


session = IrcSession()
