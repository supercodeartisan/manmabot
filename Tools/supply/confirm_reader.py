"""Read confirm/popup messages for supply qty prompts (UIdialogmon-style).

Uses ``Tools/supply/confirm_popup/confirm_listen.dll`` which walks UISubsystem
containers and reads CommonMessagePopup / ChatConfirmPanel text at
+CHATCONFIRM_MSG_OFF (same chain as UIdialogmon §8).

A visible popup whose message contains both ``Esc`` and ``Enter`` is treated
as the post-drag quantity-input notice.
"""
from __future__ import annotations

import ctypes
import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_POP = _HERE / "confirm_popup"
_REG_PATH = _POP / "confirm_registry.txt"


def _dll_path() -> Path:
    built = _POP / "confirm_listen_build.dll"
    live = _POP / "confirm_listen.dll"
    if built.is_file() and (
        not live.is_file() or built.stat().st_mtime >= live.stat().st_mtime
    ):
        return built
    return live


_DLL_PATH = _dll_path()

_LOCK = threading.Lock()
_LIB = None
_SNAP = None
_SHUT = None


def _load() -> bool:
    global _LIB, _SNAP, _SHUT
    if _SNAP is not None:
        return True
    if not _DLL_PATH.is_file():
        return False
    if not _REG_PATH.is_file():
        return False
    lib = ctypes.CDLL(str(_DLL_PATH))
    snap = lib.confirm_listen_snapshot
    snap.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    snap.restype = ctypes.c_int
    shut = lib.confirm_listen_shutdown
    shut.argtypes = []
    shut.restype = None
    _LIB = lib
    _SNAP = snap
    _SHUT = shut
    return True


def last_error() -> int:
    with _LOCK:
        if not _load() or _LIB is None:
            return -1
        fn = getattr(_LIB, "confirm_listen_last_error", None)
        if fn is None:
            return -1
        fn.restype = ctypes.c_int
        return int(fn())


def snapshot() -> Optional[dict[str, Any]]:
    """One-shot confirm JSON. None if DLL/driver unavailable."""
    with _LOCK:
        if not _load() or _SNAP is None:
            return None
        buf = ctypes.create_string_buffer(1 << 16)
        reg = str(_REG_PATH).encode("utf-8")
        n = int(_SNAP(reg, buf, len(buf)))
        if n < 0:
            return None
        raw = bytes(buf.raw[:n])
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def qty_prompt_open(snap: Optional[dict[str, Any]] = None) -> bool:
    view = snap if isinstance(snap, dict) else snapshot()
    if not isinstance(view, dict):
        return False
    if view.get("qty_prompt"):
        return True
    for row in view.get("confirms") or []:
        if isinstance(row, dict) and row.get("qty_prompt"):
            return True
    return False


def describe(snap: Optional[dict[str, Any]] = None) -> str:
    view = snap if isinstance(snap, dict) else snapshot()
    if not isinstance(view, dict):
        return f"confirm=unavailable err={last_error()}"
    rows = view.get("confirms") or []
    parts = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        msg = str(row.get("msg") or "")[:80]
        parts.append(f"{row.get('cls')} qty={row.get('qty_prompt')} \"{msg}\"")
    return (
        f"confirm n={view.get('n')} qty_prompt={view.get('qty_prompt')} "
        + ("; ".join(parts) if parts else "(none)")
    )


def wait_qty_prompt(
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.1,
) -> bool:
    """Poll until a qty-prompt popup is visible (Esc+Enter in message)."""
    deadline = time.time() + max(0.0, float(timeout_s))
    while True:
        if qty_prompt_open():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(max(0.02, float(poll_s)))


__all__ = [
    "snapshot",
    "last_error",
    "qty_prompt_open",
    "describe",
    "wait_qty_prompt",
]
