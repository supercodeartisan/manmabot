"""In-process shop_listen. One call reads ShopSubsystem Buy/Sell lists as JSON.

DLL lives next to shop_listen.c under analysis/NPC_conv. Not injected into LC.exe.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

_NPC_CONV = Path(__file__).resolve().parents[2] / "analysis" / "NPC_conv"
_LOCK = threading.Lock()
_SHARED: Optional["ShopListenReader"] = None


def default_dll_path() -> Path:
    return _NPC_CONV / "shop_listen.dll"


class ShopListenReader:
    """ctypes wrapper around shop_listen.dll."""

    def __init__(self, dll_path: Optional[Path] = None) -> None:
        dll = Path(dll_path or default_dll_path())
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._buf = ctypes.create_string_buffer(1 << 20)  # 1 MiB
        if not dll.is_file():
            return
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.shop_listen_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.shop_listen_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    @property
    def dll_loaded(self) -> bool:
        return self._snap is not None

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One shop scan. None when game/driver/DLL unavailable."""
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
        if data.get("error") and not isinstance(data.get("sell"), list):
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


def shared_shop() -> ShopListenReader:
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = ShopListenReader()
        return _SHARED


def parse_sell_entries(snapshot: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize sell rows: idx, id, tmpl, count, unit, name."""
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("sell")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("idx", i))
        except (TypeError, ValueError):
            idx = i
        try:
            item_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            item_id = 0
        try:
            tmpl = int(row.get("tmpl") or 0)
        except (TypeError, ValueError):
            tmpl = 0
        try:
            count = max(0, int(row.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        try:
            unit = int(row.get("unit") or 0)
        except (TypeError, ValueError):
            unit = 0
        name = str(row.get("name") or "").strip()
        out.append(
            {
                "idx": idx,
                "id": item_id,
                "tmpl": tmpl,
                "count": count,
                "unit": unit,
                "name": name,
            }
        )
    return out


__all__ = [
    "ShopListenReader",
    "shared_shop",
    "default_dll_path",
    "parse_sell_entries",
]
