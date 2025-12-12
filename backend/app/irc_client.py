"""
IRC/DCC helper for channel search and pack download.
This is a best-effort implementation using the `irc` library; adjust parsing
and commands to match the channel bot's protocol.
"""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
import re
import socket
import time
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

import irc.client
import irc.connection
from jaraco.stream import buffer as jsbuffer

from .config_store import load_config
from .config import get_settings
from .schemas import SearchResult
from .irc_log import append_log


class IrcSearchError(Exception):
    pass


class IrcDownloadError(Exception):
    pass


class IrcClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cfg = load_config()
        self.search_timeout = 15
        self.dcc_timeout = 60
        self.search_command = "@search {query}"
        self.download_command = "@download {id}"

    def sanitize_query(self, query: str, author: Optional[str] = None) -> str:
        q = (query or "").strip()
        # drop a trailing extension like .epub/.pdf/etc.
        q = re.sub(r"\.[a-zA-Z0-9]{1,5}$", "", q)
        # remove punctuation that the bot may treat as syntax errors
        q = re.sub(r"[^\\w\\s'\\-]", " ", q)
        if author:
            q = f"{q} {author}".strip()
        q = re.sub(r"\\s+", " ", q).strip()
        return q

    def _connect(self, nick_override: Optional[str] = None) -> Tuple[irc.client.Reactor, irc.client.ServerConnection]:
        irc.client.ServerConnection.buffer_class = jsbuffer.LenientDecodingLineBuffer
        reactor = irc.client.Reactor()
        host = self.cfg.irc_server or self.settings.irc_server
        port = self.cfg.irc_port or self.settings.irc_port
        nick = nick_override or self.cfg.irc_nick or self.settings.irc_nick
        append_log(f"Connecting to {host}:{port} as {nick}")
        try:
            connect_kwargs = {
                "server": host,
                "port": port,
                "nickname": nick,
                "ircname": self.cfg.irc_realname or self.settings.irc_realname,
            }
            if self.cfg.irc_ssl:
                append_log("Using SSL/TLS")
                ctx = ssl.create_default_context()
                if self.cfg.irc_ssl_verify is False:
                    append_log("SSL verify disabled")
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                factory = irc.connection.Factory(wrapper=lambda sock, **kwargs: ctx.wrap_socket(sock, server_hostname=host))
                connect_kwargs["connect_factory"] = factory
            server = reactor.server().connect(**connect_kwargs)
        except Exception as e:
            append_log(f"IRC connection failed: {e}")
            raise IrcSearchError(f"IRC connection failed: {e}") from e

        def log_event(prefix: str):
            return lambda c, e: append_log(f"{prefix}: {e.type} {e.arguments}")

        server.add_global_handler("welcome", lambda c, e: append_log("Connected (RPL_WELCOME)"))
        server.add_global_handler("nicknameinuse", log_event("Nick in use"))
        server.add_global_handler("disconnect", log_event("Disconnected"))
        server.add_global_handler("error", log_event("IRC error"))
        server.add_global_handler("failed_auth", log_event("Auth error"))
        server.add_global_handler("nochanmodes", log_event("Channel error"))
        server.add_global_handler("erroneusnickname", log_event("Bad nick"))
        server.add_global_handler("cap", log_event("CAP"))
        server.add_global_handler("001", log_event("RPL_WELCOME"))
        server.add_global_handler("002", log_event("RPL_YOURHOST"))
        server.add_global_handler("003", log_event("RPL_CREATED"))
        server.add_global_handler("004", log_event("RPL_MYINFO"))
        server.add_global_handler("005", log_event("RPL_ISUPPORT"))
        server.add_global_handler("notice", log_event("NOTICE"))
        server.add_global_handler("privnotice", log_event("PRIVNOTICE"))
        server.add_global_handler("pong", log_event("PONG"))
        server.add_global_handler("connected", lambda c, e: append_log("TCP connected"))
        server.add_global_handler("ctcp", log_event("CTCP"))
        server.add_global_handler("invite", log_event("INVITE"))
        server.add_global_handler("474", log_event("ERR_BANNEDFROMCHAN"))
        server.add_global_handler("473", log_event("ERR_INVITEONLYCHAN"))
        server.add_global_handler("477", log_event("ERR_NEEDREGGEDNICK"))
        server.add_global_handler("471", log_event("ERR_CHANNELISFULL"))
        return reactor, server

    def _connect_and_join(self) -> Tuple[irc.client.Reactor, irc.client.ServerConnection]:
        base_nick = self.cfg.irc_nick or self.settings.irc_nick
        last_error: Optional[Exception] = None
        for attempt in range(3):
            nick = base_nick if attempt == 0 else f"{base_nick}_{attempt}"
            reactor, server = self._connect(nick_override=nick)
            target = self.cfg.irc_channel or self.settings.irc_channel
            welcome = asyncio.Event()
            joined = asyncio.Event()

            def on_welcome(conn, event):
                append_log("Welcome received, registering done")
                welcome.set()

            def on_join(conn, event):
                if event.target.lower() == target.lower():
                    append_log(f"Joined {target}")
                    joined.set()

            server.add_global_handler("welcome", lambda c, e: on_welcome(c, e))
            server.add_global_handler("001", lambda c, e: on_welcome(c, e))
            server.add_global_handler("join", lambda c, e: on_join(c, e))

            start = time.time()
            # Wait for welcome
            while not welcome.is_set() and time.time() - start < 10:
                reactor.process_once(timeout=0.2)
            if not welcome.is_set():
                append_log("Welcome timeout")
                last_error = IrcSearchError("Welcome timeout")
                server.disconnect("welcome-timeout")
                continue

            append_log(f"Joining {target}")
            server.join(target)
            start_join = time.time()
            while not joined.is_set() and time.time() - start_join < 10:
                reactor.process_once(timeout=0.2)
            if not joined.is_set():
                append_log(f"Join timeout for {target}")
                last_error = IrcSearchError(f"Join timeout for {target}")
                server.disconnect("join-timeout")
                continue

            return reactor, server
        if last_error:
            raise last_error
        raise IrcSearchError("Failed to connect")

    def _join_and_wait(self, server: irc.client.ServerConnection, reactor: irc.client.Reactor) -> None:
        target = self.cfg.irc_channel or self.settings.irc_channel
        joined = asyncio.Event()

        def on_join(conn, event):
            if event.target.lower() == target.lower():
                append_log(f"Joined {target}")
                joined.set()

        append_log(f"Joining {target}")
        server.add_global_handler("join", on_join)
        server.join(target)
        start = time.time()
        while not joined.is_set() and time.time() - start < 10:
            reactor.process_once(timeout=0.2)
        if not joined.is_set():
            append_log(f"Join timeout for {target}")
            raise IrcSearchError(f"Join timeout for {target}")

    def _parse_search_line(self, line: str) -> Optional[SearchResult]:
        # Heuristic parse, adjust to your bot's format.
        m = re.search(r"(?P<id>\d+).*?(?P<title>[^\|]+)", line)
        if not m:
            return None
        return SearchResult(
            id=m.group("id"),
            title=m.group("title").strip(),
            description=line.strip(),
            bot=None,
            size_bytes=None,
        )

    async def search(self, query: str, author: Optional[str] = None) -> List[SearchResult]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_sync, query, author)

    def _search_sync(self, query: str, author: Optional[str]) -> List[SearchResult]:
        reactor, server = self._connect_and_join()
        target = self.cfg.irc_channel or self.settings.irc_channel
        results: List[SearchResult] = []
        done = False
        dcc_file: Optional[Path] = None
        temp_dir = Path(self.cfg.temp_dir or self.settings.temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        allowed_bots = set([b.lower() for b in (self.cfg.allowed_bots or [])]) if self.cfg.allowed_bots else None
        parsed_results: List[SearchResult] = []

        def on_privmsg(conn, event):
            line = event.arguments[0]
            append_log(f"<{event.source}> {line}")
            parsed = self._parse_search_line(line)
            if parsed:
                parsed.bot = event.source.split("!")[0] if event.source else None
                results.append(parsed)

        def on_ctcp(conn, event):
            nonlocal dcc_file
            if not event.arguments:
                return
            payload = (
                f"DCC {event.arguments[1]}"
                if len(event.arguments) >= 2 and event.arguments[0].upper() == "DCC" and event.arguments[1].upper().startswith("SEND")
                else event.arguments[0]
            )
            if payload.upper().startswith("DCC SEND"):
                sender = event.source.split("!")[0] if event.source else ""
                append_log(f"CTCP DCC from {sender}: {event.arguments}")
                if allowed_bots and sender.lower() not in allowed_bots:
                    append_log(f"DCC from {sender} rejected (not allowed)")
                    return
                try:
                    filename, host, port, size = self._parse_dcc_send(payload)
                    dest = temp_dir / filename
                    append_log(f"Accepting search DCC {filename} from {sender} at {host}:{port} size {size or 'unknown'}")
                    if not self._probe(host, port):
                        append_log(f"DCC probe failed to {host}:{port}")
                    self._receive_dcc(host, port, size, dest)
                    dcc_file = dest
                    append_log(f"Saved search results to {dest}")
                    self._parse_search_results_file(dest, parsed_results)
                except Exception as e:
                    append_log(f"DCC error: {e}")

        server.add_global_handler("privmsg", on_privmsg)
        server.add_global_handler("ctcp", on_ctcp)
        search_text = self.sanitize_query(query, author)
        append_log(f"SEARCH {search_text}")
        server.privmsg(target, self.search_command.format(query=search_text))
        start = time.time()
        while time.time() - start < self.search_timeout:
            reactor.process_once(timeout=0.2)
        server.disconnect("done")
        return parsed_results or results

    async def download_pack(self, result_id: str, bot: Optional[str], dest: Path) -> Path:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._download_sync, result_id, bot, dest)

    def _download_sync(self, result_id: str, bot: Optional[str], dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        reactor, server = self._connect_and_join()
        target = self.cfg.irc_channel or self.settings.irc_channel
        allowed_bots = set([b.lower() for b in (self.cfg.allowed_bots or [])]) if self.cfg.allowed_bots else None
        download_started = False
        download_error: Optional[str] = None
        done = False

        def on_privmsg(conn, event):
            if bot and event.source and bot.lower() not in event.source.lower():
                return
            # Some bots may send instructions before DCC; no-op.
            append_log(f"<{event.source}> {event.arguments[0]}")

        def on_ctcp(conn, event):
            nonlocal download_started, done, download_error
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
                    download_error = f"Sender {sender} not allowed"
                    done = True
                    return
                try:
                    filename, host, port, size = self._parse_dcc_send(payload)
                    append_log(f"Accepting DCC {filename} from {sender} at {host}:{port} size {size or 'unknown'}")
                    self._receive_dcc(host, port, size, dest)
                    download_started = True
                    done = True
                except Exception as e:
                    append_log(f"DCC error: {e}")
                    download_error = str(e)
                    done = True

        server.add_global_handler("privmsg", on_privmsg)
        server.add_global_handler("ctcp", on_ctcp)

        self._join_and_wait(server, reactor)
        append_log(f"DOWNLOAD {result_id} via {bot or 'unknown'}")
        server.privmsg(target, self.download_command.format(id=result_id))
        start = time.time()
        while not done and time.time() - start < self.dcc_timeout:
            reactor.process_once(timeout=0.2)
        server.disconnect("done")

        if download_error:
            raise IrcDownloadError(download_error)
        if not download_started:
            append_log("No DCC SEND received")
            raise IrcDownloadError("No DCC SEND received")
        if not done:
            append_log(f"DCC wait timeout after {self.dcc_timeout}s")
        return dest

    def _parse_dcc_send(self, payload: str) -> Tuple[str, str, int, Optional[int]]:
        # Payload example: "DCC SEND filename ip port size"
        parts = payload.split()
        if len(parts) < 5:
            raise IrcDownloadError(f"Invalid DCC payload: {payload}")
        filename = parts[2].strip('"')
        ip_raw = int(parts[3])
        host = str(ipaddress.IPv4Address(ip_raw))
        port = int(parts[4])
        size = int(parts[5]) if len(parts) > 5 else None
        max_size = self.cfg.max_download_bytes
        if max_size and size and size > max_size:
            raise IrcDownloadError(f"File too large: {size} bytes")
        return filename, host, port, size

    def _parse_search_results_file(self, path: Path, results: List[SearchResult]) -> None:
        try:
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path, "r") as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(".txt"):
                            with zf.open(name) as f:
                                text = f.read().decode("latin-1", errors="ignore")
                                self._parse_results_text(text, results)
            else:
                text = path.read_bytes().decode("latin-1", errors="ignore")
                self._parse_results_text(text, results)
        except Exception as e:
            append_log(f"Result parse error: {e}")

    def _parse_results_text(self, text: str, results: List[SearchResult]) -> None:
        for line in text.splitlines():
            parsed = self._parse_search_line(line)
            if parsed:
                results.append(parsed)

    def _receive_dcc(self, host: str, port: int, size: Optional[int], dest: Path) -> None:
        append_log(f"DCC connect -> {host}:{port} (expect size {size or 'unknown'})")
        start = time.time()
        total = 0
        try:
            with socket.create_connection((host, port), timeout=self.dcc_timeout) as sock, dest.open("wb") as fh:
                append_log(f"DCC socket established to {host}:{port}")
                remaining = size
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        append_log("DCC recv got EOF")
                        break
                    fh.write(chunk)
                    total += len(chunk)
                    # Send cumulative ACK to satisfy DCC SEND protocol.
                    try:
                        sock.sendall(total.to_bytes(4, byteorder="big", signed=False))
                    except Exception as e:
                        append_log(f"DCC ack send failed after {total} bytes: {e}")
                    if remaining is not None:
                        remaining -= len(chunk)
                        if remaining <= 0:
                            append_log("DCC recv reached declared size")
                            break
        except Exception as e:
            append_log(f"DCC socket error {host}:{port} after {total} bytes: {e}")
            raise
        elapsed = time.time() - start
        append_log(f"Saved DCC to {dest} ({total} bytes in {elapsed:.2f}s)")

    def resolve_path(self, path_str: str) -> Path:
        return Path(path_str).expanduser().resolve()

    def _probe(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=5):
                append_log(f"Probe OK to {host}:{port}")
                return True
        except Exception as e:
            append_log(f"Probe failed to {host}:{port}: {e}")
            return False
