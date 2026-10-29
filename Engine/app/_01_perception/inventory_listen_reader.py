"""Bag contents from the inventory module."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader

_DLL = Path(__file__).resolve().parents[2] / "analysis" / "dll" / "inventory.dll"
_LOCK = threading.Lock()
_SHARED: Optional["InventoryListenReader"] = None


def default_dll_path() -> Path:
    return _DLL


def default_offsets_path() -> Path:
    return Path(__file__).resolve().parents[2] / "analysis" / "registry" / "LC930_REGISTRY.txt"


class InventoryListenReader(ModuleReader):
    module = "inventory"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import inventory

        data = inventory()
        return data if isinstance(data, dict) else None


def shared_inventory() -> InventoryListenReader:
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = InventoryListenReader()
        return _SHARED


class LiveInventorySweep:
    """Latest bag. The inventory module keeps the sample current."""

    def __init__(
        self,
        *,
        interval_s: float = 60.0,
        reader: Optional[InventoryListenReader] = None,
    ) -> None:
        del interval_s
        self.reader = reader or shared_inventory()
        self._closed = False

    def scanning(self) -> bool:
        return False

    def poll(self, *, force: bool = False, now: Optional[float] = None) -> Optional[dict[str, Any]]:
        del force, now
        if self._closed:
            return None
        return self.reader.snapshot()

    def close(self) -> None:
        self._closed = True


__all__ = [
    "InventoryListenReader",
    "LiveInventorySweep",
    "shared_inventory",
    "default_dll_path",
    "default_offsets_path",
]
