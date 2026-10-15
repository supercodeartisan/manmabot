"""Party WebSocket server — one host, N client bots.

Stability:
- WebSocket ping/pong keeps dead peers detectable.
- Failed sends drop that client from the roster.
- ``reuse_address`` + in-thread rebind after listen crash.
- For whole-thread death, wrap with :class:`websocket.watchdog.PartyServerWatchdog`.
- Status changes are logged (listen / client up-down / rebind / stop).

Independent of decide/session. Requires ``websockets``.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import socket
import threading
import time
from typing import Any, Callable, Optional

from .protocol import PartyMessage, parse_frame

_log = logging.getLogger("websocket.server")

MessageHandler = Callable[[PartyMessage, str], None]


class PartyServer:
    """Listen on ``host:port`` and fan-out party messages to connected clients."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        *,
        inbox_max: int = 256,
        on_message: Optional[MessageHandler] = None,
        ping_interval: float = 20.0,
        ping_timeout: float = 20.0,
        auto_rebind: bool = True,
        rebind_delay_s: float = 0.5,
        status_log_interval_s: float = 30.0,
    ) -> None:
        self.host = str(host or "0.0.0.0")
        self.port = int(port)
        self.on_message = on_message
        self.ping_interval = max(5.0, float(ping_interval))
        self.ping_timeout = max(5.0, float(ping_timeout))
        self.auto_rebind = bool(auto_rebind)
        self.rebind_delay_s = max(0.1, float(rebind_delay_s))
        self.status_log_interval_s = max(0.0, float(status_log_interval_s))
        self.inbox: queue.Queue[PartyMessage] = queue.Queue(maxsize=max(1, int(inbox_max)))
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._clients: dict[str, Any] = {}
        self._client_lock = threading.Lock()
        self._seq = 0
        self._server = None
        self._listening = False
        self._started_at = 0.0
        self._listen_epoch = 0
        self._last_status: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    @property
    def listening(self) -> bool:
        return bool(self._listening) and self.running

    def client_count(self) -> int:
        with self._client_lock:
            return len(self._clients)

    def client_ids(self) -> list[str]:
        with self._client_lock:
            return list(self._clients.keys())

    def status(self) -> dict[str, Any]:
        """Snapshot for logs / UI (safe to call from any thread)."""
        return {
            "role": "server",
            "host": self.host,
            "port": self.port,
            "running": self.running,
            "listening": self.listening,
            "clients": self.client_count(),
            "client_ids": self.client_ids(),
            "listen_epoch": self._listen_epoch,
            "uptime_s": (
                round(time.time() - self._started_at, 1) if self._started_at else 0.0
            ),
            "last_error": str(self._error) if self._error else "",
        }

    def start(self, *, timeout: float = 5.0) -> None:
        """Bind and accept clients on a background asyncio thread."""
        if self.running:
            return
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._listening = False
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"party-ws-server:{self.port}",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=max(0.1, float(timeout))):
            self.stop()
            raise TimeoutError(
                f"party server failed to start on {self.host}:{self.port}"
            )
        if self._error is not None and not self.listening:
            err = self._error
            self.stop()
            raise RuntimeError(f"party server start failed: {err}") from err
        self._log_status("started")

    def stop(self, *, timeout: float = 5.0) -> None:
        self._log_status("stopping")
        self._stop.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(lambda: None)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, float(timeout)))
        self._thread = None
        self._loop = None
        self._server = None
        self._listening = False
        with self._client_lock:
            self._clients.clear()
        self._log_status("stopped")

    def broadcast(self, message: PartyMessage | dict[str, Any] | str, *, sender: str = "") -> int:
        frame = self._coerce(message, sender=sender)
        return self._run_coro(self._broadcast(frame))

    def send_to(
        self,
        client_id: str,
        message: PartyMessage | dict[str, Any] | str,
        *,
        sender: str = "",
    ) -> bool:
        frame = self._coerce(message, sender=sender)
        return bool(self._run_coro(self._send_to(str(client_id), frame)))

    def poll(self, timeout: float = 0.0) -> Optional[PartyMessage]:
        try:
            return self.inbox.get(timeout=max(0.0, float(timeout)))
        except queue.Empty:
            return None

    def drain(self, limit: int = 64) -> list[PartyMessage]:
        out: list[PartyMessage] = []
        for _ in range(max(0, int(limit))):
            item = self.poll(0.0)
            if item is None:
                break
            out.append(item)
        return out

    def _log_status(self, event: str) -> None:
        snap = self.status()
        snap["event"] = event
        self._last_status = snap
        _log.info(
            "party server status event=%s listening=%s clients=%s host=%s port=%s epoch=%s err=%s",
            event,
            snap["listening"],
            snap["clients"],
            snap["host"],
            snap["port"],
            snap["listen_epoch"],
            snap["last_error"] or "-",
        )

    @staticmethod
    def _coerce(
        message: PartyMessage | dict[str, Any] | str,
        *,
        sender: str = "",
    ) -> PartyMessage:
        if isinstance(message, PartyMessage):
            if sender and not message.sender:
                message.sender = sender
            return message
        if isinstance(message, dict):
            msg = PartyMessage.from_dict(message)
            if sender and not msg.sender:
                msg.sender = sender
            return msg
        return PartyMessage(sender=sender, message=str(message))

    def _run_coro(self, coro: Any) -> Any:
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("party server is not running")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=10.0)

    def _thread_main(self) -> None:
        try:
            import websockets  # noqa: F401
        except ImportError as exc:
            self._error = exc
            self._ready.set()
            return
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve_supervised())
        except BaseException as exc:
            self._error = exc
            _log.exception("party server stopped with error")
        finally:
            self._listening = False
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            except Exception:
                pass
            loop.close()
            self._loop = None
            self._ready.set()
            self._log_status("thread_exit")

    async def _serve_supervised(self) -> None:
        """Bind loop: on unexpected death, rebind quickly when auto_rebind=True."""
        first = True
        while not self._stop.is_set():
            try:
                await self._serve_once()
                first = False
            except OSError as exc:
                self._error = exc
                self._listening = False
                self._log_status("bind_failed")
                if first:
                    self._ready.set()
                    if not self.auto_rebind:
                        return
                if self._stop.is_set() or not self.auto_rebind:
                    return
                _log.warning(
                    "party server rebind in %.1fs after OSError: %s",
                    self.rebind_delay_s,
                    exc,
                )
                await asyncio.sleep(self.rebind_delay_s)
                first = False
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error = exc
                self._listening = False
                self._log_status("serve_crashed")
                if first:
                    self._ready.set()
                    if not self.auto_rebind:
                        return
                if self._stop.is_set() or not self.auto_rebind:
                    return
                _log.warning(
                    "party server rebind in %.1fs after crash: %s",
                    self.rebind_delay_s,
                    exc,
                )
                await asyncio.sleep(self.rebind_delay_s)
                first = False
            else:
                # Clean exit from _serve_once (stop requested).
                return

    async def _serve_once(self) -> None:
        import websockets

        async def _handler(websocket: Any, *_args: Any) -> None:
            await self._client_loop(websocket)

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Windows: helps reclaim the port right after a hard kill.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 0)
                except OSError:
                    pass
            sock.bind((self.host, self.port))
            sock.listen(128)
            sock.setblocking(False)
        except Exception:
            sock.close()
            raise

        self._server = await websockets.serve(
            _handler,
            sock=sock,
            ping_interval=self.ping_interval,
            ping_timeout=self.ping_timeout,
            max_size=1 << 20,
        )
        self._listen_epoch += 1
        self._listening = True
        self._error = None
        if not self._ready.is_set():
            self._ready.set()
        self._log_status("listening")

        status_task = None
        if self.status_log_interval_s > 0:
            status_task = asyncio.create_task(self._status_heartbeat())

        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.1)
        finally:
            if status_task is not None:
                status_task.cancel()
                try:
                    await status_task
                except asyncio.CancelledError:
                    pass
            self._listening = False
            server = self._server
            self._server = None
            if server is not None:
                server.close()
                await server.wait_closed()
            with self._client_lock:
                sockets = list(self._clients.items())
                self._clients.clear()
            for client_id, ws in sockets:
                try:
                    await ws.close()
                except Exception:
                    pass
                _log.info("party client closed on shutdown id=%s", client_id)
            self._log_status("listen_closed")

    async def _status_heartbeat(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self.status_log_interval_s)
            if self._stop.is_set():
                break
            self._log_status("heartbeat")

    async def _client_loop(self, websocket: Any) -> None:
        client_id = self._register(websocket)
        remote = "?"
        try:
            addr = websocket.remote_address
            if addr:
                remote = f"{addr[0]}:{addr[1]}"
        except Exception:
            remote = "?"
        _log.info(
            "party client connected id=%s remote=%s clients=%s",
            client_id,
            remote,
            self.client_count(),
        )
        self._log_status("client_connected")
        try:
            async for raw in websocket:
                try:
                    msg = parse_frame(raw)
                except Exception as exc:
                    _log.warning("bad party frame from %s: %s", client_id, exc)
                    continue
                self._deliver(msg, client_id)
        except Exception as exc:
            _log.info("party client disconnected id=%s (%s)", client_id, exc)
        finally:
            self._unregister(client_id)
            _log.info(
                "party client removed id=%s clients=%s",
                client_id,
                self.client_count(),
            )
            self._log_status("client_removed")

    def _register(self, websocket: Any) -> str:
        with self._client_lock:
            self._seq += 1
            client_id = f"c{self._seq}"
            self._clients[client_id] = websocket
            return client_id

    def _unregister(self, client_id: str) -> None:
        with self._client_lock:
            self._clients.pop(client_id, None)

    def _deliver(self, msg: PartyMessage, client_id: str) -> None:
        try:
            self.inbox.put_nowait(msg)
        except queue.Full:
            try:
                self.inbox.get_nowait()
            except queue.Empty:
                pass
            try:
                self.inbox.put_nowait(msg)
            except queue.Full:
                _log.warning("party server inbox full; dropped message")
        if self.on_message is not None:
            try:
                self.on_message(msg, client_id)
            except Exception:
                _log.exception("party server on_message failed")

    async def _broadcast(self, message: PartyMessage) -> int:
        payload = message.to_json()
        with self._client_lock:
            items = list(self._clients.items())
        dead: list[str] = []
        sent = 0
        for client_id, ws in items:
            try:
                await ws.send(payload)
                sent += 1
            except Exception:
                dead.append(client_id)
        for client_id in dead:
            self._unregister(client_id)
            _log.info("party client dropped on send id=%s", client_id)
        if dead:
            self._log_status("clients_pruned")
        return sent

    async def _send_to(self, client_id: str, message: PartyMessage) -> bool:
        with self._client_lock:
            ws = self._clients.get(client_id)
        if ws is None:
            return False
        try:
            await ws.send(message.to_json())
            return True
        except Exception:
            self._unregister(client_id)
            _log.info("party client dropped on send id=%s", client_id)
            self._log_status("clients_pruned")
            return False


__all__ = ["MessageHandler", "PartyServer"]
