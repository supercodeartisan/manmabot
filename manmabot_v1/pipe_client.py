"""Named-pipe client for realtime_monitor — no Manmabot package import.

Importing ``app._03_world.memory_client`` runs ``app._03_world.__init__``, which
pulls numpy and can fail on some PCs with WinError 206 (path too long under
``.venv\\...\\numpy.libs``). We load ``memory_client.py`` by file path instead.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional, Type

from manmabot_v1.paths import manmabot_root

_PIPE_CLIENT_MOD = None


def _load_memory_client_module():
    global _PIPE_CLIENT_MOD
    if _PIPE_CLIENT_MOD is not None:
        return _PIPE_CLIENT_MOD

    path = manmabot_root() / "app" / "_03_world" / "memory_client.py"
    if not path.is_file():
        raise FileNotFoundError(f"memory_client.py not found: {path}")

    # Unique name so we never collide with app._03_world.memory_client
    name = "manmabot_v1_memory_client_standalone"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _PIPE_CLIENT_MOD = mod
    return mod


def LineageMonitor(**kwargs: Any):
    """Construct the same class as Manmabot's LineageMonitor."""
    cls = _load_memory_client_module().LineageMonitor
    return cls(**kwargs)


def pipe_name() -> str:
    return str(getattr(_load_memory_client_module(), "PIPE_NAME", r"\\.\pipe\realtime_monitor"))


def format_memory_error(exc: BaseException) -> str:
    """Human-readable probe failure (esp. WinError 206 / numpy path issues)."""
    msg = str(exc)
    winerror = getattr(exc, "winerror", None)
    if winerror == 206 or "WinError 206" in msg or "filename or extension is too long" in msg.lower():
        return (
            "Python failed to load libraries (WinError 206 — path too long), "
            "often under .venv\\...\\numpy.libs. "
            "Fix: enable Windows long paths, or use a shorter install path "
            "(e.g. D:\\v0), then recreate the venv and pip install -r requirements.txt. "
            f"Detail: {msg}"
        )
    return msg
