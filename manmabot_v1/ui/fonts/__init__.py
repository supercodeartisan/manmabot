"""Load the UI's bundled fonts without installing them on the computer."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path


FONT_DIR = Path(__file__).resolve().parent
FONT_FILES_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    "ko": (
        "Manmabot-NotoSansKR-Regular.ttf",
        "Manmabot-NotoSansKR-Medium.ttf",
        "Manmabot-NotoSansKR-Bold.ttf",
    ),
    "zh": (
        "Manmabot-NotoSansSC-Regular.ttf",
        "Manmabot-NotoSansSC-Medium.ttf",
        "Manmabot-NotoSansSC-Bold.ttf",
    ),
    "en": (
        "Manmabot-Inter-Regular.ttf",
        "Manmabot-Inter-Medium.ttf",
        "Manmabot-Inter-Bold.ttf",
    ),
}
# Full set kept for callers that still want every face (tests / tools).
FONT_FILES = tuple(
    name for files in FONT_FILES_BY_LANGUAGE.values() for name in files
)
_loaded_names: set[str] = set()


def font_files_for_language(language: str | None) -> tuple[str, ...]:
    """Return the three static faces needed for ``language`` (default English)."""
    key = language if language in FONT_FILES_BY_LANGUAGE else "en"
    return FONT_FILES_BY_LANGUAGE[key]


def load_bundled_fonts(language: str | None = None, *, all_languages: bool = False) -> bool:
    """Make packaged fonts available to this Windows process only.

    By default loads only the active UI language's family (3 files). Pass
    ``all_languages=True`` to register every bundled face.
    """
    if sys.platform != "win32":
        return False
    names = (
        FONT_FILES
        if all_languages
        else font_files_for_language(language)
    )
    pending = [name for name in names if name not in _loaded_names]
    if not pending:
        return True
    add_font = ctypes.windll.gdi32.AddFontResourceExW
    found = True
    roots = (FONT_DIR, Path(sys.executable).resolve().parent / "manmabot_v1" / "ui" / "fonts")
    for name in pending:
        path = next((root / name for root in roots if (root / name).is_file()), None)
        if path is None:
            found = False
            continue
        path_buffer = ctypes.create_unicode_buffer(str(path))
        if add_font(ctypes.byref(path_buffer), 0x10, 0) == 0:
            found = False
            continue
        _loaded_names.add(name)
    return found
