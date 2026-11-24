"""LAN party browse: UDP discover request → leader announce reply.

Search alone never joins or invites. The member builds ``ws://reply_ip:ws_port``
only after the user picks a row (or auto-reconnect finds a saved ``leader_id``).
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_log = logging.getLogger("websocket.lan_discover")

# Dedicated UDP port (WebSocket stays on party_ws_port).
LAN_DISCOVER_PORT = 38765
PROTOCOL_V = 1
MAGIC = "manma_party"
DISCOVER_TYPE = "party_discover"
ANNOUNCE_TYPE = "party_announce"
DEFAULT_EXPIRE_S = 8.0
DEFAULT_ANNOUNCE_INTERVAL_S = 2.0
DEFAULT_BROWSE_INTERVAL_S = 1.5


def new_leader_id() -> str:
    return uuid.uuid4().hex


def ensure_leader_id(store: Any) -> str:
    """Read or create a stable leader_id on a profile / bag-like object."""
    lid = str(getattr(store, "party_leader_id", "") or "").strip()
    if lid:
        return lid
    if isinstance(store, dict):
        lid = str(store.get("leader_id") or store.get("party_leader_id") or "").strip()
        if lid:
            return lid
        lid = new_leader_id()
        store["leader_id"] = lid
        store["party_leader_id"] = lid
        return lid
    lid = new_leader_id()
    try:
        setattr(store, "party_leader_id", lid)
    except Exception:
        pass
    return lid


def _pack(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _unpack(raw: bytes) -> Optional[dict[str, Any]]:
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def announce_body(
    *,
    leader_id: str,
    session_id: str,
    name: str,
    ws_port: int,
    ready: bool,
    protocol: int = PROTOCOL_V,
) -> dict[str, Any]:
    return {
        "type": ANNOUNCE_TYPE,
        "magic": MAGIC,
        "v": int(protocol),
        "leader_id": str(leader_id or "").strip(),
        "session_id": str(session_id or "").strip(),
        "name": str(name or "").strip() or "leader",
        "ws_port": int(ws_port),
        "ready": bool(ready),
        "protocol": int(protocol),
    }


def parse_announce(body: Any, *, source_ip: str = "") -> Optional[dict[str, Any]]:
    if not isinstance(body, dict):
        return None
    if str(body.get("magic") or "") != MAGIC:
        return None
    if str(body.get("type") or "") != ANNOUNCE_TYPE:
        return None
    leader_id = str(body.get("leader_id") or "").strip()
    if not leader_id:
        return None
    try:
        ws_port = int(body.get("ws_port") or 0)
    except (TypeError, ValueError):
        return None
    if ws_port < 1 or ws_port > 65535:
        return None
    ready = bool(body.get("ready"))
    return {
        "leader_id": leader_id,
        "session_id": str(body.get("session_id") or "").strip(),
        "name": str(body.get("name") or "").strip() or "leader",
        "ws_port": ws_port,
        "ready": ready,
        "protocol": int(body.get("protocol") or body.get("v") or PROTOCOL_V),
        "host": str(source_ip or "").strip(),
        "status": "ready" if ready else "preparing",
        "status_label": "초대 가능" if ready else "게임 준비 중",
    }


@dataclass
class LanAnnouncer:
    """Respond to LAN discover probes while the party WebSocket is listening."""

    leader_id: str
    ws_port: int
    name: str = "leader"
    session_id: str = ""
    ready: bool = False
    port: int = LAN_DISCOVER_PORT
    interval_s: float = DEFAULT_ANNOUNCE_INTERVAL_S
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: Optional[threading.Thread] = field(default=None, repr=False)
    _sock: Optional[socket.socket] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(
        self,
        *,
        session_id: Optional[str] = None,
        name: Optional[str] = None,
        ready: Optional[bool] = None,
        ws_port: Optional[int] = None,
    ) -> None:
        with self._lock:
            if session_id is not None:
                self.session_id = str(session_id or "")
            if name is not None:
                self.name = str(name or "").strip() or "leader"
            if ready is not None:
                self.ready = bool(ready)
            if ws_port is not None:
                self.ws_port = int(ws_port)

    def _body(self) -> dict[str, Any]:
        with self._lock:
            return announce_body(
                leader_id=self.leader_id,
                session_id=self.session_id,
                name=self.name,
                ws_port=self.ws_port,
                ready=self.ready,
            )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="party-lan-announce", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._sock = None

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock = sock
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass
            sock.bind(("0.0.0.0", int(self.port)))
            sock.settimeout(0.5)
            _log.info("party lan announce listening udp/%s", self.port)
            while not self._stop.is_set():
                try:
                    raw, addr = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    continue
                body = _unpack(raw)
                if not isinstance(body, dict):
                    continue
                if str(body.get("magic") or "") != MAGIC:
                    continue
                if str(body.get("type") or "") != DISCOVER_TYPE:
                    continue
                try:
                    sock.sendto(_pack(self._body()), addr)
                except OSError as exc:
                    _log.debug("party lan announce reply failed: %s", exc)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            if self._sock is sock:
                self._sock = None


@dataclass
class DiscoveredLeader:
    leader_id: str
    host: str
    ws_port: int
    name: str = "leader"
    session_id: str = ""
    ready: bool = False
    protocol: int = PROTOCOL_V
    seen_at: float = 0.0

    @property
    def status_label(self) -> str:
        return "초대 가능" if self.ready else "게임 준비 중"

    def as_dict(self) -> dict[str, Any]:
        return {
            "leader_id": self.leader_id,
            "host": self.host,
            "ws_port": self.ws_port,
            "name": self.name,
            "session_id": self.session_id,
            "ready": self.ready,
            "protocol": self.protocol,
            "status": "ready" if self.ready else "preparing",
            "status_label": self.status_label,
            "seen_at": self.seen_at,
            "endpoint": f"{self.host}:{self.ws_port}",
        }


class LanBrowser:
    """Background UDP browse. Dedupes by ``leader_id``; expires silent rows."""

    def __init__(
        self,
        *,
        port: int = LAN_DISCOVER_PORT,
        expire_s: float = DEFAULT_EXPIRE_S,
        interval_s: float = DEFAULT_BROWSE_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.port = int(port)
        self.expire_s = float(expire_s)
        self.interval_s = float(interval_s)
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._rows: dict[str, DiscoveredLeader] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="party-lan-browse", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._lock:
            dead = [
                key
                for key, row in self._rows.items()
                if now - float(row.seen_at) > self.expire_s
            ]
            for key in dead:
                self._rows.pop(key, None)
            rows = sorted(
                self._rows.values(),
                key=lambda r: (not r.ready, r.name.casefold(), r.leader_id),
            )
            return [row.as_dict() for row in rows]

    def find(self, leader_id: str) -> Optional[dict[str, Any]]:
        key = str(leader_id or "").strip()
        if not key:
            return None
        for row in self.snapshot():
            if row.get("leader_id") == key:
                return row
        return None

    def _note(self, row: dict[str, Any]) -> None:
        lid = str(row.get("leader_id") or "").strip()
        host = str(row.get("host") or "").strip()
        if not lid or not host:
            return
        with self._lock:
            prev = self._rows.get(lid)
            self._rows[lid] = DiscoveredLeader(
                leader_id=lid,
                host=host,
                ws_port=int(row["ws_port"]),
                name=str(row.get("name") or (prev.name if prev else "leader")),
                session_id=str(row.get("session_id") or ""),
                ready=bool(row.get("ready")),
                protocol=int(row.get("protocol") or PROTOCOL_V),
                seen_at=self._clock(),
            )

    def probe_once(self, timeout_s: float = 0.8) -> list[dict[str, Any]]:
        """One broadcast round for tests / sync callers."""
        req = _pack({"type": DISCOVER_TYPE, "magic": MAGIC, "v": PROTOCOL_V})
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(max(0.1, float(timeout_s)))
            sock.bind(("0.0.0.0", 0))
            for target in (("<broadcast>", self.port), ("255.255.255.255", self.port)):
                try:
                    sock.sendto(req, target)
                except OSError:
                    continue
            deadline = time.time() + max(0.1, float(timeout_s))
            while time.time() < deadline:
                try:
                    raw, addr = sock.recvfrom(2048)
                except socket.timeout:
                    break
                except OSError:
                    break
                parsed = parse_announce(_unpack(raw), source_ip=str(addr[0]))
                if parsed is not None:
                    self._note(parsed)
        finally:
            try:
                sock.close()
            except Exception:
                pass
        return self.snapshot()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.probe_once(timeout_s=min(0.8, self.interval_s))
            except Exception as exc:
                _log.debug("party lan browse failed: %s", exc)
            self._stop.wait(self.interval_s)


def resolve_leader_endpoint(
    *,
    leader_id: str,
    last_host: str = "",
    last_port: int = 8765,
    browser: Optional[LanBrowser] = None,
    probe_s: float = 1.2,
) -> Optional[tuple[str, int]]:
    """Prefer the cached host; on miss, browse for the same ``leader_id``."""
    lid = str(leader_id or "").strip()
    host = str(last_host or "").strip()
    try:
        port = int(last_port or 8765)
    except (TypeError, ValueError):
        port = 8765
    if host:
        return host, max(1, min(65535, port))
    if not lid:
        return None
    owned = browser is None
    scan = browser if browser is not None else LanBrowser()
    try:
        if owned:
            scan.probe_once(timeout_s=probe_s)
        else:
            scan.probe_once(timeout_s=probe_s)
        hit = scan.find(lid)
        if hit is None:
            return None
        return str(hit["host"]), int(hit["ws_port"])
    finally:
        if owned:
            scan.stop(timeout=0.5)


__all__ = [
    "ANNOUNCE_TYPE",
    "DISCOVER_TYPE",
    "DEFAULT_EXPIRE_S",
    "DiscoveredLeader",
    "LAN_DISCOVER_PORT",
    "LanAnnouncer",
    "LanBrowser",
    "MAGIC",
    "PROTOCOL_V",
    "announce_body",
    "ensure_leader_id",
    "new_leader_id",
    "parse_announce",
    "resolve_leader_endpoint",
]
