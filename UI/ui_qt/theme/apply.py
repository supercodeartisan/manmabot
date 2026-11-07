"""Apply classic Manmabot look to a QApplication / window."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QGroupBox, QHeaderView, QWidget

from ui_qt.theme import tokens as t
from ui_qt.theme.fonts import (
    body_font,
    classic_font_sizes,
    load_qt_fonts,
    resolve_family,
    resolve_section_family,
    section_font,
)
from ui_qt.theme.stylesheet import build_qss


def apply_classic_qt_theme(
    app: QApplication,
    language: str = "en",
    *widgets: QWidget,
    font_size: int = 8,
    section_size: int | None = None,
    restyle: bool = True,
) -> str:
    """Load fonts + QSS + palette. Returns the resolved body font family.

    ``restyle=False`` only swaps the already-loaded face. Reapplying the
    application stylesheet walks every widget and freezes the window.
    """
    load_qt_fonts(language)
    body_family = resolve_family(language)
    section_family = resolve_section_family(language)
    size = max(8, min(16, int(font_size)))
    sec_size = max(8, min(16, int(section_size if section_size is not None else size)))
    font = body_font(language, size)
    section = section_font(language, sec_size)
    app.setFont(font)
    if restyle:
        app.setStyleSheet(
            build_qss(
                body_family,
                size,
                section_family=section_family,
                section_size=sec_size,
            )
        )

    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(t.BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(t.SURFACE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(t.CHROME))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(t.TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(t.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(t.SURFACE))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(t.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(t.ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.TEXT_MUTED))
    app.setPalette(palette)
    for widget in widgets:
        widget.setFont(font)
        widget.setPalette(palette)
        # Body face on children first, then classic section face on headers.
        for child in widget.findChildren(QWidget):
            child.setFont(font)
        for header in widget.findChildren(QHeaderView):
            header.setFont(section)
        for group in widget.findChildren(QGroupBox):
            group.setFont(section)
    return body_family


def font_px_for_window(width: int, height: int) -> int:
    """Body size in points — same formula as classic ``_scale_font(FONT_BODY)``."""
    body, _section, _title = classic_font_sizes(width, height)
    return body


def font_roles_for_window(width: int, height: int) -> tuple[int, int, int]:
    """Body / section / title sizes for the given window (classic scale)."""
    return classic_font_sizes(width, height)


def mark_accent(button: QWidget) -> None:
    """Match classic ``Accent.TButton`` (soft blue, dark text — not solid fill)."""
    button.setObjectName("accent")
    button.setProperty("class", "accent")
    button.style().unpolish(button)
    button.style().polish(button)
