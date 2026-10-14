"""Compatibility shim: former ``debug_tools`` package name.

New code should import from ``shopping``, ``hotbar``, ``dungeon``, or ``common``.
"""
from __future__ import annotations

from common import OUTPUT_DIR, PROJECT_ROOT, TOOLS_ROOT

__all__ = ["OUTPUT_DIR", "PROJECT_ROOT", "TOOLS_ROOT"]
