"""One-shot party WebSocket reachability check (UI Test connection).

Does not start the member bot and does not keep a client thread. Leader must
already be listening (Party leader + Start on the leader PC).
"""
from __future__ import annotations

import asyncio
import socket
from typing import Optional


def _tcp_check(host: str, port: int, *, timeout: float) -> None:
    with socket.create_connection((host, int(port)), timeout=max(0.2, float(timeout))):
        pass


async def _ws_handshake(host: str, port: int, *, timeout: float) -> None:
    import websockets

    uri = f"ws://{host}:{int(port)}/"
    async with websockets.connect(
        uri,
        open_timeout=max(0.5, float(timeout)),
        close_timeout=1.0,
        ping_interval=None,
    ):
        # Connected — party server accepted the WebSocket upgrade.
        return


def probe_party_leader(
    host: str,
    port: int = 8765,
    *,
    timeout: float = 3.0,
) -> str:
    """Return the URI on success; raise ``OSError`` / ``RuntimeError`` on failure.

    Safe to call from a worker thread before the member bot is Started.
    """
    host = str(host or "").strip()
    if not host:
        raise ValueError("leader host is empty")
    port = int(port)
    timeout = max(0.5, float(timeout))
    uri = f"ws://{host}:{port}/"
    try:
        _tcp_check(host, port, timeout=min(2.0, timeout))
    except OSError as exc:
        raise OSError(
            f"nothing listening at {uri} ({exc}). "
            "On the leader PC: Enable party, Party leader, then Start."
        ) from exc
    try:
        import websockets  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            f"TCP open at {uri}, but the websockets package is missing: {exc}"
        ) from exc
    try:
        asyncio.run(_ws_handshake(host, port, timeout=timeout))
    except Exception as exc:
        raise RuntimeError(
            f"TCP open at {uri}, but WebSocket handshake failed: {exc}. "
            "Confirm the leader bot is Started with Party enabled as leader."
        ) from exc
    return uri


__all__ = ["probe_party_leader"]
