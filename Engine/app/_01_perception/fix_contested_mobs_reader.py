"""In-process contested_mobs sweep. Mobs attacked by other visible players.

Dedicated DLL (analysis/dll/contested_mobs.dll). If the other user
is not in the entity sweep, the mob is absent (= free).
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any, Optional

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"


def default_dll_path() -> Path:
    return _ANALYSIS / "dll" / "contested_mobs.dll"


def default_settings_path() -> Path:
    return _ANALYSIS / "registry" / "settings_contested_mobs.json"


class ContestedMobsReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        settings = Path(settings_path or default_settings_path())
        if not dll.is_file():
            raise FileNotFoundError(f"contested_mobs DLL is missing: {dll}")
        if not settings.is_file():
            raise FileNotFoundError(
                f"contested_mobs settings are missing: {settings}"
            )
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.contested_mobs_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.contested_mobs_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None
        self._cfg = str(settings).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 20)
        self._closed = False

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One contested-mob sweep. None if unavailable / LC not attached."""
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
