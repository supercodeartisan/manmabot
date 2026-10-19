"""In-process storewin. One call reads the NPC warehouse window list as JSON.

DLL is storewin.dll (D:\\dist build, copied beside shop_listen.dll). Not injected
into LC.exe. Rows are the window slot order: idx, name, qty.
"""
from __future__ import annotations

import ctypes
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.Lock()
_SHARED: Optional["StorewinReader"] = None


def default_dll_path() -> Path:
    env = os.environ.get("STOREWIN_DLL", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.append(here.parents[2] / "analysis" / "NPC_conv" / "storewin.dll")
    candidates.append(Path(r"D:\dist\bin\storewin.dll"))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0] if env else candidates[-2]


class StorewinReader:
    """ctypes wrapper around storewin.dll."""

    def __init__(self, dll_path: Optional[Path] = None) -> None:
        dll = Path(dll_path or default_dll_path())
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._buf = ctypes.create_string_buffer(1 << 20)
        if not dll.is_file():
            return
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.storewin_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.storewin_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    @property
    def dll_loaded(self) -> bool:
        return self._snap is not None

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One warehouse-window scan. None when the DLL or driver is missing."""
        if self._closed or self._snap is None:
            return None
        with _LOCK:
            n = int(self._snap(None, self._buf, len(self._buf)))
        if n < 2:
            return None
        try:
            data = json.loads(self._buf.raw[:n].decode("utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

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


def shared_storewin() -> StorewinReader:
    global _SHARED
    if _SHARED is None:
        _SHARED = StorewinReader()
    return _SHARED


def capture_store() -> Optional[dict[str, Any]]:
    reader = shared_storewin()
    if not reader.dll_loaded:
        return None
    return reader.snapshot()


def parse_store_entries(snapshot: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize rows to idx, name, count. Empty when the window is not open."""
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("rows")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        try:
            idx = max(0, int(row.get("idx", i)))
        except (TypeError, ValueError):
            idx = i
        try:
            qty = max(0, int(row.get("qty") or row.get("count") or 0))
        except (TypeError, ValueError):
            qty = 0
        out.append(
            {
                "idx": idx,
                "name": str(row.get("name") or "").strip(),
                "count": qty,
            }
        )
    return out
