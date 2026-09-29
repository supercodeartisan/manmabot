"""Load the UI's bundled fonts without installing them on the computer."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


FONT_DIR = Path(__file__).resolve().parent
FONT_FILES = (
    "Manmabot-NotoSansKR-Regular.ttf",
    "Manmabot-NotoSansKR-Medium.ttf",
    "Manmabot-NotoSansKR-Bold.ttf",
    "Manmabot-NotoSansSC-Regular.ttf",
    "Manmabot-NotoSansSC-Medium.ttf",
    "Manmabot-NotoSansSC-Bold.ttf",
    "Manmabot-Inter-Regular.ttf",
    "Manmabot-Inter-Medium.ttf",
    "Manmabot-Inter-Bold.ttf",
)
_loaded: bool | None = None


def load_bundled_fonts() -> bool:
    """Make the packaged fonts available to this Windows process only."""
    global _loaded
    if _loaded is not None:
        return _loaded
    if sys.platform != "win32":
        return False
    add_font = ctypes.windll.gdi32.AddFontResourceExW
    found = True
    roots = (FONT_DIR, Path(sys.executable).resolve().parent / "manmabot_v1" / "ui" / "fonts")
    for name in FONT_FILES:
        path = next((root / name for root in roots if (root / name).is_file()), None)
        if path is None:
            found = False
            continue
        path_buffer = ctypes.create_unicode_buffer(str(path))
        if add_font(ctypes.byref(path_buffer), 0x10, 0) == 0:
            found = False
    _loaded = found
    return found
