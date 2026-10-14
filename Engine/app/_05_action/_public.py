"""Action Module: converts decisions into game inputs.

Keep package import light: decide/shop paths need ``spell_box`` without pulling
OpenCV (``cursor_verify`` / ``cursor_match``). Heavy symbols load on demand.
"""

from __future__ import annotations

import importlib
from typing import Any

# This module is `_public`; sibling modules hang off the parent.
_PKG = __name__.rsplit(".", 1)[0]

from .result import ActionResult

__all__ = [
    "ActionExecutor",
    "ActionResult",
    "ELF_ATTACK_INTERVAL",
    "MAGE_CAST_INTERVAL",
    "humanize",
    "cursor_verify",
    "CursorCategory",
    "CursorMatch",
    "CursorMatcher",
    "get_cursor_matcher",
]


def __getattr__(name: str) -> Any:
    if name in ("ActionExecutor", "ELF_ATTACK_INTERVAL", "MAGE_CAST_INTERVAL"):
        controller = importlib.import_module(f"{_PKG}.controller")
        mapping = {
            "ActionExecutor": controller.ActionExecutor,
            "ELF_ATTACK_INTERVAL": controller.ELF_ATTACK_INTERVAL,
            "MAGE_CAST_INTERVAL": controller.MAGE_CAST_INTERVAL,
        }
        value = mapping[name]
        globals()[name] = value
        return value
    if name in ("humanize", "cursor_verify"):
        mod = importlib.import_module(f"{_PKG}.{name}")
        globals()[name] = mod
        return mod
    if name == "CursorCategory":
        from .cursor_catalog import CursorCategory

        globals()[name] = CursorCategory
        return CursorCategory
    if name in ("CursorMatch", "CursorMatcher", "get_cursor_matcher"):
        match_mod = importlib.import_module(f"{_PKG}.cursor_match")
        mapping = {
            "CursorMatch": match_mod.CursorMatch,
            "CursorMatcher": match_mod.CursorMatcher,
            "get_cursor_matcher": match_mod.get_cursor_matcher,
        }
        value = mapping[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
