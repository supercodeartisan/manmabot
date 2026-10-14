"""Small Qt form helpers shared by editor tabs."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ui_qt.theme import tokens
from ui_qt.viewmodels.settings_bag import SettingsBag
from ui_qt.widgets.step_spin import StepSpinBox


def configure_select_rows(table: QTableWidget) -> None:
    """Full-row selection chrome (classic ttk Treeview browse/extended)."""
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    # Keep cell text whole — no mid-string "…" clipping (classic Treeview fit).
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    table.setWordWrap(True)
    table.setStyleSheet(
        f"""
        QTableWidget::item:selected {{
            background: {tokens.ACCENT};
            color: #ffffff;
        }}
        QTableWidget::item:selected:!active {{
            background: {tokens.ACCENT};
            color: #ffffff;
        }}
        """
    )
    if not getattr(table, "_row_select_wired", False):
        table.itemSelectionChanged.connect(lambda t=table: sync_row_widget_selection(t))
        table._row_select_wired = True  # type: ignore[attr-defined]


def fit_table_columns(
    table: QTableWidget,
    *,
    stretch_last: bool = False,
    min_width: int = 48,
    pad: int = 28,
) -> None:
    """Size every column to its heading and cell text so strings stay intact."""
    from PySide6.QtGui import QFontMetrics

    header = table.horizontalHeader()
    body = QFontMetrics(table.font())
    head = QFontMetrics(header.font())
    last = table.columnCount() - 1
    header.setStretchLastSection(False)
    for col in range(table.columnCount()):
        head_item = table.horizontalHeaderItem(col)
        title = head_item.text() if head_item is not None else ""
        width = head.horizontalAdvance(title) + 40
        for row in range(table.rowCount()):
            item = table.item(row, col)
            if item is not None:
                width = max(width, body.horizontalAdvance(item.text()) + pad)
            widget = table.cellWidget(row, col)
            if widget is not None:
                width = max(width, int(widget.sizeHint().width()) + 8)
        width = max(int(width), int(min_width))
        table.setColumnWidth(col, width)
        if stretch_last and col == last:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
    if stretch_last and last >= 0:
        header.setStretchLastSection(True)


def configure_table_fill(
    table: QTableWidget,
    stretch_col: int,
    *,
    fixed: dict[int, int] | None = None,
) -> None:
    """Stretch one column so the header/grid fills the table viewport edge-to-edge.

    ``fixed`` maps column index → pixel width (icon columns, etc.).
    Other non-stretch columns use Interactive (not ResizeToContents) so long
    cell text cannot starve the stretch column and leave a right-edge gap.
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    fixed = fixed or {}
    for index, width in fixed.items():
        table.setColumnWidth(index, int(width))
        header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
    for index in range(table.columnCount()):
        if index in fixed:
            continue
        if index == stretch_col:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
    # Last-column stretch is the most reliable way to pin the right edge.
    if stretch_col == table.columnCount() - 1:
        header.setStretchLastSection(True)


def cell_button(text: str, *, compact: bool = True) -> QPushButton:
    """Table-cell button — fills the cell host with a small inset padding."""
    btn = QPushButton(text)
    btn.setObjectName("cellButton")
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    if compact:
        btn.setMinimumHeight(0)
    return btn


def wrap_cell_widget(inner: QWidget, *, hpad: int = 3, vpad: int = 2) -> QWidget:
    """Inset a cell widget so borders do not collide with grid lines.

    The inner widget stretches to fill the cell (width + height) so buttons and
    steppers show fully with only a small padding inset.
    """
    host = QWidget()
    host.setObjectName("cellHost")
    row = QHBoxLayout(host)
    row.setContentsMargins(hpad, vpad, hpad, vpad)
    row.setSpacing(0)
    inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    row.addWidget(inner, stretch=1)
    return host


def table_row_height_for_controls() -> int:
    """Row height that fully fits cell buttons / steppers with small padding."""
    return 36


