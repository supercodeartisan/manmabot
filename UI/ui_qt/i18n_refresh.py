"""Swap visible widget text when the UI language changes.

Widgets keep their identity. Only a string that matches the previous
language table is replaced, so typed names and coordinates stay put.
"""

from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ui_qt.i18n_overlay import pop_tx_bind, push_tx_bind, take_tx

TX_ROLE = Qt.ItemDataRole.UserRole + 41
_PATCHED: list[tuple[type, str, object]] = []


@contextmanager
def bind_tx_keys():
    """Tag widgets created from ``tx`` while this block runs."""
    first = not _PATCHED
    if first:
        _install_tx_patches()
    push_tx_bind()
    try:
        yield
    finally:
        pop_tx_bind()
        if first:
            _remove_tx_patches()


def _install_tx_patches() -> None:
    for cls, name in (
        (QLabel, "__init__"),
        (QPushButton, "__init__"),
        (QCheckBox, "__init__"),
        (QRadioButton, "__init__"),
        (QGroupBox, "__init__"),
        (QTableWidgetItem, "__init__"),
        (QLabel, "setText"),
        (QPushButton, "setText"),
        (QCheckBox, "setText"),
        (QRadioButton, "setText"),
        (QGroupBox, "setTitle"),
        (QTableWidgetItem, "setText"),
        (QComboBox, "addItem"),
        (QTableWidget, "setHorizontalHeaderLabels"),
    ):
        original = getattr(cls, name)
        _PATCHED.append((cls, name, original))
        setattr(cls, name, _make_wrapper(name, original))


def _remove_tx_patches() -> None:
    while _PATCHED:
        cls, name, original = _PATCHED.pop()
        setattr(cls, name, original)


def _make_wrapper(name: str, original):
    def wrapped(widget, *args, **kwargs):
        result = original(widget, *args, **kwargs)
        if name == "setHorizontalHeaderLabels":
            labels = args[0] if args else ()
            for column in range(len(labels) - 1, -1, -1):
                key = take_tx(str(labels[column] or ""))
                item = widget.horizontalHeaderItem(column)
                if key and item is not None:
                    item.setData(TX_ROLE, key)
            return result
        text = _phrase(name, widget, args)
        key = take_tx(text)
        if not key:
            return result
        if name == "addItem" and isinstance(widget, QComboBox):
            widget.setItemData(widget.count() - 1, key, TX_ROLE)
        elif isinstance(widget, QTableWidgetItem):
            widget.setData(TX_ROLE, key)
        else:
            widget.setProperty("txKey", key)
        return result

    return wrapped


def _phrase(name: str, widget, args: tuple) -> str:
    if name == "__init__":
        if isinstance(widget, QGroupBox):
            return widget.title()
        if isinstance(widget, (QLabel, QAbstractButton, QTableWidgetItem)):
            return widget.text()
        return ""
    if not args:
        return ""
    if name == "addItem" and not isinstance(args[0], str) and len(args) > 1:
        return str(args[1] or "")
    return str(args[0] or "")


def _apply_keyed_text(current: str, key: object, old: dict[str, str], new: dict[str, str]) -> str | None:
    if not isinstance(key, str) or not key:
        return None
    nxt = new.get(key, "")
    previous = old.get(key, "")
    if not nxt or "{" in nxt or nxt == current:
        return None
    if previous and current != previous:
        return None
    return nxt


def mapped_text(
    text: str,
    old: dict[str, str],
    new: dict[str, str],
    *,
    index: dict[str, tuple[str, ...]] | None = None,
) -> str | None:
    """Return the new wording when every old key for ``text`` agrees."""
    if not text:
        return None
    if index is None:
        keys = tuple(key for key, value in old.items() if value == text)
    else:
        keys = index.get(text, ())
    if not keys:
        return None
    updated = {new.get(key, text) for key in keys}
    if len(updated) != 1:
        return None
    nxt = next(iter(updated))
    if nxt == text:
        return None
    return nxt


