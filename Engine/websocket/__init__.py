"""Independent party WebSocket transport (1 server, N clients).

Decide and session do not import this package. ``BotController`` starts one
server when the profile party role is leader, and stops it when the worker
exits. Host and port come from the profile, not from YAML.

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
