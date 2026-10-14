"""Other tab — game F-keys, diagnostics, profile I/O, hotkeys (classic parity)."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import (
    language_display_name,
    map_display_name,
    memory_name_for_ui,
)
from i18n.strings import DEFAULT_HOTKEYS
from session.bot_controller import RunState
from session.paths import LOG_DIR
from session.probes import Lamp, localize_probe_detail
from settings.profile import (
    Profile,
    delete_named_profile,
    list_profile_names,
    load_named_profile,
    named_profile_path,
    save_named_profile,
    save_profile,
)
from settings.spell_defaults import SKILL_GRID, SKILL_KEYS, spell_slot_bindings
from ui_qt.editors.form_helpers import card
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.theme import tokens
from ui_qt.theme.apply import mark_accent
from ui_qt.viewmodels.settings_bag import SettingsBag

_SLOT_MIN = 56
_CLASS_MARKS = ("⚔", "🗡", "✦")
_BADGE = {
    "SPELL": ("#166534", "#dcfce7"),
    "ITEM": ("#1d4ed8", "#dbeafe"),
    "STALE": ("#92400e", "#fef3c7"),
    "EMPTY": ("#111827", "#ffffff"),
}


class _HotbarWorker(QThread):
    finished_ok = Signal(object, object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            from hotbar.inspect import inspect_hotbars

            detected = inspect_hotbars()
            self.finished_ok.emit(detected.to_profile_dict(), detected.spell_slots)
        except Exception as exc:
            self.failed.emit(str(exc))


class OtherTab(QWidget):
    def __init__(
        self,
        *,
        profile: Profile,
        bridge: QtBridge,
        strings: dict[str, str],
        language: str,
        bag: SettingsBag | None = None,
        on_log: Callable[[str], None] | None = None,
        on_run_setup: Callable[[], None] | None = None,
        on_start_driver: Callable[[], None] | None = None,
        on_profile_reloaded: Callable[[], None] | None = None,
        on_hotbar_applied: Callable[[], None] | None = None,
        get_log_lines: Callable[[], list[str]] | None = None,
        clear_shell_logs: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.profile = profile
        self.bridge = bridge
        self.bag = bag
        self.t = strings
        self.language = language
        self.on_log = on_log or (lambda _m: None)
        self.on_run_setup = on_run_setup
        self.on_start_driver = on_start_driver
        self.on_profile_reloaded = on_profile_reloaded
        self.on_hotbar_applied = on_hotbar_applied
        self.get_log_lines = get_log_lines
        self.clear_shell_logs = clear_shell_logs

        self._worker: _HotbarWorker | None = None
        self._slot_names: dict[tuple[int, str], QLabel] = {}
        self._slot_badges: dict[tuple[int, str], QLabel] = {}
        self._slot_tiles: dict[tuple[int, str], QFrame] = {}
        self._status_states: dict[str, QLabel] = {}
        self._status_values: dict[str, QLabel] = {}
        self._profile_info: dict[str, QLabel] = {}
        self._hotkey_labels: dict[str, QLabel] = {}
        self._hotkey_enabled: dict[str, QCheckBox] = {}

        self._build()
        self.bridge.hotbarUpdated.connect(self.apply_hotbar_from_bridge)

    def retranslate(self, strings: dict[str, str], language: str | None = None) -> None:
        self.t = strings
        if language is not None:
            self.language = language
        # Nested tab titles
        if hasattr(self, "tabs"):
            titles = (
                self.t.get("game_f_keys", "Game F keys"),
                self.t.get("diagnostics", "Diagnostics"),
                self.t.get("copy_import", "Profiles"),
                self.t.get("hotkeys", "Hotkeys"),
            )
            for i, title in enumerate(titles):
                if i < self.tabs.count():
                    self.tabs.setTabText(i, title)
        self.refresh_hotbar_view()
        self._reload_profile_table()
        self._load_hotkey_fields()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.hotbar_page = QWidget()
        self.diag_page = QWidget()
        self.copy_page = QWidget()
        self.hotkey_page = QWidget()
        self.tabs.addTab(self.hotbar_page, self.t.get("game_f_keys", "Game F keys"))
        self.tabs.addTab(self.diag_page, self.t.get("diagnostics", "Diagnostics"))
        self.tabs.addTab(self.copy_page, self.t.get("copy_import", "Profiles"))
        self.tabs.addTab(self.hotkey_page, self.t.get("hotkeys", "Hotkeys"))
        root.addWidget(self.tabs)
        self._build_hotbar(self.hotbar_page)
        self._build_diagnostics(self.diag_page)
        self._build_copy_import(self.copy_page)
        self._build_hotkeys(self.hotkey_page)
        self.refresh_hotbar_view()
        self._reload_profile_table()
        self._load_hotkey_fields()
        if self.get_log_lines is not None:
            for line in self.get_log_lines():
                stamp, _, message = str(line).partition("  ")
                self.append_log_row(stamp or str(line), message)

    # --- Game F-keys ------------------------------------------------------------

    def _build_hotbar(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel(self.t.get("detected_hotbar", "Hotbar detection result"))
        title.setStyleSheet(f"color: {tokens.ACCENT}; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self._btn_refresh = QPushButton(self.t.get("hotbar_refresh", "Show / refresh"))
        mark_accent(self._btn_refresh)
        self._btn_refresh.clicked.connect(self.refresh_hotbar_scan)
        header.addWidget(self._btn_refresh)
        host_layout.addLayout(header)

        meta = QHBoxLayout()
        self._hotbar_basis = QLabel(self.t.get("hotbar_memory_basis", ""))
        self._hotbar_basis.setObjectName("muted")
        self._hotbar_updated = QLabel(
            self.t.get("hotbar_last_update", "Updated: {time}").format(time="—")
        )
        self._hotbar_updated.setObjectName("muted")
        self._hotbar_total = QLabel(
            self.t.get("hotbar_total_slots", "Slots: {count}").format(count=24)
        )
        self._hotbar_total.setObjectName("muted")
        meta.addWidget(self._hotbar_basis)
        meta.addWidget(self._hotbar_updated)
        meta.addWidget(self._hotbar_total)
        meta.addStretch(1)
        host_layout.addLayout(meta)

        self._hotbar_empty = QLabel(self.t.get("hotbar_waiting_scan", ""))
        self._hotbar_empty.setWordWrap(True)
        self._hotbar_empty.setObjectName("muted")
        host_layout.addWidget(self._hotbar_empty)

        cards = QHBoxLayout()
        cards.setSpacing(8)
        for index, box in enumerate((1, 2, 3)):
            card_box = QFrame()
            card_box.setObjectName("hotbarCard")
            card_box.setStyleSheet(
                f"QFrame#hotbarCard {{ background: {tokens.SURFACE}; "
                f"border: 1px solid {tokens.BORDER}; }}"
            )
            card_layout = QVBoxLayout(card_box)
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(0)
            title_row = QLabel(
                f"{_CLASS_MARKS[index]}  "
                + self.t.get("hotbar_class_n", "F{n} class").format(n=box)
            )
            title_row.setStyleSheet(
                f"background: {tokens.ACCENT_SOFT}; padding: 8px 10px; color: {tokens.TEXT};"
            )
            card_layout.addWidget(title_row)
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setSpacing(4)
            for row_i, row_keys in enumerate(SKILL_GRID):
                for col_i, key in enumerate(row_keys):
                    tile = QFrame()
                    tile.setFixedSize(_SLOT_MIN, _SLOT_MIN)
                    tile.setStyleSheet(
                        "background: #1f2937; border: 1px solid #374151;"
                    )
                    tile_layout = QVBoxLayout(tile)
                    tile_layout.setContentsMargins(2, 2, 2, 2)
                    tile_layout.setSpacing(0)
                    badge = QLabel(key.upper())
                    badge.setAlignment(Qt.AlignmentFlag.AlignLeft)
                    badge.setStyleSheet(
                        "background: #111827; color: #ffffff; padding: 1px 3px; "
                        "font-size: 9px; font-weight: 700;"
                    )
                    badge.setMaximumWidth(28)
                    name = QLabel("")
                    name.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
                    name.setWordWrap(True)
                    name.setStyleSheet("color: #e5e7eb; font-size: 9px;")
                    tile_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)
                    tile_layout.addStretch(1)
                    tile_layout.addWidget(name)
                    grid.addWidget(tile, row_i, col_i)
                    self._slot_tiles[(box, key)] = tile
                    self._slot_badges[(box, key)] = badge
                    self._slot_names[(box, key)] = name
            card_layout.addWidget(grid_host)
            cards.addWidget(card_box, stretch=1)
        host_layout.addLayout(cards)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll)

    def refresh_hotbar_view(self) -> None:
        layout: dict[str, Any] = {}
        if self.bag is not None:
            raw = self.bag.get("magic", "hotbar_layout", {})
            if isinstance(raw, dict) and raw:
                layout = raw
        if not layout:
            layout = getattr(self.profile, "hotbar_layout", None) or {}
        boxes = layout.get("boxes") if isinstance(layout, dict) else {}
        if not isinstance(boxes, dict):
            boxes = {}
        filled = 0
        for box in (1, 2, 3):
            box_cells = boxes.get(str(box))
            if not isinstance(box_cells, dict):
                box_cells = {}
            for key in SKILL_KEYS:
                cell = box_cells.get(key) if isinstance(box_cells.get(key), dict) else {}
                raw_name = str(cell.get("kr_name") or cell.get("label") or "").strip()
                name = memory_name_for_ui(raw_name, self.language) if raw_name else ""
                kind = str(cell.get("kind") or "").upper()
                if not kind:
                    kind = "EMPTY" if not name else ""
                count = cell.get("count")
                if count in (None, "") and raw_name:
                    try:
                        from hotbar.inspect import count_from_hotbar_label

                        count = count_from_hotbar_label(raw_name)
                    except Exception:
                        count = None
                bits: list[str] = []
                if name:
                    bits.append(name)
                    filled += 1
                if kind == "ITEM" and count not in (None, "", 0):
                    bits.append(f"×{count}")
                caption = self._slot_names.get((box, key))
                badge = self._slot_badges.get((box, key))
                if caption is not None:
                    text = " ".join(bits)
                    caption.setText(text)
                    caption.setToolTip(text)
                if badge is not None:
                    bg, fg = _BADGE.get(kind or "EMPTY", ("#111827", "#ffffff"))
                    badge.setText(key.upper())
                    badge.setStyleSheet(
                        f"background: {bg}; color: {fg}; padding: 1px 3px; "
                        f"font-size: 9px; font-weight: 700;"
                    )
        stamp = str(layout.get("updated_at") or "").strip() if isinstance(layout, dict) else ""
        self._hotbar_updated.setText(
            self.t.get("hotbar_last_update", "Updated: {time}").format(time=stamp or "—")
        )
        self._hotbar_total.setText(
            self.t.get("hotbar_total_slots", "Slots: {count}").format(count=24)
        )
        self._hotbar_empty.setVisible(filled == 0)

    def refresh_hotbar_scan(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._btn_refresh.setEnabled(False)
        self._hotbar_updated.setText(self.t.get("hotbar_refreshing", "Refreshing…"))
        self._hotbar_empty.setText(self.t.get("hotbar_refreshing", "Refreshing…"))
        self._hotbar_empty.setVisible(True)
        self._worker = _HotbarWorker(self)
        self._worker.finished_ok.connect(self._on_hotbar_scan_ok)
        self._worker.failed.connect(self._on_hotbar_scan_fail)
        self._worker.finished.connect(lambda: self._btn_refresh.setEnabled(True))
        self._worker.start()

    def _on_hotbar_scan_ok(self, layout: object, slots: object) -> None:
        if not isinstance(layout, dict):
            self._on_hotbar_scan_fail(self.t.get("hotbar_refresh_failed", "Failed: {error}").format(error="—"))
            return
        stamped = dict(layout)
        stamped["updated_at"] = f"{datetime.now():%H:%M:%S}"
        merged_slots = slots if isinstance(slots, dict) else {}
        try:
            from hotbar.inspect import merge_detected_spell_slots
            from settings.haste_potion import apply_haste_potion_to_spell_slots
            from settings.hp_actions import apply_recovery_to_spell_slots

            previous = {}
            if self.bag is not None:
                previous = self.bag.get("magic", "spell_slots", {}) or {}
            if not isinstance(previous, dict) or not previous:
                previous = getattr(self.profile, "spell_slots", {}) or {}
            hp_actions = None
            if self.bag is not None:
                hp_actions = self.bag.get("recovery", "hp_actions", None)
            if hp_actions is None:
                hp_actions = getattr(self.profile, "hp_actions", None)
            merged_slots = apply_recovery_to_spell_slots(
                merge_detected_spell_slots(merged_slots, previous),
                hp_actions,
            )
            use_haste = bool(getattr(self.profile, "use_haste_potion", False))
            haste_item = str(getattr(self.profile, "haste_potion_item", "") or "")
            haste_box = getattr(self.profile, "haste_potion_box", 0)
            haste_key = getattr(self.profile, "haste_potion_key", "")
            if self.bag is not None:
                use_haste = self.bag.get_bool("hunt", "use_haste_potion", use_haste)
                haste_item = self.bag.get_str("hunt", "haste_potion_item", haste_item)
                haste_box = self.bag.get_int("hunt", "haste_potion_box", int(haste_box or 0))
                haste_key = self.bag.get_str("hunt", "haste_potion_key", str(haste_key or ""))
            merged_slots = apply_haste_potion_to_spell_slots(
                merged_slots,
                use=use_haste,
                item_key=haste_item,
                box=haste_box,
                key=haste_key,
                layout=stamped,
            )
        except Exception:
            pass
        binding_slots = spell_slot_bindings(merged_slots) if merged_slots else None
        if self.bag is not None:
            self.bag.set("magic", "hotbar_layout", copy.deepcopy(stamped))
            if binding_slots:
                self.bag.set("magic", "spell_slots", copy.deepcopy(binding_slots))
        self.profile.hotbar_layout = stamped
        if binding_slots:
            self.profile.spell_slots = copy.deepcopy(binding_slots)
        try:
            save_profile(self.profile)
        except Exception:
            pass
        self.refresh_hotbar_view()
        if self.on_hotbar_applied is not None:
            self.on_hotbar_applied()

    def _on_hotbar_scan_fail(self, message: str) -> None:
        self._hotbar_empty.setText(
            self.t.get("hotbar_refresh_failed", "Failed: {error}").format(
                error=message or "—"
            )
        )
        self._hotbar_empty.setVisible(True)
        self._hotbar_updated.setText(
            self.t.get("hotbar_last_update", "Updated: {time}").format(time="—")
        )

    def apply_hotbar_from_bridge(self, layout: object, slots: object) -> None:
        if isinstance(layout, dict):
            stamped = dict(layout)
            if "updated_at" not in stamped:
                stamped["updated_at"] = f"{datetime.now():%H:%M:%S}"
            self.profile.hotbar_layout = stamped
            if self.bag is not None:
                self.bag.set("magic", "hotbar_layout", copy.deepcopy(stamped))
        if isinstance(slots, dict) and slots:
            binding = spell_slot_bindings(slots)
            self.profile.spell_slots = copy.deepcopy(binding)
            if self.bag is not None:
                self.bag.set("magic", "spell_slots", copy.deepcopy(binding))
        self.refresh_hotbar_view()

    # --- Diagnostics ------------------------------------------------------------

    def _build_diagnostics(self, page: QWidget) -> None:
        from ui_qt.editors.form_helpers import configure_select_rows

        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        status = card(page, self.t.get("diag_status", "System status"))
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        for key, title_key in (
            ("game", "diag_game"),
            ("memory", "diag_memory"),
            ("map", "diag_map"),
            ("bot", "diag_bot"),
            ("hotbar", "diag_hotbar"),
        ):
            cell = QFrame()
            cell.setMinimumHeight(88)
            cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            cell.setStyleSheet(
                f"background: {tokens.SURFACE}; border: 1px solid {tokens.BORDER};"
            )
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(8, 6, 8, 6)
            cell_layout.setSpacing(2)
            head = QLabel(self.t.get(title_key, key))
            head.setStyleSheet(f"color: {tokens.ACCENT};")
            state = QLabel(self.t.get("status_wait", "Waiting"))
            state.setStyleSheet(f"color: {tokens.ACCENT}; font-weight: 600;")
            detail = QLabel("")
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            detail.setMinimumHeight(32)
            cell_layout.addWidget(head)
            cell_layout.addWidget(state)
            cell_layout.addWidget(detail, stretch=1)
            self._status_states[key] = state
            self._status_values[key] = detail
            status_row.addWidget(cell, stretch=1)
        status.layout().addLayout(status_row)
        layout.addWidget(status)

        # Same row as classic: log (left) + tools/alerts (right), equal top edge.
        split = QSplitter(Qt.Orientation.Horizontal)
        log_card = card(page, self.t.get("exec_log", "Execution log"))
        log_layout = log_card.layout()
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        self._log_autoscroll = QCheckBox(self.t.get("auto_scroll", "Auto-scroll"))
        self._log_autoscroll.setChecked(True)
        toolbar.addWidget(self._log_autoscroll)
        log_layout.addLayout(toolbar)
        self.log_table = QTableWidget(0, 2)
        self.log_table.setHorizontalHeaderLabels(
            [
                self.t.get("log_time", "Time"),
                self.t.get("log_message", "Message"),
            ]
        )
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setColumnWidth(0, 88)
        self.log_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.log_table.setWordWrap(True)
        configure_select_rows(self.log_table)
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log_table.itemSelectionChanged.connect(self._on_log_select)
        log_layout.addWidget(self.log_table, stretch=1)
        log_layout.addWidget(QLabel(self.t.get("log_full_line", "Full line")))
        self.log_detail = QTextEdit()
        self.log_detail.setReadOnly(True)
        self.log_detail.setMaximumHeight(80)
        log_layout.addWidget(self.log_detail)
        split.addWidget(log_card)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        tools = card(side, self.t.get("diag_tools", "Diagnostic tools"))
        for title_key, hint_key, handler in (
            ("copy_diagnostics", "copy_diag_hint", self.copy_diagnostics),
            ("open_logs", "open_logs_hint", self.open_logs),
            ("clear_log", "clear_log_hint", self.clear_log_view),
        ):
            # Title button above hint so long KO strings stay readable.
            row_host = QFrame()
            row_host.setStyleSheet(
                f"background: {tokens.SURFACE}; border: 1px solid {tokens.BORDER};"
            )
            row = QVBoxLayout(row_host)
            row.setContentsMargins(8, 6, 8, 6)
            row.setSpacing(4)
            btn = QPushButton(self.t.get(title_key, title_key))
            btn.clicked.connect(handler)
            hint = QLabel(self.t.get(hint_key, ""))
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            row.addWidget(btn)
            row.addWidget(hint)
            tools.layout().addWidget(row_host)
        side_layout.addWidget(tools)
        alerts = card(side, self.t.get("recent_alerts", "Recent alerts"))
        self.alert_title = QLabel(self.t.get("no_alerts", "No alerts"))
        self.alert_body = QLabel("")
        self.alert_body.setObjectName("muted")
        self.alert_body.setWordWrap(True)
        alerts.layout().addWidget(self.alert_title)
        alerts.layout().addWidget(self.alert_body, stretch=1)
        side_layout.addWidget(alerts, stretch=1)
        split.addWidget(side)
        split.setStretchFactor(0, 7)
        split.setStretchFactor(1, 3)
        split.setSizes([700, 300])
        layout.addWidget(split, stretch=1)

    def show_status(self, game, memory, map_probe) -> None:
        if not self._status_states:
            return
        pairs = (
            ("game", game.lamp, game.detail),
            ("memory", memory.lamp, memory.detail),
            ("map", map_probe.lamp, map_probe.detail),
        )
        for key, lamp, detail in pairs:
            caption, color = self._lamp_caption(lamp)
            self._status_states[key].setText(caption)
            self._status_states[key].setStyleSheet(f"color: {color}; font-weight: 600;")
            self._status_values[key].setText(
                localize_probe_detail(str(detail or ""), self.language)
            )
        state = self.bridge.coordinator.controller.state
        if state == RunState.RUNNING:
            caption, color = self.t.get("status_ok", "Normal"), "#16a34a"
        elif state == RunState.PAUSED:
            caption, color = self.t.get("status_warn", "Warn"), "#d97706"
        else:
            caption, color = self.t.get("status_wait", "Waiting"), tokens.ACCENT
        self._status_states["bot"].setText(caption)
        self._status_states["bot"].setStyleSheet(f"color: {color}; font-weight: 600;")
        self._status_values["bot"].setText(self.t.get(state.value, state.value))
        slots = getattr(self.profile, "spell_slots", {}) or {}
        count = sum(
            1
            for slot in slots.values()
            if isinstance(slot, dict) and str(slot.get("key") or "").strip()
        )
        ok = bool(count)
        self._status_states["hotbar"].setText(
            self.t.get("status_ok", "Normal") if ok else self.t.get("status_wait", "Waiting")
        )
        self._status_states["hotbar"].setStyleSheet(
            f"color: {'#16a34a' if ok else tokens.ACCENT}; font-weight: 600;"
        )
        self._status_values["hotbar"].setText(
            self.t.get("hotbar_ready", "{count} slots").format(count=count)
        )

    def _lamp_caption(self, lamp) -> tuple[str, str]:
        if lamp == Lamp.GREEN:
            return self.t.get("status_ok", "Normal"), "#16a34a"
        if lamp == Lamp.YELLOW:
            return self.t.get("status_warn", "Warn"), "#d97706"
        if lamp == Lamp.RED:
            return self.t.get("status_error", "Error"), "#dc2626"
        return self.t.get("status_wait", "Waiting"), tokens.ACCENT

    def append_log_row(self, stamp: str, message: str) -> None:
        if not hasattr(self, "log_table"):
            return
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        self.log_table.setItem(row, 0, QTableWidgetItem(str(stamp)))
        self.log_table.setItem(row, 1, QTableWidgetItem(str(message)))
        while self.log_table.rowCount() > 500:
            self.log_table.removeRow(0)
        if self._log_autoscroll.isChecked():
            self.log_table.selectRow(self.log_table.rowCount() - 1)
            self.log_table.scrollToBottom()
            self._show_log_detail(stamp, message)
        self.alert_title.setText(str(message))
        self.alert_body.setText(str(stamp))

    def _on_log_select(self) -> None:
        items = self.log_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        stamp_item = self.log_table.item(row, 0)
        msg_item = self.log_table.item(row, 1)
        if stamp_item is None or msg_item is None:
            return
        self._show_log_detail(stamp_item.text(), msg_item.text())

    def _show_log_detail(self, stamp: str, message: str) -> None:
        self.log_detail.setPlainText(f"{stamp}  {message}")

    def clear_log_view(self) -> None:
        self.log_table.setRowCount(0)
        self.log_detail.clear()
        self.alert_title.setText(self.t.get("no_alerts", "No alerts"))
        self.alert_body.setText("")
        if self.clear_shell_logs is not None:
            self.clear_shell_logs()

    def copy_diagnostics(self) -> None:
        try:
            game, memory, map_probe = self.bridge.probes()
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("diagnostics", "Diagnostics"), str(exc))
            return
        text = (
            f"Manmabot v1\ngame={game.detail}\nmemory={memory.detail}\nmap={map_probe.detail}\n"
            f"active_map={self.profile.active_map}\ncharacter={self.profile.character}\n"
            f"language={self.profile.language}\ngame_language={self.profile.game_language}\n"
        )
        QGuiApplication.clipboard().setText(text)
        self.on_log(self.t.get("diagnostics_copied", "Diagnostics copied."))

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(LOG_DIR))  # noqa: S606
        else:
            self.on_log(str(LOG_DIR))

    # --- Copy / import ----------------------------------------------------------

    def _build_copy_import(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        library = card(page, self.t.get("saved_profiles", "Saved profiles"))
        lib = library.layout()
        hint = QLabel(self.t.get("saved_profiles_hint", ""))
        hint.setWordWrap(True)
        lib.addWidget(hint)
        save_row = QHBoxLayout()
        save_row.addWidget(QLabel(self.t.get("profile_name", "Name")))
        self.profile_name_edit = QLineEdit()
        save_row.addWidget(self.profile_name_edit, stretch=1)
        save_btn = QPushButton(self.t.get("save_current", "Save current"))
        mark_accent(save_btn)
        save_btn.clicked.connect(self._save_profile_from_entry)
        save_row.addWidget(save_btn)
        lib.addLayout(save_row)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.profile_table = QTableWidget(0, 3)
        self.profile_table.setHorizontalHeaderLabels(
            [
                self.t.get("col_name", "Name"),
                self.t.get("profile_class", "Class"),
                self.t.get("profile_date", "Date"),
            ]
        )
        self.profile_table.horizontalHeader().setStretchLastSection(True)
        self.profile_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.profile_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.profile_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.profile_table.itemSelectionChanged.connect(self._show_selected_profile)
        left.addWidget(self.profile_table)
        actions = QHBoxLayout()
        load_btn = QPushButton(self.t.get("load_profile", "Load"))
        load_btn.clicked.connect(self._load_selected_profile)
        del_btn = QPushButton(self.t.get("delete_profile", "Delete"))
        del_btn.clicked.connect(self._delete_selected_profile)
        actions.addWidget(load_btn)
        actions.addWidget(del_btn)
        actions.addStretch(1)
        left.addLayout(actions)
        body.addLayout(left, stretch=3)

        detail = QVBoxLayout()
        detail.addWidget(QLabel(self.t.get("selected_profile", "Selected")))
        self.profile_empty = QLabel(self.t.get("no_profile", "No profile selected"))
        self.profile_empty.setObjectName("muted")
        detail.addWidget(self.profile_empty)
        for key, label_key in (
            ("name", "col_name"),
            ("class", "profile_class"),
            ("created", "profile_date"),
            ("language", "language"),
            ("map", "map"),
        ):
            row = QHBoxLayout()
            lab = QLabel(self.t.get(label_key, key))
            lab.setObjectName("muted")
            lab.setMinimumWidth(96)
            lab.setWordWrap(True)
            value = QLabel("-")
            value.setWordWrap(True)
            row.addWidget(lab)
            row.addWidget(value, stretch=1)
            self._profile_info[key] = value
            detail.addLayout(row)
        detail.addStretch(1)
        body.addLayout(detail, stretch=2)
        lib.addLayout(body)
        layout.addWidget(library)

        files = card(page, self.t.get("file_transfer", "File transfer"))
        transfer_hint = QLabel(self.t.get("file_transfer_hint", ""))
        transfer_hint.setWordWrap(True)
        transfer_hint.setObjectName("muted")
        files.layout().addWidget(transfer_hint)
        export_row = QHBoxLayout()
        export_btn = QPushButton(self.t.get("export_file", "Export"))
        export_btn.clicked.connect(self._export_selected_profile)
        export_hint = QLabel(self.t.get("export_file_hint", ""))
        export_hint.setObjectName("muted")
        export_hint.setWordWrap(True)
        export_row.addWidget(export_btn)
        export_row.addWidget(export_hint, stretch=1)
        files.layout().addLayout(export_row)
        import_row = QHBoxLayout()
        import_btn = QPushButton(self.t.get("import_file", "Import"))
        import_btn.clicked.connect(self._import_profile_file)
        import_hint = QLabel(self.t.get("import_file_hint", ""))
        import_hint.setObjectName("muted")
        import_hint.setWordWrap(True)
        import_row.addWidget(import_btn)
        import_row.addWidget(import_hint, stretch=1)
        files.layout().addLayout(import_row)
        layout.addWidget(files)
        layout.addStretch(1)

    def _profile_class_label(self, character: str) -> str:
        key = "royal" if character == "prince" else character
        return self.t.get(key, character)

    def _selected_profile_name(self) -> str:
        rows = self.profile_table.selectionModel().selectedRows()
        if not rows:
            return ""
        item = self.profile_table.item(rows[0].row(), 0)
        return item.text() if item else ""

    def _reload_profile_table(self) -> None:
        self.profile_table.setRowCount(0)
        for name in list_profile_names():
            path = named_profile_path(name)
            character = ""
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    character = str(data.get("character") or "")
            except (OSError, json.JSONDecodeError):
                pass
            stamp = ""
            try:
                stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except OSError:
                pass
            row = self.profile_table.rowCount()
            self.profile_table.insertRow(row)
            self.profile_table.setItem(row, 0, QTableWidgetItem(name))
            self.profile_table.setItem(
                row, 1, QTableWidgetItem(self._profile_class_label(character))
            )
            self.profile_table.setItem(row, 2, QTableWidgetItem(stamp))
        self._show_selected_profile()

    def _show_selected_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            for value in self._profile_info.values():
                value.setText("-")
            self.profile_empty.setText(self.t.get("no_profile", "No profile selected"))
            return
        path = named_profile_path(name)
        character = language = active_map = ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                character = str(data.get("character") or "")
                language = str(data.get("language") or "")
                active_map = str(data.get("active_map") or "")
        except (OSError, json.JSONDecodeError):
            pass
        created = ""
        try:
            created = datetime.fromtimestamp(path.stat().st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
        except OSError:
            pass
        self._profile_info["name"].setText(name)
        self._profile_info["class"].setText(self._profile_class_label(character) or "-")
        self._profile_info["created"].setText(created or "-")
        self._profile_info["language"].setText(
            language_display_name(language, self.language) if language else "-"
        )
        self._profile_info["map"].setText(
            map_display_name(active_map, self.language) if active_map else "-"
        )
        self.profile_empty.setText("")

    def _save_profile_from_entry(self) -> None:
        name = self.profile_name_edit.text().strip()
        if not name:
            name, ok = QInputDialog.getText(
                self,
                self.t.get("profiles", "Profiles"),
                self.t.get("profile_name", "Profile name"),
            )
            if not ok or not name.strip():
                return
            name = name.strip()
        try:
            save_named_profile(name, self.profile)
        except Exception as exc:
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), str(exc))
            return
        self._reload_profile_table()

    def _load_selected_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        try:
            loaded = load_named_profile(name)
            self.profile.__dict__.update(loaded.__dict__)
            save_profile(self.profile)
            self.bridge.profile = self.profile
            self.bridge.coordinator.profile = self.profile
            self.bridge.rebind_hotkeys()
            self._load_hotkey_fields()
            self.refresh_hotbar_view()
            if self.on_profile_reloaded is not None:
                self.on_profile_reloaded()
            self.on_log(self.t.get("profile_loaded", "Profile loaded."))
        except Exception as exc:
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), str(exc))

    def _delete_selected_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            return
        confirm = QMessageBox.question(
            self,
            self.t.get("profiles", "Profiles"),
            self.t.get("confirm_delete_profile", "Delete {name}?").format(name=name),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_named_profile(name)
            self._reload_profile_table()
        except Exception as exc:
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), str(exc))

    def _export_selected_profile(self) -> None:
        name = self._selected_profile_name()
        if not name:
            names = list_profile_names()
            name, ok = QInputDialog.getText(
                self,
                self.t.get("profiles", "Profiles"),
                self.t.get("available_profiles", "Available: {names}").format(
                    names=", ".join(names) if names else "—"
                ),
            )
            if not ok or not name.strip():
                return
            name = name.strip()
        try:
            source = named_profile_path(name)
            if not source.is_file():
                raise FileNotFoundError(
                    self.t.get("profile_not_found", "Profile not found.")
                )
            destination, _ = QFileDialog.getSaveFileName(
                self,
                self.t.get("export_profile", "Export"),
                source.name,
                self.t.get("profile_files", "Profiles") + " (*.json)",
            )
            if destination:
                shutil.copy2(source, destination)
                QMessageBox.information(
                    self,
                    self.t.get("profiles", "Profiles"),
                    self.t.get("profile_exported", "Exported."),
                )
        except Exception as exc:
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), str(exc))

    def _import_profile_file(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get("import_profile", "Import"),
            "",
            self.t.get("profile_files", "Profiles") + " (*.json)",
        )
        if not source:
            return
        try:
            data = json.loads(Path(source).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(
                    self.t.get("invalid_profile_file", "Invalid profile file.")
                )
            imported = Profile.from_dict(data)
            suggested = Path(source).stem
            name, ok = QInputDialog.getText(
                self,
                self.t.get("profiles", "Profiles"),
                self.t.get("profile_name", "Profile name"),
                text=suggested,
            )
            if ok and name.strip():
                save_named_profile(name.strip(), imported)
                QMessageBox.information(
                    self,
                    self.t.get("profiles", "Profiles"),
                    self.t.get("profile_imported", "Imported."),
                )
                self._reload_profile_table()
        except Exception as exc:
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), str(exc))

    # --- Hotkeys ----------------------------------------------------------------

    def _build_hotkeys(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        settings = card(page, self.t.get("hotkey_settings", "Hotkey settings"))
        grid = QGridLayout()
        grid.addWidget(QLabel(self.t.get("hotkey_action", "Action")), 0, 0)
        grid.addWidget(QLabel(self.t.get("hotkey_key", "Key")), 0, 1)
        grid.addWidget(QLabel(self.t.get("hotkey_enabled", "On")), 0, 2)
        for row, (key, label_key) in enumerate(
            (("pause_resume", "pause_hotkey"), ("stop", "stop_hotkey")),
            start=1,
        ):
            grid.addWidget(QLabel(self.t.get(label_key, key)), row, 0)
            field = QLabel("")
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setMinimumWidth(100)
            field.setStyleSheet(
                f"border: 1px solid {tokens.BORDER}; padding: 4px 12px; "
                f"background: {tokens.SURFACE}; color: {tokens.ACCENT};"
            )
            field.setCursor(Qt.CursorShape.PointingHandCursor)
            field.mousePressEvent = lambda _e, action=key: self.edit_hotkeys()  # type: ignore[method-assign]
            self._hotkey_labels[key] = field
            grid.addWidget(field, row, 1)
            enabled = QCheckBox()
            enabled.setChecked(True)
            self._hotkey_enabled[key] = enabled
            grid.addWidget(enabled, row, 2)
        settings.layout().addLayout(grid)
        buttons = QHBoxLayout()
        save_btn = QPushButton(self.t.get("save_hotkeys", "Save hotkeys"))
        save_btn.clicked.connect(self.edit_hotkeys)
        reset_btn = QPushButton(self.t.get("reset_hotkeys", "Reset"))
        reset_btn.clicked.connect(self._reset_hotkeys)
        apply_btn = QPushButton(self.t.get("hotkey_apply", "Apply"))
        mark_accent(apply_btn)
        apply_btn.clicked.connect(self._apply_hotkey_fields)
        buttons.addWidget(save_btn)
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        settings.layout().addLayout(buttons)
        notes = QLabel(
            f"{self.t.get('hotkey_global_note', '')}  "
            f"{self.t.get('hotkey_duplicate_note', '')}"
        )
        notes.setWordWrap(True)
        notes.setObjectName("muted")
        settings.layout().addWidget(notes)
        howto = QLabel(self.t.get("hotkey_howto_body", ""))
        howto.setWordWrap(True)
        howto.setObjectName("muted")
        settings.layout().addWidget(howto)
        layout.addWidget(settings)
        layout.addStretch(1)

    def _load_hotkey_fields(self) -> None:
        current = dict(getattr(self.profile, "hotkeys", None) or DEFAULT_HOTKEYS)
        for key, label in self._hotkey_labels.items():
            bound = str(current.get(key) or "").strip()
            display = bound or str(DEFAULT_HOTKEYS.get(key, ""))
            label.setText(display.lower())
            enabled = self._hotkey_enabled.get(key)
            if enabled is not None:
                enabled.setChecked(bool(bound))

    def _reset_hotkeys(self) -> None:
        for key, label in self._hotkey_labels.items():
            label.setText(str(DEFAULT_HOTKEYS.get(key, "")).lower())
            enabled = self._hotkey_enabled.get(key)
            if enabled is not None:
                enabled.setChecked(True)

    def _apply_hotkey_fields(self) -> None:
        values: dict[str, str] = {}
        for key, label in self._hotkey_labels.items():
            enabled = self._hotkey_enabled.get(key)
            combo = label.text().strip().lower()
            if not combo:
                combo = str(DEFAULT_HOTKEYS.get(key, "")).lower()
            # Classic: unchecked Enabled clears the binding.
            values[key] = combo if enabled is None or enabled.isChecked() else ""
        active = [value for value in values.values() if value]
        if len(set(active)) < len(active):
            QMessageBox.warning(
                self,
                self.t.get("hotkeys", "Hotkeys"),
                self.t.get("hotkey_duplicate_note", "Duplicate hotkeys."),
            )
            return
        previous = dict(getattr(self.profile, "hotkeys", None) or DEFAULT_HOTKEYS)
        self.profile.hotkeys = values
        save_profile(self.profile)
        err = self.bridge.rebind_hotkeys()
        if err:
            self.profile.hotkeys = previous
            save_profile(self.profile)
            self.bridge.rebind_hotkeys()
            self._load_hotkey_fields()
            QMessageBox.warning(self, self.t.get("hotkeys", "Hotkeys"), str(err))
        else:
            self._load_hotkey_fields()
            self.on_log(self.t.get("hotkeys_saved", "Hotkeys saved."))

    def edit_hotkeys(self) -> None:
        from ui_qt.dialogs.hotkey_dialog import HotkeyEditorDialog

        try:
            self.bridge.coordinator.hotkeys.clear()
        except Exception:
            pass
        previous = dict(getattr(self.profile, "hotkeys", None) or DEFAULT_HOTKEYS)

        def on_save(values: dict[str, str]) -> str | None:
            try:
                self.profile.hotkeys = {
                    "pause_resume": values["pause_resume"],
                    "stop": values["stop"],
                }
                save_profile(self.profile)
                err = self.bridge.rebind_hotkeys()
                self._load_hotkey_fields()
                return err
            except Exception as exc:
                self.profile.hotkeys = previous
                self.bridge.rebind_hotkeys()
                return str(exc)

        dialog = HotkeyEditorDialog(
            self,
            strings=self.t,
            initial=previous,
            on_save=on_save,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            self.bridge.rebind_hotkeys()
        else:
            self._load_hotkey_fields()