def _value_index(table: dict[str, str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for key, value in table.items():
        if value:
            grouped.setdefault(value, []).append(key)
    return {value: tuple(keys) for value, keys in grouped.items()}


def retranslate_tree(
    root: QWidget,
    old: dict[str, str],
    new: dict[str, str],
    *,
    skip: tuple[QWidget, ...] = (),
) -> int:
    """Update chrome under ``root``. Returns how many strings changed."""
    skipped = {widget for widget in skip if widget is not None}
    index = _value_index(old)
    changed = 0
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget in skipped:
            continue
        keyed = _apply_keyed_text(
            _widget_phrase(widget), widget.property("txKey"), old, new
        )
        if keyed is not None:
            _set_widget_phrase(widget, keyed)
            changed += 1
        tip = mapped_text(widget.toolTip(), old, new, index=index)
        if tip is not None:
            widget.setToolTip(tip)
            changed += 1
        if isinstance(widget, QGroupBox):
            title = mapped_text(widget.title(), old, new, index=index)
            if title is not None:
                widget.setTitle(title)
                changed += 1
        if isinstance(widget, (QLabel, QAbstractButton)):
            label = mapped_text(widget.text(), old, new, index=index)
            if label is not None:
                widget.setText(label)
                changed += 1
        elif isinstance(widget, QLineEdit):
            hint = mapped_text(widget.placeholderText(), old, new, index=index)
            if hint is not None:
                widget.setPlaceholderText(hint)
                changed += 1
        elif isinstance(widget, QComboBox):
            for row in range(widget.count()):
                keyed = _apply_keyed_text(
                    widget.itemText(row),
                    widget.itemData(row, TX_ROLE),
                    old,
                    new,
                )
                if keyed is not None:
                    widget.setItemText(row, keyed)
                    changed += 1
                    continue
                item = mapped_text(widget.itemText(row), old, new, index=index)
                if item is None:
                    continue
                widget.setItemText(row, item)
                changed += 1
        elif isinstance(widget, QTabWidget):
            for row in range(widget.count()):
                tab = mapped_text(widget.tabText(row), old, new, index=index)
                if tab is None:
                    continue
                widget.setTabText(row, tab)
                changed += 1
        if isinstance(widget, QTableWidget):
            changed += _retranslate_table(widget, old, new, index)
        elif isinstance(widget, QListWidget):
            changed += _retranslate_list(widget, old, new, index)
    return changed


def _retranslate_table(
    table: QTableWidget,
    old: dict[str, str],
    new: dict[str, str],
    index: dict[str, tuple[str, ...]],
) -> int:
    changed = 0
    for column in range(table.columnCount()):
        header = table.horizontalHeaderItem(column)
        if header is None:
            continue
        keyed = _apply_keyed_text(header.text(), header.data(TX_ROLE), old, new)
        text = keyed if keyed is not None else mapped_text(header.text(), old, new, index=index)
        if text is None:
            continue
        header.setText(text)
        changed += 1
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            item = table.item(row, column)
            if item is None:
                continue
            keyed = _apply_keyed_text(item.text(), item.data(TX_ROLE), old, new)
            text = keyed if keyed is not None else mapped_text(item.text(), old, new, index=index)
            if text is None:
                continue
            item.setText(text)
            changed += 1
    return changed


def _retranslate_list(
    widget: QListWidget,
    old: dict[str, str],
    new: dict[str, str],
    lookup: dict[str, tuple[str, ...]],
) -> int:
    changed = 0
    for row in range(widget.count()):
        item = widget.item(row)
        if item is None:
            continue
        text = mapped_text(item.text(), old, new, index=lookup)
        if text is None:
            continue
        item.setText(text)
        changed += 1
    return changed


def _widget_phrase(widget: QWidget) -> str:
    if isinstance(widget, QGroupBox):
        return widget.title()
    if isinstance(widget, (QLabel, QAbstractButton)):
        return widget.text()
    return ""


def _set_widget_phrase(widget: QWidget, text: str) -> None:
    if isinstance(widget, QGroupBox):
        widget.setTitle(text)
    elif isinstance(widget, (QLabel, QAbstractButton)):
        widget.setText(text)
