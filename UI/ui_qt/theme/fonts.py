"""Load Manmabot bundled faces into Qt (same files / names as classic ttk)."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase

from ui.fonts import FONT_DIR, font_files_for_language, load_bundled_fonts

# Exact classic ``design_system`` family names.
_BODY_FAMILY = {
    "ko": "Manmabot Noto KR Medium",
    "zh": "Manmabot Noto SC Medium",
    "en": "Manmabot Inter Medium",
}
_SECTION_FAMILY = {
    "ko": "Manmabot Noto KR",
    "zh": "Manmabot Noto SC",
    "en": "Manmabot Inter",
}
_FALLBACK_BODY = {
    "ko": ("Manmabot Noto KR", "Noto Sans KR"),
    "zh": ("Manmabot Noto SC", "Noto Sans SC"),
    "en": ("Manmabot Inter", "Inter"),
}
_FALLBACK_SECTION = {
    "ko": ("Noto Sans KR",),
    "zh": ("Noto Sans SC",),
    "en": ("Inter",),
}

_loaded_ids: list[int] = []
_resolved_body: dict[str, str] = {}
_resolved_section: dict[str, str] = {}


def _lang_key(language: str) -> str:
    return language if language in _BODY_FAMILY else "en"


def _pick_family(preferred: str, fallbacks: tuple[str, ...], *, avoid_medium: bool = False) -> str:
    available = set(QFontDatabase.families())
    if preferred in available:
        return preferred
    for candidate in fallbacks:
        if candidate in available:
            return candidate
        for family in available:
            if candidate.lower() not in family.lower():
                continue
            if avoid_medium and " Medium" in family:
                continue
            return family
    return preferred


def resolve_family(language: str) -> str:
    """Classic ``FONT_BODY`` Medium family name."""
    key = _lang_key(language)
    if key in _resolved_body:
        return _resolved_body[key]
    preferred = _BODY_FAMILY[key]
    family = _pick_family(preferred, _FALLBACK_BODY[key], avoid_medium=False)
    _resolved_body[key] = family
    return family


def resolve_section_family(language: str) -> str:
    """Classic ``FONT_SECTION`` / ``FONT_TITLE`` Regular family name (not Medium)."""
    key = _lang_key(language)
    if key in _resolved_section:
        return _resolved_section[key]
    preferred = _SECTION_FAMILY[key]
    family = _pick_family(preferred, _FALLBACK_SECTION[key], avoid_medium=True)
    _resolved_section[key] = family
    return family


def load_qt_fonts(language: str) -> str:
    """Register bundled TTFs with Qt + GDI; return the classic Medium body family."""
    key = _lang_key(language)
    _resolved_body.pop(key, None)
    _resolved_section.pop(key, None)
    try:
        load_bundled_fonts(language)
    except Exception:
        pass
    preferred_body = _BODY_FAMILY[key]
    preferred_section = _SECTION_FAMILY[key]
    for name in font_files_for_language(language):
        path = FONT_DIR / name
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        _loaded_ids.append(font_id)
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family == preferred_body or " Medium" in family:
                if key not in _resolved_body or family == preferred_body:
                    _resolved_body[key] = preferred_body if preferred_body in QFontDatabase.families() else family
            elif family == preferred_section or (
                preferred_section in family and " Medium" not in family
            ):
                if key not in _resolved_section or family == preferred_section:
                    _resolved_section[key] = (
                        preferred_section
                        if preferred_section in QFontDatabase.families()
                        else family
                    )
            elif key not in _resolved_body:
                _resolved_body[key] = family
    if preferred_body in QFontDatabase.families():
        _resolved_body[key] = preferred_body
    if preferred_section in QFontDatabase.families():
        _resolved_section[key] = preferred_section
    return resolve_family(language)


def _base_font(family: str, point_size: int, *, bold: bool = False) -> QFont:
    """Build a QFont with clean CJK/Latin rasterization (classic Tk parity look).

    Noto KR/SC at small UI sizes looks muddy under subpixel ClearType + hinting —
    that is what makes jamo like ㅈ in \"작\" / \"시작\" look untidy. Prefer
    grayscale AA, no hinting, and no font merging (no fallback glyphs).
    """
    font = QFont(family)
    # Integer pixel size tracks classic Win32/Tk glyph boxes more closely than
    # fractional point→pixel conversion (8pt → 10.67px), which softens stems.
    px = max(10, min(24, int(round(float(point_size) * 96.0 / 72.0))))
    font.setPixelSize(px)
    if bold:
        font.setWeight(QFont.Weight.Bold)
        font.setBold(True)
    else:
        # Medium is its own family (prepare_fonts.py); do not set StyleName —
        # forcing \"Regular\" can make DirectWrite pick a poorer face match.
        font.setWeight(QFont.Weight.Normal)
        font.setBold(False)
    strategy = (
        QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoFontMerging
    )
    no_sub = getattr(QFont.StyleStrategy, "NoSubpixelAntialias", None)
    if no_sub is not None:
        strategy |= no_sub
    font.setStyleStrategy(strategy)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setKerning(True)
    return font


def body_font(language: str, point_size: int = 8) -> QFont:
    """Match classic ``FONT_BODY``: Medium *family*, Regular style, scaled points."""
    return _base_font(resolve_family(language), point_size, bold=False)


def section_font(language: str, point_size: int = 8) -> QFont:
    """Match classic ``FONT_SECTION``: Regular family + Bold."""
    return _base_font(resolve_section_family(language), point_size, bold=True)


def title_font(language: str, point_size: int = 10) -> QFont:
    """Match classic ``FONT_TITLE``: Regular family + Bold, larger points."""
    return _base_font(resolve_section_family(language), point_size, bold=True)


def classic_font_sizes(width: int, height: int) -> tuple[int, int, int]:
    """Body / section / title point sizes — same scale as classic ``_scale_font``."""
    from ui.scale import MIN_FONT_SIZE, compute_ui_scale

    scale = compute_ui_scale(width, height)
    body = max(MIN_FONT_SIZE, min(16, int(round(11.0 * scale))))
    section = max(MIN_FONT_SIZE, min(16, int(round(12.0 * scale))))
    title = max(MIN_FONT_SIZE, min(18, int(round(15.0 * scale))))
    return body, section, title
