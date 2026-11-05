"""The one party server this process is allowed to listen with.

The leader bot publishes its server here. The test window uses that same
server instead of opening a second socket on the same port.
"""
from __future__ import annotations

import threading
from typing import Optional

from .watchdog import PartyServerWatchdog

_lock = threading.Lock()
_current: Optional[PartyServerWatchdog] = None


def publish(watchdog: PartyServerWatchdog) -> None:
    global _current
    with _lock:
        _current = watchdog


def clear(watchdog: Optional[PartyServerWatchdog] = None) -> None:
    """Drop the published server. A different instance is left in place."""
    global _current
    with _lock:
        if watchdog is None or _current is watchdog:
            _current = None


def current() -> Optional[PartyServerWatchdog]:
    with _lock:
        return _current


__all__ = ["clear", "current", "publish"]
