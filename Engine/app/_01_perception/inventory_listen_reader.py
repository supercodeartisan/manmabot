"""In-process inventory_listen. One call reads LC bag memory and returns JSON.

The DLL is the same reader as inventory_listen.exe, without a console or
named pipe. It is not injected into LC.exe. Offsets come from
analysis/inventories/offsets.json, then inventory_offsets.txt (TXT wins).
Names use the static FNV table first; a heap scan fills gaps when names are missing.
"""
from __future__ import annotations

import ctypes
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

_INVENTORIES = Path(__file__).resolve().parents[2] / "analysis" / "inventories"
_LOCK = threading.Lock()
_SHARED: Optional["InventoryListenReader"] = None


def default_dll_path() -> Path:
    return _INVENTORIES / "inventory_listen.dll"


def default_offsets_path() -> Path:
    return _INVENTORIES / "offsets.json"


class InventoryListenReader:
    """ctypes wrapper around inventory_listen.dll (print_state-style)."""

    def __init__(
        self,
        dll_path: Optional[Path] = None,
        offsets_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        offsets = Path(offsets_path or default_offsets_path())
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._offsets = str(offsets).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 21)  # 2 MiB bag JSON
        if not dll.is_file():
            raise FileNotFoundError(f"inventory_listen DLL is missing: {dll}")
        if not offsets.is_file():
            raise FileNotFoundError(f"inventory offsets are missing: {offsets}")
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.inventory_listen_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.inventory_listen_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    @property
    def dll_loaded(self) -> bool:
        return self._snap is not None

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One bag scan. None when the game/driver/DLL is unavailable."""
        if self._closed or self._snap is None:
            return None
        with _LOCK:
            n = int(self._snap(self._offsets, self._buf, len(self._buf)))
        if n < 2:
            return None
        try:
            data = json.loads(self._buf.raw[:n].decode("utf-8"))
        except Exception:
            return None
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
        return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._shutdown is None:
            return
        with _LOCK:
            try:
                self._shutdown()
            except Exception:
                pass


def shared_inventory() -> InventoryListenReader:
    """Process-wide reader. Bot ticks share one DLL attach."""
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = InventoryListenReader()
        return _SHARED


class LiveInventorySweep:
    """Latest bag snapshot. Scans run on a daemon thread (never block the bot tick).

    ``poll()`` always returns the last finished snapshot immediately. A new scan
    starts in the background when ``force=True``, or when ``interval_s`` has
    elapsed since the previous scan start (default 60s). Overlapping scans are
    not started while one is already running.
    """

    def __init__(
        self,
        *,
        interval_s: float = 60.0,
        reader: Optional[InventoryListenReader] = None,
    ) -> None:
        self.reader = reader or shared_inventory()
        self.interval_s = max(0.0, float(interval_s))
        self._lock = threading.Lock()
        # Negative infinity → first poll is always due (session force still wins early).
        self._last_poll = float("-inf")
        self._last_snap: Optional[dict[str, Any]] = None
        self._last_error: str = ""
        self._scan_thread: Optional[threading.Thread] = None
        self._closed = False

    def scanning(self) -> bool:
        thread = self._scan_thread
        return thread is not None and thread.is_alive()

    def poll(self, *, force: bool = False, now: Optional[float] = None) -> Optional[dict[str, Any]]:
        """Return the last bag. May start one background scan (force or interval)."""
        stamp = float(time.time() if now is None else now)
        with self._lock:
            snap = self._last_snap
            if self._closed:
                return snap
            busy = self._scan_thread is not None and self._scan_thread.is_alive()
            due = self.interval_s > 0.0 and (stamp - self._last_poll) >= self.interval_s
            start = (bool(force) or due) and not busy
            if start:
                self._last_poll = stamp
        if start:
            thread = threading.Thread(
                target=self._scan, name="inventory-listen", daemon=True
            )
            with self._lock:
                if self._closed:
                    return snap
                self._scan_thread = thread
            thread.start()
        return snap

    def _scan(self) -> None:
        try:
            snap = self.reader.snapshot()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            return
        with self._lock:
            if self._closed:
                return
            if isinstance(snap, dict) and isinstance(snap.get("items"), list):
                self._last_snap = snap
                self._last_error = ""

    def close(self) -> None:
        """Stop scheduling scans. Does not wait for an in-flight DLL read."""
        with self._lock:
            self._closed = True


__all__ = [
    "InventoryListenReader",
    "LiveInventorySweep",
    "shared_inventory",
    "default_dll_path",
    "default_offsets_path",
]
