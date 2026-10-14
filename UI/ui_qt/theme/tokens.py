"""Color and geometry tokens — mirrored from ``ui.design_system``."""

from __future__ import annotations

BG = "#f4f6f8"
SURFACE = "#ffffff"
CHROME = "#f7f9fb"
CONTROL = "#f4f7fb"
BORDER = "#d5dbe3"
BORDER_STRONG = "#b4bcc6"
TEXT = "#1f2328"
TEXT_MUTED = "#6b7280"
ACCENT = "#3a82f6"
ACCENT_HOVER = "#2f6fdb"
ACCENT_SOFT = "#e8f1fe"
ACCENT_PRESS = "#d3e4fc"
ACCENT_TEXT = "#17345c"
TABLE_HEADER = "#e7eef8"
BUTTON_EDGE = "#a3b8cc"
SELECTED = ACCENT
PAGE = "#f4f8fc"
DISABLED_FG = "#a0a6ad"
DISABLED_BG = "#f3f4f6"
SCROLL_BG = "#d5dce6"
SCROLL_TROUGH = "#f3f5f8"

# Schedule window was designed at ~1760×1000. Default size is 1187×806.
DESIGN_WIDTH = 1760
DESIGN_HEIGHT = 1000
DEFAULT_WIDTH = 1187
DEFAULT_HEIGHT = 806
MIN_WIDTH = 800
MIN_HEIGHT = 600

LAMP = {
    "gray": "#6b7280",
    "green": "#22c55e",
    "yellow": "#eab308",
    "red": "#ef4444",
}

# Status-strip chip colors (schedule_ui._STRIP_* parity).
STRIP = {
    "off": ("#e6e9ee", "#5c6570"),
    "on": ("#128a43", "#ffffff"),
    "hold": ("#f4e4c4", "#8a5a00"),
}
