"""In-process player monitor. One call reads LC memory and returns JSON.

The DLL is the same reader as realtime_monitor_full.exe --pipe, without the
console or the named pipe. It is not injected into LC.exe. Offsets come from
analysis/offsets.json on every snapshot.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"
_LOCK = threading.Lock()
_SHARED: Optional["RealtimeMonitorReader"] = None


def default_dll_path() -> Path:
    return _ANALYSIS / "realtime_monitor.dll"


def default_offsets_path() -> Path:
    return _ANALYSIS / "offsets.json"


class RealtimeMonitorReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        offsets_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        offsets = Path(offsets_path or default_offsets_path())
        if not dll.is_file():
            raise FileNotFoundError(f"realtime_monitor DLL is missing: {dll}")
        if not offsets.is_file():
            raise FileNotFoundError(f"offsets.json is missing: {offsets}")
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.realtime_monitor_snapshot
        self._snap.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
        ]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.realtime_monitor_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None
        self._offsets = str(offsets).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 20)
        self._closed = False

    def snapshot(self, fresh: bool = False) -> Optional[dict[str, Any]]:
        """One player snapshot. None when the game or driver is not available."""
        if self._closed:
            return None
        with _LOCK:
            n = int(self._snap(self._offsets, 1 if fresh else 0, self._buf, len(self._buf)))
        if n < 0:
            return None
        return json.loads(self._buf.raw[:n].decode("utf-8"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _LOCK:
            try:
                self._shutdown()
            except Exception:
                pass


def shared_monitor() -> RealtimeMonitorReader:
    """Process-wide reader. Probes and the bot share one DLL attach."""
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
