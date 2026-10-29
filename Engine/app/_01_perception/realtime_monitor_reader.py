"""Player snapshot from the charread and map modules."""
from __future__ import annotations

import threading
from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader

_LOCK = threading.Lock()
_SHARED: Optional["RealtimeMonitorReader"] = None


class RealtimeMonitorReader(ModuleReader):
    """Starts charread. Map is pulled with the same snapshot."""

    module = "charread"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import player_snapshot

        data = player_snapshot()
        return data if isinstance(data, dict) else None


def shared_monitor() -> RealtimeMonitorReader:
    """Process-wide reader. Probes and the bot share one attach."""
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = RealtimeMonitorReader()
        return _SHARED


def shutdown_shared_monitor() -> None:
    global _SHARED
    with _LOCK:
        reader = _SHARED
        _SHARED = None
    if reader is not None:
        reader.close()


__all__ = ["RealtimeMonitorReader", "shared_monitor", "shutdown_shared_monitor"]
