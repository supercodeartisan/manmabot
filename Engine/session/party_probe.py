"""Live party memory probe for the Party monitor UI (independent of bot Start)."""
from __future__ import annotations

import threading
import time
from typing import Any, Optional

_LOCK = threading.Lock()
_reader = None
_reader_tried = False
_dll_path_cached: Optional[str] = None
_dll_loaded_cached = False


def _ensure_reader():
    global _reader, _reader_tried, _dll_path_cached, _dll_loaded_cached
    with _LOCK:
        if _reader_tried:
            return _reader
        _reader_tried = True
        from app._01_perception.party_listen_reader import (
            PartyListenReader,
            default_dll_path,
        )

        path = default_dll_path()
        _dll_path_cached = str(path)
        if not path.is_file():
            _dll_loaded_cached = False
            _reader = None
            return None
        try:
            _reader = PartyListenReader()
            _dll_loaded_cached = bool(getattr(_reader, "dll_loaded", False))
            if not _dll_loaded_cached:
                _reader = None
        except Exception:
            _reader = None
            _dll_loaded_cached = False
        return _reader


def reset_party_probe() -> None:
    """Drop the cached reader (e.g. after building the DLL)."""
    global _reader, _reader_tried, _dll_loaded_cached
    with _LOCK:
        old = _reader
        _reader = None
        _reader_tried = False
        _dll_loaded_cached = False
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def probe_party_live() -> dict[str, Any]:
    """One live party_listen read for the UI.

    Always returns a dict with ``dll_path``, ``dll_loaded``, ``party``, ``error``.
    """
    from app._01_perception.party_listen_reader import default_dll_path

    path = default_dll_path()
    out: dict[str, Any] = {
        "dll_path": str(path),
        "dll_loaded": False,
        "party": None,
        "error": "",
        "probed_at": time.time(),
    }
    if not path.is_file():
        out["error"] = (
            f"DLL missing: {path.name}. "
            "Run Engine/analysis/party/build_party_listen_dll.bat "
            "(needs VS Build Tools / VCTools)."
        )
        return out

    reader = _ensure_reader()
    if reader is None or not getattr(reader, "dll_loaded", False):
        # File appeared after a failed first try — reset once.
        if path.is_file() and not _dll_loaded_cached:
            reset_party_probe()
            reader = _ensure_reader()
        if reader is None or not getattr(reader, "dll_loaded", False):
            out["error"] = f"DLL present but failed to load: {path}"
            return out

    out["dll_loaded"] = True
    try:
        snap = reader.snapshot()
    except Exception as exc:
        out["error"] = f"party snapshot failed: {exc}"
        return out
    if not isinstance(snap, dict):
        out["error"] = (
            "No party payload (LC not attached, signeddrv down, or not in party)."
        )
        return out
    out["party"] = snap
    if not bool(snap.get("in_party")):
        out["error"] = "DLL ok — not in a party (or 0 members)."
    return out


__all__ = ["probe_party_live", "reset_party_probe"]
