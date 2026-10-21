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
    built = _PARTY / "party_listen_build.dll"
    live = _PARTY / "party_listen.dll"
    if built.is_file() and (
        not live.is_file() or built.stat().st_mtime >= live.stat().st_mtime
    ):
        return built
    return live


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
    def __init__(
        self,
        dll_path: Optional[Path] = None,
        registry_path: Optional[Path] = None,
    ) -> None:
        dll = Path(dll_path or default_dll_path())
        registry = Path(registry_path or default_registry_path())
        self._calibrate = registry_path is None and registry == _MERGED
        # None until the first anchored read; then {"delta", "subs_ok", "tried"}.
        self.calibration: Optional[dict[str, Any]] = None
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

    def _read(self, registry: bytes) -> Optional[dict[str, Any]]:
        with _DLL_LOCK:
            n = int(self._snap(registry, self._buf, len(self._buf)))
            if n < 0:
                return None
            raw = bytes(self._buf.raw[:n])
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None

    def _run_calibration(self) -> Optional[dict[str, Any]]:
        """Find the vft delta where PartySubsystem resolves (works outside a party)."""
        probe = _PARTY / "registry" / "_calib_party_registry.txt"
        tried = 0
        for delta in CALIBRATION_DELTAS[1:]:
            tried += 1
            try:
                path = merged_registry_path(delta, out=probe)
            except OSError:
                break
            data = self._read(str(path).encode("utf-8"))
            if data is not None and data.get("subs_ok") is True:
                merged_registry_path(delta)
                self.calibration = {"delta": delta, "subs_ok": True, "tried": tried}
                return data
        self.calibration = {"delta": 0, "subs_ok": False, "tried": tried}
        return None

    def snapshot(self) -> Optional[dict[str, Any]]:
        """One party snapshot. None when LC or the driver is unavailable.

        ``subs_ok`` false means the party vfts are wrong for this build — the
        snapshot then says nothing about whether we are in a party.
        """
        if self._closed or self._snap is None:
            return None
        data = self._read(self._registry)
        if data is None:
            return None
        if self.calibration is None and "subs_ok" in data:
            if data.get("subs_ok") or not self._calibrate:
                self.calibration = {
                    "delta": 0, "subs_ok": bool(data.get("subs_ok")), "tried": 0,
                }
            else:
                found = self._run_calibration()
                if found is not None:
                    data = found
                # Reload the (possibly rewritten) merged registry in the DLL.
                again = self._read(self._registry)
                if again is not None:
                    data = again
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
