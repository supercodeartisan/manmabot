"""Start / stop the party WebSocket (leader server or member client)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

LogFn = Callable[[str], None]


@dataclass
class LeaderLink:
    watchdog: Any
    owned: bool
    advertise: str
    port: int


@dataclass
class MemberLink:
    client: Any
    heartbeat: Any
    host: str
    port: int


def _clamp_port(raw: Any) -> int:
    try:
        port = int(raw or 8765)
    except (TypeError, ValueError):
        port = 8765
    return max(1, min(65535, port))


def start_leader_link(
    *,
    port: Any = 8765,
    log: Optional[LogFn] = None,
) -> Optional[LeaderLink]:
    """Bind the party server (or reuse one already listening on ``port``)."""
    note = log or (lambda _m: None)
    port_i = _clamp_port(port)
    try:
        from websocket.active import current, publish
        from websocket.netinfo import local_ipv4
        from websocket.watchdog import PartyServerWatchdog

        existing = current()
        if (
            existing is not None
            and existing.running
            and int(existing.server.port) == port_i
        ):
            note(f"Party socket already listening on port {port_i}. Using that server.")
            try:
                advertise = local_ipv4()
            except Exception:
                advertise = "127.0.0.1"
            return LeaderLink(
                watchdog=existing, owned=False, advertise=advertise, port=port_i
            )

        watchdog = PartyServerWatchdog(
            host="0.0.0.0",
            port=port_i,
            relay=True,
            announce=True,
        )
        watchdog.start(timeout=5.0)
        publish(watchdog)
    except Exception as exc:
        note(f"Party socket failed to start on port {port_i}: {exc}")
        return None
    try:
        from websocket.netinfo import local_ipv4

        advertise = local_ipv4()
    except Exception:
        advertise = "127.0.0.1"
    note(
        f"Party socket listening on {advertise}:{port_i} (bind 0.0.0.0). "
        "It stops when this bot stops."
    )
    return LeaderLink(
        watchdog=watchdog, owned=True, advertise=advertise, port=port_i
    )


def stop_leader_link(
    link: Optional[LeaderLink],
    *,
    log: Optional[LogFn] = None,
) -> None:
    note = log or (lambda _m: None)
    if link is None or not link.owned or link.watchdog is None:
        return
    try:
        from websocket.active import clear

        clear(link.watchdog)
        link.watchdog.stop(timeout=3.0)
        note("Party socket stopped")
    except Exception as exc:
        note(f"Party socket stop failed: {exc}")


def start_member_link(
    *,
    host: str,
    port: Any = 8765,
    log: Optional[LogFn] = None,
) -> Optional[MemberLink]:
    """Connect to the leader. Reconnects until the server is up."""
    note = log or (lambda _m: None)
    host = str(host or "").strip()
    if not host:
        note(
            "Party member WebSocket: set Leader IP on the Party tab "
            "(LAN address of the leader PC)."
        )
        return None
    port_i = _clamp_port(port)
    try:
        from websocket.client import PartyClient
        from websocket.member_status import MemberHeartbeat

        client = PartyClient(
            host=host,
            port=port_i,
            sender="member",
            reconnect=True,
        )
        client.connect(wait=False)
    except Exception as exc:
        note(f"Party member client failed to start: {exc}")
        return None
    note(
        f"Party member WebSocket → {host}:{port_i} "
        "(reconnects until the leader bot is Started). "
        "Follow uses in-game party memory, not this socket."
    )
    return MemberLink(
        client=client,
        heartbeat=MemberHeartbeat(client),
        host=host,
        port=port_i,
    )


def stop_member_link(
    link: Optional[MemberLink],
    *,
    log: Optional[LogFn] = None,
) -> None:
    note = log or (lambda _m: None)
    if link is None or link.client is None:
        return
    try:
        link.client.close(timeout=3.0)
        note("Party member client stopped")
    except Exception as exc:
        note(f"Party member client stop failed: {exc}")


__all__ = [
    "LeaderLink",
    "MemberLink",
    "start_leader_link",
    "stop_leader_link",
    "start_member_link",
    "stop_member_link",
]
