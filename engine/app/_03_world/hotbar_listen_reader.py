"""In-process hotbar_listen. One call reads LC 24 hotbar slots as JSON.

The DLL is the same reader as hotbar_listen.exe. It is not injected into
LC.exe. Offsets come from analysis/Hotbar/skill_offsets.txt, then
analysis/inventories/inventory_offsets.txt for item names.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

_HOTBAR = Path(__file__).resolve().parents[2] / "analysis" / "Hotbar"
_LOCK = threading.Lock()
_SHARED: Optional["HotbarListenReader"] = None


def default_dll_path() -> Path:
    return _HOTBAR / "hotbar_listen.dll"


def default_offsets_path() -> Path:
    return _HOTBAR / "skill_offsets.txt"


class HotbarListenReader:
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
        self._buf = ctypes.create_string_buffer(1 << 16)
        if not dll.is_file():
            raise FileNotFoundError(f"hotbar_listen DLL is missing: {dll}")
        if not offsets.is_file():
            raise FileNotFoundError(f"hotbar offsets are missing: {offsets}")
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.hotbar_listen_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.hotbar_listen_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    def snapshot(self) -> Optional[dict[str, Any]]:
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
        if isinstance(data, dict) and isinstance(data.get("slots"), list):
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


def shared_hotbar() -> HotbarListenReader:
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = HotbarListenReader()
        return _SHARED


__all__ = [
    "HotbarListenReader",
    "shared_hotbar",
    "default_dll_path",
    "default_offsets_path",
]
