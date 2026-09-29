"""In-process print_state sweep. One call reads LC memory and returns JSON.

The DLL keeps a roster across calls (slow grid sweep ~1s, fast PRES_B poll
every snapshot) and adds ``iscr`` (A→B interpolated screen). ``entities[]``
and ``screen`` stay the same. Offsets come from settings_print_state.json,
then entity_offsets.txt in the same folder (TXT wins).
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any, Optional

_ENTITIES = Path(__file__).resolve().parents[2] / "analysis" / "entities"


def default_dll_path() -> Path:
    return _ENTITIES / "print_state.dll"


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
        """One snapshot (fast PRES_B poll; roster refreshes ~1s). None if unavailable."""
        if self._closed:
            return None
        n = int(self._snap(self._cfg, self._buf, len(self._buf)))
        if n < 0:
            return None
        return json.loads(self._buf.raw[:n].decode("utf-8"))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._shutdown()
        except Exception:
            pass
