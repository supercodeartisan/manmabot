"""In-process attacks_me sweep. Who is currently attacking MyPlayer.

Dedicated DLL (analysis/combat_attack/attacks_me.dll), same signeddrv stack as
print_state / realtime_monitor. Observation only — no combat policy.
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Any, Optional

_COMBAT = Path(__file__).resolve().parents[2] / "analysis" / "combat_attack"


def default_dll_path() -> Path:
    return _COMBAT / "attacks_me.dll"


def default_settings_path() -> Path:
    return _COMBAT / "settings_attacks_me.json"


class AttacksMeReader:
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        settings_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        settings = Path(settings_path or default_settings_path())
        if not dll.is_file():
            raise FileNotFoundError(f"attacks_me DLL is missing: {dll}")
        if not settings.is_file():
            raise FileNotFoundError(f"attacks_me settings are missing: {settings}")
        self._lib = ctypes.CDLL(str(dll))
        self._snap = self._lib.attacks_me_snapshot
        self._snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        self._snap.restype = ctypes.c_int
        self._shutdown = self._lib.attacks_me_shutdown
        self._shutdown.argtypes = []
        self._shutdown.restype = None
        self._cfg = str(settings).encode("utf-8")
        self._buf = ctypes.create_string_buffer(1 << 20)
        self._closed = False

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One AttackAction sweep. None if unavailable / LC not attached."""
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