def sync_row_widget_selection(table: QTableWidget) -> None:
    """Paint cell *hosts* for selected rows; never strip button/spin chrome."""
    model = table.selectionModel()
    selected = {idx.row() for idx in model.selectedRows()} if model else set()
    for row in range(table.rowCount()):
        on = row in selected
        bg = tokens.ACCENT if on else "transparent"
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                table.setItem(row, col, item)
            widget = table.cellWidget(row, col)
            if widget is None:
                continue
            # Only tint the host; child buttons/spins keep their QSS.
            widget.setStyleSheet(f"QWidget#cellHost {{ background: {bg}; }}")


def card(parent: QWidget, title: str) -> QGroupBox:
    box = QGroupBox(title, parent)
    QVBoxLayout(box)
    return box


def bind_gate(master: QCheckBox, *widgets: QWidget) -> None:
    """Classic ``_bind_gate``: children enabled only while master is checked."""

    def _apply(checked: bool = False) -> None:
        on = bool(master.isChecked())
        for widget in widgets:
            if widget is None or widget is master:
                continue
            widget.setEnabled(on)

    master.toggled.connect(_apply)
    _apply(master.isChecked())


def add_check(
    layout: QVBoxLayout | QHBoxLayout,
    bag: SettingsBag,
    section: str,
    key: str,
    label: str,
    default: bool,
    on_change: Callable[[], None] | None = None,
) -> QCheckBox:
    box = QCheckBox(label)
    box.setChecked(bag.get_bool(section, key, default))

    def _sync(checked: bool) -> None:
        bag.set(section, key, bool(checked))
        if on_change:
            on_change()

    box.toggled.connect(_sync)
    layout.addWidget(box)
    return box


def add_spin_row(
    layout: QVBoxLayout,
    bag: SettingsBag,
    section: str,
    key: str,
    label: str,
    default: int,
    low: int,
    high: int,
    suffix: str = "",
    on_change: Callable[[], None] | None = None,
) -> StepSpinBox:
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    spin = StepSpinBox()
    spin.setRange(low, high)
    spin.setValue(bag.get_int(section, key, default))

    def _sync(value: int) -> None:
        bag.set(section, key, int(value))
        if on_change:
            on_change()

    def _commit() -> None:
        bag.set(section, key, int(spin.value()))
        if on_change:
            on_change()

    spin.valueChanged.connect(_sync)
    spin.editingFinished.connect(_commit)
    row.addWidget(spin)
    if suffix:
        row.addWidget(QLabel(suffix))
    row.addStretch(1)
    layout.addLayout(row)
    return spin


def add_check_spin(
    layout: QVBoxLayout,
    bag: SettingsBag,
    check_key: str,
    check_default: bool,
    check_label: str,
    spin_key: str,
    spin_default: int,
    low: int,
    high: int,
    suffix: str = "",
    *,
    section: str = "hunt",
    on_change: Callable[[], None] | None = None,
) -> tuple[QCheckBox, StepSpinBox]:
    row = QHBoxLayout()
    check = QCheckBox(check_label)
    check.setChecked(bag.get_bool(section, check_key, check_default))
    spin = StepSpinBox()
    spin.setRange(low, high)
    spin.setValue(bag.get_int(section, spin_key, spin_default))

    def _sync_check(checked: bool) -> None:
        bag.set(section, check_key, bool(checked))
        spin.setEnabled(bool(checked))
        if on_change:
            on_change()

    def _sync_spin(value: int) -> None:
        bag.set(section, spin_key, int(value))
        if on_change:
            on_change()

    def _commit_spin() -> None:
        bag.set(section, spin_key, int(spin.value()))
        if on_change:
            on_change()

    check.toggled.connect(_sync_check)
    spin.valueChanged.connect(_sync_spin)
    spin.editingFinished.connect(_commit_spin)
    spin.setEnabled(check.isChecked())
    row.addWidget(check)
    row.addWidget(spin)
    if suffix:
        row.addWidget(QLabel(suffix))
    row.addStretch(1)
    layout.addLayout(row)
    return check, spin
