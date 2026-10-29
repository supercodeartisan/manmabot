"""Hotbar slots from the hotbar module."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader

_DLL = Path(__file__).resolve().parents[2] / "analysis" / "dll" / "hotbar.dll"
_LOCK = threading.Lock()
_SHARED: Optional["HotbarListenReader"] = None


def default_dll_path() -> Path:
    return _DLL


def default_offsets_path() -> Path:
    return Path(__file__).resolve().parents[2] / "analysis" / "registry" / "LC930_REGISTRY.txt"


class HotbarListenReader(ModuleReader):
    module = "hotbar"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import hotbar

        data = hotbar()
        return data if isinstance(data, dict) else None


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
