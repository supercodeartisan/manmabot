"""Party WebSocket client — connect to one :class:`PartyServer`.

Independent of decide/session. Use :meth:`PartyClient.connect` /
:meth:`PartyClient.close`. Received frames land in :attr:`inbox`.

Requires the ``websockets`` package.
"""
from __future__ import annotations

import asyncio
import logging
import queue
import random
import threading
from typing import Any, Callable, Optional

from .protocol import PartyMessage, parse_frame

_log = logging.getLogger("websocket.client")

MessageHandler = Callable[[PartyMessage], None]


class PartyClient:
    """Connect as one of N clients to a single party server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        path: str = "/",
        sender: str = "",
        inbox_max: int = 256,
        on_message: Optional[MessageHandler] = None,
        reconnect: bool = True,
        reconnect_delay_s: float = 2.0,
    ) -> None:
        self.host = str(host or "127.0.0.1")
        self.port = int(port)
        self.path = str(path or "/")
        if not self.path.startswith("/"):
            self.path = "/" + self.path
        self.sender = str(sender or "").strip()
        self.on_message = on_message
        self.reconnect = bool(reconnect)
        self.reconnect_delay_s = max(0.2, float(reconnect_delay_s))
        self._reconnect_wait = self.reconnect_delay_s
        self.inbox: queue.Queue[PartyMessage] = queue.Queue(maxsize=max(1, int(inbox_max)))
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._ws: Any = None
        self._send_q: queue.Queue[str] = queue.Queue()

    @property
    def uri(self) -> str:
        return f"ws://{self.host}:{self.port}{self.path}"

    @property
    def connected(self) -> bool:
        return self._ws is not None and self.running

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def connect(self, *, timeout: float = 10.0, wait: bool = True) -> None:
        """Open the client loop on a background thread.

        ``wait=False`` returns immediately and keeps reconnecting until
        :meth:`close`. The member bot uses that so a down leader does not
        stop the farm.
        """
        if self.running:
            return
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"party-ws-client:{self.host}:{self.port}",
            daemon=True,
        )
        self._thread.start()
        if not wait:
            return
        if not self._ready.wait(timeout=max(0.1, float(timeout))):
            self.close()
            raise TimeoutError(f"party client failed to connect to {self.uri}")
        if self._error is not None:
            err = self._error
            self.close()
            raise RuntimeError(f"party client connect failed: {err}") from err

    def close(self, *, timeout: float = 5.0) -> None:
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
        self._ws = None

    def send(self, message: PartyMessage | dict[str, Any] | str, *, sender: str = "") -> None:
        """Queue one frame to the server (flushed by the IO thread)."""
        frame = self._coerce(message, sender=sender or self.sender)
        if not self.running:
            raise RuntimeError("party client is not running")
        try:
            self._send_q.put_nowait(frame.to_json())
        except queue.Full as exc:
            raise RuntimeError("party client send queue full") from exc
        from .traffic_log import note

        note("sent", frame)

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

    def _coerce(
        self,
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
            loop.run_until_complete(self._run())
        except BaseException as exc:
            self._error = exc
            _log.exception("party client stopped with error")
        finally:
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

    def status(self) -> dict[str, Any]:
        return {
            "role": "client",
            "uri": self.uri,
            "sender": self.sender,
            "running": self.running,
            "connected": self.connected,
            "reconnect": self.reconnect,
            "last_error": str(self._error) if self._error else "",
        }

    async def _run(self) -> None:
        first = True
        while not self._stop.is_set():
            try:
                await self._session()
                first = False
                _log.info(
                    "party client session ended uri=%s connected=%s",
                    self.uri,
                    False,
                )
            except Exception as exc:
                if first:
                    self._error = exc
                    self._ready.set()
                    if not self.reconnect:
                        return
                _log.warning(
                    "party client connection error uri=%s err=%s; reconnect=%s delay=%.1fs",
                    self.uri,
                    exc,
                    self.reconnect,
                    self.reconnect_delay_s,
                )
            self._ws = None
            if self._stop.is_set() or not self.reconnect:
                break
            # 2s + jitter at first, doubling, never past 15s. A live session
            # resets the wait (see ``_session``).
            jitter = random.uniform(0.0, min(1.0, self._reconnect_wait * 0.5))
            pause = min(15.0, self._reconnect_wait + jitter)
            _log.info(
                "party client reconnecting to %s in %.1fs",
                self.uri,
                pause,
            )
            await asyncio.sleep(pause)
            self._reconnect_wait = min(15.0, max(self.reconnect_delay_s, self._reconnect_wait * 2))
            first = False

    async def _session(self) -> None:
        import websockets

        _log.info("party client connecting to %s", self.uri)
        async with websockets.connect(
            self.uri,
            ping_interval=20,
            ping_timeout=20,
            max_size=1 << 20,
        ) as ws:
            self._ws = ws
            self._error = None
            self._reconnect_wait = self.reconnect_delay_s
            if not self._ready.is_set():
                self._ready.set()
            _log.info(
                "party client connected uri=%s sender=%s",
                self.uri,
                self.sender or "-",
            )
            reader = asyncio.create_task(self._read_loop(ws))
            writer = asyncio.create_task(self._write_loop(ws))
            stopper = asyncio.create_task(self._wait_stop())
            done, pending = await asyncio.wait(
                {reader, writer, stopper},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, asyncio.CancelledError):
                    raise exc

    async def _wait_stop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.1)

    async def _read_loop(self, ws: Any) -> None:
        async for raw in ws:
            try:
                msg = parse_frame(raw)
            except Exception as exc:
                _log.warning("bad party frame: %s", exc)
                continue
            self._deliver(msg)

    async def _write_loop(self, ws: Any) -> None:
        while not self._stop.is_set():
            try:
                payload = self._send_q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.02)
                continue
            await ws.send(payload)

    def _deliver(self, msg: PartyMessage) -> None:
        # The server relays a client's own frame back. That echo is not a new message.
        if str(msg.sender or "") != self.sender or not self.sender:
            from .traffic_log import note

            note("recv", msg)
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
                _log.warning("party client inbox full; dropped message")
        if self.on_message is not None:
            try:
                self.on_message(msg)
            except Exception:
                _log.exception("party client on_message failed")


__all__ = ["MessageHandler", "PartyClient"]
