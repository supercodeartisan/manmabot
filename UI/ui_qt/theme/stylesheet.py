"""Qt Style Sheet mirroring ``ui.design_system.apply_classic_style``."""

from __future__ import annotations

from ui_qt.theme import tokens as t
from ui_qt.theme.indicators import indicator_dir, qss_url


def build_qss(
    font_family: str,
    font_size: int = 8,
    *,
    section_family: str | None = None,
    section_size: int | None = None,
) -> str:
    """Return application-wide QSS. ``font_size`` is classic Tk body points."""
    family = font_family.replace('"', "")
    size = max(8, min(16, int(font_size)))
    sec_family = (section_family or font_family).replace('"', "")
    sec_size = max(8, min(16, int(section_size if section_size is not None else size)))
    # Integer px keeps Korean jamo (ㅈ in 작/시작) sharp — same as body_font().
    size_px = max(10, min(24, int(round(size * 96.0 / 72.0))))
    sec_px = max(10, min(24, int(round(sec_size * 96.0 / 72.0))))
    # Combo dropdown + StepSpinBox button column width.
    step_w = max(16, min(22, round(size * 1.85)))
    arrow_px = max(8, min(12, round(size * 1.05)))
    pad_x = max(4, round(size * 0.5))
    pad_y = max(2, round(size * 0.3))
    field_min_h = max(22, round(size * 2.6))
    icons = indicator_dir()
    cb_off = qss_url(icons / "cb_off.png")
    cb_on = qss_url(icons / "cb_on.png")
    cb_off_dis = qss_url(icons / "cb_off_dis.png")
    cb_on_dis = qss_url(icons / "cb_on_dis.png")
    rb_off = qss_url(icons / "rb_off.png")
    rb_on = qss_url(icons / "rb_on.png")
    rb_off_dis = qss_url(icons / "rb_off_dis.png")
    rb_on_dis = qss_url(icons / "rb_on_dis.png")
    combo_down = qss_url(icons / "combo_down.png")
    combo_down_hov = qss_url(icons / "combo_down_hov.png")
    combo_down_dis = qss_url(icons / "combo_down_dis.png")
    return f"""
* {{
    font-family: "{family}";
    font-size: {size_px}px;
    color: {t.TEXT};
}}

QMainWindow, QDialog, QWidget {{
    background: {t.BG};
}}

QLabel {{
    background: transparent;
    color: {t.TEXT};
}}

QLabel#muted, QLabel[role="muted"] {{
    color: {t.TEXT_MUTED};
}}

QFrame#chrome {{
    background: {t.CHROME};
    border: 1px solid {t.BORDER};
}}

QFrame#statusStrip {{
    background: {t.BORDER};
    border: none;
}}

QLabel#statusChip {{
    background: {t.CONTROL};
    color: {t.TEXT_MUTED};
    padding: 3px 10px;
    border: none;
}}

QStatusBar {{
    background: {t.CHROME};
    color: {t.TEXT_MUTED};
    border-top: 1px solid {t.BORDER};
}}

QPushButton {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BUTTON_EDGE};
    border-radius: 6px;
    padding: 3px 10px;
    min-height: 22px;
    font-family: "{family}";
    font-size: {size_px}px;
}}
QPushButton:hover {{
    background: #f5f9fd;
    border-color: #8eabc4;
}}
QPushButton:pressed {{
    background: #e3edf8;
    border-color: #7f9db8;
}}
QPushButton:disabled {{
    background: #f6f7f8;
    color: {t.DISABLED_FG};
    border-color: #d8dee6;
}}
QPushButton#cellButton {{
    border: 1px solid {t.BORDER};
    border-radius: 4px;
    padding: 1px 6px;
    min-height: 0px;
}}
QPushButton#cellButton:hover {{
    background: #f5f9fd;
    border-color: {t.BORDER};
}}
QPushButton#cellButton:pressed {{
    background: #e3edf8;
    border-color: {t.BORDER};
}}

QPushButton#accent, QPushButton[class="accent"] {{
    background: {t.ACCENT_SOFT};
    color: {t.ACCENT_TEXT};
    border: 1px solid {t.BUTTON_EDGE};
}}
QPushButton#accent:hover, QPushButton[class="accent"]:hover {{
    background: #eef5ff;
    border-color: #8eabc4;
}}
QPushButton#accent:pressed, QPushButton[class="accent"]:pressed {{
    background: {t.ACCENT_PRESS};
    border-color: #7f9db8;
}}

QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 4px;
    padding: {pad_y}px {pad_x}px;
    selection-background-color: {t.ACCENT_SOFT};
    selection-color: {t.TEXT};
    font-family: "{family}";
    font-size: {size_px}px;
    min-height: {field_min_h}px;
}}
QSpinBox, QDoubleSpinBox {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 5px;
    padding: {pad_y}px {pad_x}px;
    selection-background-color: {t.ACCENT_SOFT};
    selection-color: {t.TEXT};
    font-family: "{family}";
    font-size: {size_px}px;
    min-height: {field_min_h}px;
}}
/* StepSpinBox: one input frame; ▲/▼ inset like QComboBox::drop-down. */
QWidget#stepSpin {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 5px;
}}
QWidget#stepSpin[spinFocused="true"] {{
    border: 1px solid {t.ACCENT};
}}
QWidget#stepSpin:disabled {{
    background: {t.DISABLED_BG};
}}
QSpinBox#stepSpinField {{
    background: transparent;
    color: {t.TEXT};
    border: none;
    border-radius: 0;
    padding: {pad_y}px {pad_x}px;
    min-height: 0px;
}}
QSpinBox#stepSpinField:focus {{
    border: none;
    background: transparent;
}}
QSpinBox#stepSpinField:disabled {{
    background: transparent;
    color: {t.TEXT_MUTED};
}}
QWidget#stepSpinBtns {{
    background: {t.CONTROL};
    border: 1px solid {t.BORDER};
    border-radius: 4px;
    max-width: 20px;
    min-width: 16px;
    padding: 0px;
    margin: 0px;
}}
QPushButton#stepSpinUp, QPushButton#stepSpinDown {{
    background: {t.CONTROL};
    border: none;
    border-radius: 0;
    color: #3f4a57;
    font-size: {max(8, size_px - 2)}px;
    padding: 0px;
    margin: 0px;
    min-width: 0px;
    min-height: 8px;
    text-align: center;
}}
QPushButton#stepSpinUp {{
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
}}
QPushButton#stepSpinDown {{
    border-top: 1px solid {t.BORDER};
    border-bottom-left-radius: 3px;
    border-bottom-right-radius: 3px;
}}
QPushButton#stepSpinUp:hover, QPushButton#stepSpinDown:hover {{
    background: #eef5ff;
    color: {t.ACCENT};
}}
QPushButton#stepSpinDown:hover {{
    border-top: 1px solid {t.BORDER};
}}
QPushButton#stepSpinUp:pressed, QPushButton#stepSpinDown:pressed {{
    background: {t.ACCENT_PRESS};
    color: {t.ACCENT_TEXT};
}}
QPushButton#stepSpinUp:disabled, QPushButton#stepSpinDown:disabled {{
    color: {t.DISABLED_FG};
    background: {t.DISABLED_BG};
}}
QWidget#timeField {{
    background: transparent;
}}
QWidget#cellHost {{
    background: transparent;
}}
QLineEdit:focus, QTextEdit:focus {{
    border: 1px solid {t.ACCENT};
    background: {t.SURFACE};
}}
/* Native spins (if any): do not paint a focus ring that spills onto neighbors. */
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {t.ACCENT};
    background: {t.SURFACE};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {t.DISABLED_BG};
    color: {t.TEXT_MUTED};
}}
QDialog QLineEdit, QDialog QSpinBox, QDialog QDoubleSpinBox, QDialog QComboBox, QDialog QTextEdit {{
    background: {t.SURFACE};
}}

QComboBox {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-radius: 5px;
    /* Room for a separate bordered drop button on the right. */
    padding: {pad_y}px {step_w + 6}px {pad_y}px {pad_x}px;
    min-height: {field_min_h}px;
    font-family: "{family}";
    font-size: {size_px}px;
}}
QComboBox:hover, QComboBox:focus {{
    border: 1px solid {t.ACCENT};
    background: {t.SURFACE};
}}
QComboBox::drop-down {{
    subcontrol-origin: border;
    subcontrol-position: center right;
    width: {step_w}px;
    /* Same bordered chrome as StepSpinBox ▲/▼ stack. */
    border: 1px solid {t.BORDER};
    border-radius: 4px;
    background: {t.CONTROL};
    margin: 2px;
}}
QComboBox::drop-down:hover {{
    background: {t.ACCENT_SOFT};
    border: 1px solid {t.BORDER};
}}
QComboBox::drop-down:pressed {{
    background: {t.ACCENT_PRESS};
    border: 1px solid {t.BORDER};
}}
QComboBox::down-arrow {{
    image: url("{combo_down}");
    width: {arrow_px}px;
    height: {arrow_px}px;
}}
QComboBox::down-arrow:on, QComboBox::down-arrow:hover {{
    image: url("{combo_down_hov}");
}}
QComboBox::down-arrow:disabled {{
    image: url("{combo_down_dis}");
}}
QComboBox:disabled {{
    background: {t.DISABLED_BG};
    color: {t.TEXT_MUTED};
}}
QComboBox::drop-down:disabled {{
    background: {t.DISABLED_BG};
    border: 1px solid {t.BORDER};
}}
QComboBox QAbstractItemView {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    selection-background-color: {t.ACCENT};
    selection-color: #ffffff;
}}

QCheckBox, QRadioButton {{
    background: transparent;
    color: {t.TEXT};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: none;
    background: transparent;
}}
QCheckBox::indicator:unchecked {{
    image: url("{cb_off}");
}}
QCheckBox::indicator:checked {{
    image: url("{cb_on}");
}}
QCheckBox::indicator:unchecked:disabled {{
    image: url("{cb_off_dis}");
}}
QCheckBox::indicator:checked:disabled {{
    image: url("{cb_on_dis}");
}}
QRadioButton::indicator:unchecked {{
    image: url("{rb_off}");
}}
QRadioButton::indicator:checked {{
    image: url("{rb_on}");
}}
QRadioButton::indicator:unchecked:disabled {{
    image: url("{rb_off_dis}");
}}
QRadioButton::indicator:checked:disabled {{
    image: url("{rb_on_dis}");
}}

QGroupBox {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 8px;
    font-family: "{sec_family}";
    font-size: {sec_px}px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {t.ACCENT};
    background: {t.SURFACE};
    font-family: "{sec_family}";
    font-size: {sec_px}px;
    font-weight: bold;
}}

QTabWidget::pane {{
    background: {t.SURFACE};
    border: 1px solid {t.BORDER};
    top: -1px;
}}
QTabBar::tab {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 4px 12px;
    margin-right: 2px;
    min-height: 20px;
}}
QTabBar::tab:selected {{
    background: {t.ACCENT};
    color: #ffffff;
    border-color: {t.ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background: {t.ACCENT_SOFT};
    color: {t.ACCENT_TEXT};
    border-color: {t.ACCENT};
}}

QTableWidget, QTableView, QTreeWidget, QListWidget {{
    background: {t.SURFACE};
    alternate-background-color: {t.CHROME};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    gridline-color: {t.BORDER};
    selection-background-color: {t.ACCENT};
    selection-color: #ffffff;
    outline: none;
    show-decoration-selected: 1;
}}
QTableWidget::item, QTableView::item, QTreeWidget::item, QListWidget::item {{
    padding: 2px 4px;
}}
QTableWidget::item:selected, QTableView::item:selected,
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {t.ACCENT};
    color: #ffffff;
}}
QTableWidget::item:selected:!active, QTableView::item:selected:!active {{
    background: {t.ACCENT};
    color: #ffffff;
}}
QHeaderView::section {{
    background: {t.TABLE_HEADER};
    color: {t.TEXT};
    border: none;
    border-right: 1px solid {t.BORDER};
    border-bottom: 1px solid {t.BORDER};
    padding: 4px 6px;
    font-family: "{sec_family}";
    font-size: {sec_px}px;
    font-weight: bold;
}}

QScrollBar:vertical {{
    background: {t.SCROLL_TROUGH};
    width: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {t.SCROLL_BG};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: #b7c3d4;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {t.SCROLL_TROUGH};
    height: 12px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {t.SCROLL_BG};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QSplitter::handle {{
    background: {t.BG};
    width: 8px;
}}

QToolTip {{
    background: {t.SURFACE};
    color: {t.TEXT};
    border: 1px solid {t.BORDER};
    padding: 4px;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {t.BORDER};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {t.ACCENT};
}}
"""
