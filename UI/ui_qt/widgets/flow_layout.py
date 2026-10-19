"""Wrapping flow layout (classic tool/category reflow parity)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Left-to-right, top-to-bottom wrapping layout."""

    def __init__(self, parent: QWidget | None = None, margin: int = 0, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:
        # Prefer inherited ``addWidget`` so Qt reparents via addChildWidget.
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        width = self.geometry().width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        if width <= 0:
            width = 640
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        # Must grow vertically when buttons wrap; a single-row minimum clips tools.
        width = self.geometry().width()
        if width <= 0 and self.parentWidget() is not None:
            width = self.parentWidget().width()
        if width <= 0:
            width = 320
        height = self.heightForWidth(width)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        size = QSize(
            max(size.width() + left + right, 40),
            max(height, size.height() + top + bottom),
        )
        return size

    def spacing(self) -> int:
        return self._spacing

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        y = effective.y()
        space = self._spacing
        line: list[tuple[QLayoutItem, QSize]] = []
        line_height = 0

        def line_width() -> int:
            if not line:
                return 0
            return sum(h.width() for _i, h in line) + space * (len(line) - 1)

        def flush_line(row_y: int) -> int:
            nonlocal line, line_height
            if not line:
                return row_y
            cursor = effective.x()
            for item, hint in line:
                if not test_only:
                    # Vertically center widgets of mixed height on the same row
                    # (e.g. zoom "%" between − / + buttons).
                    iy = row_y + max(0, (line_height - hint.height()) // 2)
                    item.setGeometry(QRect(QPoint(cursor, iy), hint))
                cursor += hint.width() + space
            next_y = row_y + line_height + space
            line = []
            line_height = 0
            return next_y

        for item in self._items:
            # Do not skip widgets that are not visible yet. The magic category
            # row is laid out while those buttons are still hidden, and treating
            # them as absent reports height 0 so the row never appears.
            hint = item.sizeHint()
            next_width = line_width() + hint.width() + (space if line else 0)
            if line and next_width > effective.width():
                y = flush_line(y)
            line.append((item, hint))
            line_height = max(line_height, hint.height())
        y = flush_line(y)
        # Last flush adds a trailing spacing; strip it when we laid out a row.
        content_bottom = y - space if y > effective.y() else effective.y()
        return content_bottom - rect.y() + bottom

