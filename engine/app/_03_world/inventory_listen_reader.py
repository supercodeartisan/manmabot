"""In-process inventory_listen. One call reads LC bag memory and returns JSON.

The DLL is the same reader as inventory_listen.exe, without a console or
named pipe. It is not injected into LC.exe. Offsets come from
analysis/inventories/offsets.json, then inventory_offsets.txt (TXT wins).
Names use the static FNV table first; a heap scan is only a fallback.
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


def default_inv_json_path() -> Path:
    return _INVENTORIES / "inv.json"


class InventoryListenReader:
    """ctypes wrapper around inventory_listen.dll (print_state-style)."""

    def __init__(
        self,
        dll_path: Optional[Path] = None,
        offsets_path: Optional[Path] = None,
        *,
        allow_file_fallback: bool = True,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        offsets = Path(offsets_path or default_offsets_path())
        self._inv_json = default_inv_json_path()
        self._allow_file = bool(allow_file_fallback)
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._offsets = str(offsets).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 21)  # 2 MiB bag JSON
        if not dll.is_file():
            if not self._allow_file:
                raise FileNotFoundError(f"inventory_listen DLL is missing: {dll}")
            return
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
        if self._closed:
            return None
        if self._snap is not None:
            with _LOCK:
                n = int(self._snap(self._offsets, self._buf, len(self._buf)))
            if n >= 2:
                try:
                    data = json.loads(self._buf.raw[:n].decode("utf-8"))
                except Exception:
                    return None
                if isinstance(data, dict) and isinstance(data.get("items"), list):
                    return data
                if isinstance(data, dict) and data.get("error"):
                    return None
            # n < 0 → LC/driver unavailable; fall through to optional file.
        if self._allow_file:
            return self._snapshot_file()
        return None

    def _snapshot_file(self) -> Optional[dict[str, Any]]:
        path = self._inv_json
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data.setdefault("cmd", "inventory")
            data.setdefault("source", "inv.json")
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
    """Keep the latest bag snapshot without blocking the bot tick.

    Bag reads are structure-chain (fast). Name keys still take a short
    bounded heap pass. Scans run on a daemon thread; ``poll()`` returns
    the last finished snapshot immediately.
    """

    def __init__(
        self,
        *,
        interval_s: float = 20.0,
        reader: Optional[InventoryListenReader] = None,
    ) -> None:
        self.reader = reader or shared_inventory()
        self.interval_s = max(2.0, float(interval_s))
        self._lock = threading.Lock()
        self._last_poll = 0.0
        self._last_snap: Optional[dict[str, Any]] = None
        self._last_error: str = ""
        self._scan_thread: Optional[threading.Thread] = None
        self._closed = False
        self._seed_from_file()

    def _seed_from_file(self) -> None:
        try:
            seed = self.reader._snapshot_file()
        except Exception:
            return
        if isinstance(seed, dict) and isinstance(seed.get("items"), list):
            self._last_snap = seed

    def scanning(self) -> bool:
        thread = self._scan_thread
        return thread is not None and thread.is_alive()

    def poll(self, *, force: bool = False, now: Optional[float] = None) -> Optional[dict[str, Any]]:
        stamp = time.time() if now is None else float(now)
        with self._lock:
            snap = self._last_snap
            if self._closed:
                return snap
            due = force or snap is None or (stamp - self._last_poll >= self.interval_s)
            busy = self._scan_thread is not None and self._scan_thread.is_alive()
            start = due and not busy
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
    "default_inv_json_path",
]
