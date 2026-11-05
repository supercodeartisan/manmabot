"""In-process party reader. Leader stats come from PartySubsystem, not the entity sweep.

``snapshot()`` is one synchronous DLL read (fixed pointer chain, no BFS).
The payload always includes ``leader`` (object or null) and ``members``.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

_PARTY = Path(__file__).resolve().parents[2] / "analysis" / "party"
_DLL_LOCK = threading.Lock()


def default_dll_path() -> Path:
    built = _PARTY / "party_listen_build.dll"
    live = _PARTY / "party_listen.dll"
    if built.is_file() and (
        not live.is_file() or built.stat().st_mtime >= live.stat().st_mtime
    ):
        return built
    return live


def default_registry_path() -> Path:
    return _PARTY / "registry" / "LC930_REGISTRY.txt"


def leader_stats(snapshot: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Party leader block, or None when the snapshot has no matched leader."""
    if not isinstance(snapshot, dict):
        return None
    leader = snapshot.get("leader")
    if isinstance(leader, dict) and str(leader.get("name") or "").strip():
        return leader
    return None


class PartyListenReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        registry_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        registry = Path(registry_path or default_registry_path())
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._registry = str(registry).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 16)
        if not dll.is_file():
            return
        if not registry.is_file():
            return
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.party_listen_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.party_listen_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    @property
    def dll_loaded(self) -> bool:
        return self._snap is not None

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One party snapshot. None when LC or the driver is unavailable."""
        if self._closed or self._snap is None:
            return None
        with _DLL_LOCK:
            n = int(self._snap(self._registry, self._buf, len(self._buf)))
            if n < 0:
                return None
            raw = bytes(self._buf.raw[:n])
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._shutdown is not None:
            with _DLL_LOCK:
                try:
                    self._shutdown()
                except Exception:
                    pass


__all__ = [
    "PartyListenReader",
    "default_dll_path",
    "default_registry_path",
    "leader_stats",
]
