"""Load Engine/win32_prototypes.py when the bot dir is on sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parents[3]
_engine_s = str(_ENGINE)
if _engine_s not in sys.path:
    sys.path.insert(0, _engine_s)

from win32_prototypes import (  # noqa: E402
    bind_all,
    bind_crypt32,
    bind_gdi32,
    bind_kernel32,
    bind_shell32,
    bind_shcore,
    bind_user32,
)

__all__ = [
    "bind_all",
    "bind_crypt32",
    "bind_gdi32",
    "bind_kernel32",
    "bind_shell32",
    "bind_shcore",
    "bind_user32",
]
