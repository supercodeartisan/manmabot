"""Open UI windows from the uidialogmon module."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader

_DLL = Path(__file__).resolve().parents[2] / "analysis" / "dll" / "uidialogmon.dll"
_LOCK = threading.Lock()
_SHARED: Optional["UiDialogListenReader"] = None


def default_dll_path() -> Path:
    return _DLL


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "analysis" / "registry" / "LC930_REGISTRY.txt"


class UiDialogListenReader(ModuleReader):
    module = "uidialogmon"

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        super().__init__()

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import uidialog

        data = uidialog()
        return data if isinstance(data, dict) else None


def shared_uidialog() -> UiDialogListenReader:
    global _SHARED
    with _LOCK:
        if _SHARED is None or _SHARED._closed:
            _SHARED = UiDialogListenReader()
        return _SHARED


__all__ = [
    "UiDialogListenReader",
    "shared_uidialog",
    "default_dll_path",
    "default_registry_path",
]
