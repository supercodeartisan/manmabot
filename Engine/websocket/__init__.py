"""Independent party WebSocket transport (1 server, N clients).

Not wired into decide/session. No YAML settings — pass host/port in code.

Stability:
- server ping/pong + in-thread auto-rebind
- :class:`PartyServerWatchdog` outer thread restarts a dead server
- client auto-reconnect

Status: ``server.status()`` / ``watchdog.status()`` / logger ``websocket.*``.
"""
from .client import PartyClient
from .protocol import MessageBody, PartyMessage, parse_frame
from .server import PartyServer
from .watchdog import PartyServerWatchdog

__all__ = [
    "MessageBody",
    "PartyClient",
    "PartyMessage",
    "PartyServer",
    "PartyServerWatchdog",
    "parse_frame",
]
