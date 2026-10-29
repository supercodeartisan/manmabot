"""In-process party reader. Leader stats come from PartySubsystem, not the entity sweep.

``snapshot()`` is one synchronous DLL read (fixed pointer chain, no BFS).
The payload always includes ``leader`` (object or null) and ``members``.
"""
from __future__ import annotations

import ctypes
import json
import re
import threading
from pathlib import Path
from typing import Any, Optional

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"
_PARTY = _ANALYSIS / "party"
_LC930_REGISTRY = _ANALYSIS / "lc930" / "registry" / "LC930_REGISTRY.txt"
_PARTY_KEYS = _PARTY / "registry" / "PARTY_SEC17.txt"
# Generated: current anchors (lc930) + party keys. The DLL takes one file.
_MERGED = _PARTY / "registry" / "_merged_party_registry.txt"
_DLL_LOCK = threading.Lock()


def default_dll_path() -> Path:
    return _ANALYSIS / "dll" / "party.dll"


_VFT_KEYS = ("PARTY_VFT_SUBS", "PARTY_VFT_RC", "PARTY_VFT_RC_PLAYER")
# Tried (relative to PARTY_SEC17.txt) when PartySubsystem is not found. Deltas are
# the patch-to-patch shifts seen on neighbouring subsystems; the three party
# vfts sit together in .rdata and move by the same amount.
CALIBRATION_DELTAS = (
    0x0, -0xB5E0, -0xB2E8, -0xB4B0, -0xB438, -0xB3F0, -0xB318, -0xB008,
    0x290, -0x290, 0x2F8, -0x2F8, 0x5D8, -0x5D8,
)


def _party_keys_text(delta: int = 0) -> str:
    text = _PARTY_KEYS.read_text(encoding="utf-8")
    if not delta:
        return text
    for key in _VFT_KEYS:
        m = re.search(rf"^{key}=(0x[0-9A-Fa-f]+)", text, re.M)
        if m:
            val = int(m.group(1), 16) + delta
            text = text.replace(m.group(0), f"{key}=0x{val:X}")
    return text + f"\n# calibrated delta {delta:+#x} vs PARTY_SEC17.txt\n"


def merged_registry_path(delta: int = 0, *, out: Optional[Path] = None) -> Path:
    """Write lc930 registry + party keys (vfts shifted by ``delta``) and return it."""
    text = (
        _LC930_REGISTRY.read_text(encoding="utf-8")
        + "\n\n"
        + _party_keys_text(delta)
        + "\n"
    )
    path = Path(out or _MERGED)
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def default_registry_path() -> Path:
    """lc930 registry (anchors, same as every other reader) + ``PARTY_SEC17.txt``.

    Falls back to the old standalone party registry when either part is missing.
    """
    legacy = _PARTY / "registry" / "LC930_REGISTRY.txt"
    if not (_LC930_REGISTRY.is_file() and _PARTY_KEYS.is_file()):
        return legacy
    try:
        return merged_registry_path()
    except OSError:
        return legacy


def leader_stats(snapshot: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Party leader block, or None when the snapshot has no matched leader."""
    if not isinstance(snapshot, dict):
        return None
    leader = snapshot.get("leader")
    if isinstance(leader, dict) and str(leader.get("name") or "").strip():
        return leader
    return None


class PartyListenReader:
    """Party roster from the party module. Vfts come from the registry."""

    def __init__(
        self,
        dll_path: Optional[Path] = None,
        registry_path: Optional[Path] = None,
    ) -> None:
        del dll_path, registry_path
        self.calibration: Optional[dict[str, Any]] = None
        self._closed = False
        self._loaded = False
        try:
            from app._01_perception.lc_session import session

            session.ensure("party")
            self._loaded = True
        except Exception:
            self._loaded = False

    @property
    def dll_loaded(self) -> bool:
        return self._loaded and not self._closed

    def snapshot(self) -> Optional[dict[str, Any]]:
        if not self.dll_loaded:
            return None
        from app._01_perception.lc_view import party

        data = party()
        if isinstance(data, dict):
            self.calibration = {
                "delta": 0,
                "subs_ok": bool(data.get("subs_ok")),
                "tried": 0,
            }
        return data

    def close(self) -> None:
        self._closed = True


__all__ = [
    "PartyListenReader",
    "default_dll_path",
    "default_registry_path",
    "leader_stats",
]
