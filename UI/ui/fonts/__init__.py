"""Thin package shim — font loading in ``bundled_fonts`` (``.pyd`` in release)."""
from __future__ import annotations

from .bundled_fonts import (
    FONT_DIR,
    FONT_FILES,
    FONT_FILES_BY_LANGUAGE,
    font_files_for_language,
    load_bundled_fonts,
)

__all__ = [
    "FONT_DIR",
    "FONT_FILES",
    "FONT_FILES_BY_LANGUAGE",
    "font_files_for_language",
    "load_bundled_fonts",
]
