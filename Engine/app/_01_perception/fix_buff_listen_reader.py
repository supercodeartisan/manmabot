"""In-process buff_listen (E:\\Lineage\\extra ``lbuff.h`` map walk).

``snapshot()`` / ``snapshot_fresh()`` always do a synchronous DLL read (same as
Memory Watch). Optional background poller is off by default.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"
_LC930 = _ANALYSIS / "lc930"
_DLL_LOCK = threading.Lock()
_SHARED_LOCK = threading.Lock()
_SHARED: Optional["BuffListenReader"] = None

# Registry POLL_BUFF_INTERVAL_MS default.
_DEFAULT_POLL_S = 0.25


def default_dll_path() -> Path:
    # Prefer the freshly built image when the live DLL is still mapped and locked.
    built = _LC930 / "buff" / "buff_listen_build.dll"
    live = _LC930 / "buff" / "buff_listen.dll"
    if built.is_file() and (
        not live.is_file() or built.stat().st_mtime >= live.stat().st_mtime
    ):
        return built
    return live


def default_registry_path() -> Path:
    return _ANALYSIS / "registry" / "LC930_REGISTRY.txt"


class BuffListenReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        registry_path: Optional[Path] = None,
        *,
        poll_interval_s: float = _DEFAULT_POLL_S,
        start_thread: bool = False,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        registry = Path(registry_path or default_registry_path())
        self._closed = False
        self._lib = None
        self._snap = None
        self._shutdown = None
        self._registry = str(registry).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 20)
        self._poll_interval_s = max(0.05, float(poll_interval_s))
        self._latest: Optional[dict[str, Any]] = None
        self._data_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not dll.is_file():
            return
        if not registry.is_file():
            return
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.buff_listen_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.buff_listen_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None
        if start_thread:
            self._thread = threading.Thread(
                target=self._poll_loop,
                name="buff-listen",
                daemon=True,
            )
            self._thread.start()

    @property
    def dll_loaded(self) -> bool:
        return self._snap is not None

    def _snapshot_sync(self) -> Optional[dict[str, Any]]:
        if self._closed or self._snap is None:
            return None
        with _DLL_LOCK:
            n = int(self._snap(self._registry, self._buf, len(self._buf)))
            if n < 0:
                return None
            raw = bytes(self._buf.raw[:n])
        return json.loads(raw.decode("utf-8"))

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self._snapshot_sync()
                if isinstance(snap, dict):
                    with self._data_lock:
                        self._latest = snap
            except Exception:
                pass
            self._stop.wait(self._poll_interval_s)

    def snapshot(self) -> Optional[dict[str, Any]]:
        """Synchronous DLL read (same as tools / ``snapshot_fresh``)."""
        return self.snapshot_fresh()

    def snapshot_fresh(self) -> Optional[dict[str, Any]]:
        """Synchronous DLL read (Memory Watch / bot tick)."""
        snap = self._snapshot_sync()
        if isinstance(snap, dict):
            with self._data_lock:
                self._latest = snap
        return snap

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
        self._thread = None
        if self._shutdown is not None:
            with _DLL_LOCK:
                try:
                    self._shutdown()
                except Exception:
                    pass


def shared_buff() -> BuffListenReader:
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = BuffListenReader()
        return _SHARED


__all__ = ["BuffListenReader", "shared_buff", "default_dll_path", "default_registry_path"]
