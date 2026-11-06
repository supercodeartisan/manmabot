"""In-process print_state sweep. One call reads LC memory and returns JSON.

The DLL is the same reader ``fix/single-version`` uses: roster plus a fast
PRES_B poll, then ``iscr``. Settings come from ``settings_print_state.json``,
then ``entity_offsets.txt`` in the same folder. Solo and party ticks both
keep HP, MP, and level on this snapshot.
"""
from __future__ import annotations

import ctypes
import json
import threading
from pathlib import Path
from typing import Any, Optional

# One process-wide DLL. The bot worker and a field view must not enter
# print_state_snapshot / shutdown at the same time.
_DLL_LOCK = threading.Lock()

_ENTITIES = Path(__file__).resolve().parents[2] / "analysis" / "entities"


def default_dll_path() -> Path:
    """Newest print_state image. A locked live DLL keeps the previous build beside it."""
    candidates = [
        _ENTITIES / "print_state.new.dll",
        _ENTITIES / "print_state.iso.dll",
        _ENTITIES / "print_state.dll",
    ]
    found = [path for path in candidates if path.is_file()]
    if not found:
        return candidates[-1]
    return max(found, key=lambda path: path.stat().st_mtime)


def default_settings_path() -> Path:
    return _ENTITIES / "settings_print_state.json"


class PrintStateReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        settings = Path(settings_path or default_settings_path())
        if not dll.is_file():
            raise FileNotFoundError(f"print_state DLL is missing: {dll}")
        if not settings.is_file():
            raise FileNotFoundError(f"print_state settings are missing: {settings}")
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.print_state_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.print_state_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None
        self._cfg = str(settings).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 20)
        self._closed = False

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One snapshot (fast PRES_B poll; roster refreshes ~100ms). None if unavailable."""
        with _DLL_LOCK:
            if self._closed:
                return None
            n = int(self._snap(self._cfg, self._buf, len(self._buf)))
            if n < 0:
                return None
            raw = self._buf.raw[:n]
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            return None
        return data

    def close(self) -> None:
        with _DLL_LOCK:
            if self._closed:
                return
            self._closed = True
            try:
                self._shutdown()
            except Exception:
                pass


__all__ = ["PrintStateReader", "default_dll_path", "default_settings_path"]
