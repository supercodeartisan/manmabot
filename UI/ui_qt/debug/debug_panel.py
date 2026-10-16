"""Debug inspector panel bound to one BotController."""

from __future__ import annotations

import io
import threading
from typing import Callable

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from session.bot_controller import BotController, RunState
from session.field_watch import FieldWatch
from session.debug_snapshot import (
    STATUS_SECTIONS,
    columns_for_section,
    rows_for_section,
    section_text,
)
from ui_qt.debug.field_view import FieldView
from ui_qt.debug.party_monitor_window import PartyMonitorPanel
from ui_qt.theme import tokens


def _field_dots(snapshot: dict) -> list[tuple[str, float, float]]:
    """Monster and item dots in player-relative tiles. Players are omitted."""
    world = snapshot.get("world") if isinstance(snapshot.get("world"), dict) else {}
    dots: list[tuple[str, float, float]] = []
    for item in list(world.get("objects") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind not in ("monster", "item"):
            continue
        if int(item.get("missed") or 0) > 0:
            continue
        rx = item.get("rx")
        ry = item.get("ry")
        if rx is None or ry is None:
            continue
        if kind == "monster" and item.get("dead"):
            kind = "dead"
        elif kind == "monster" and item.get("bait"):
            kind = "bait"
        dots.append((kind, float(rx), float(ry)))
    return dots


def _field_terrain(snapshot: dict, radius: int) -> list[tuple[int, int, str]]:
    """Nav tiles around the live player cell. Empty when the pose is missing."""
    nav = snapshot.get("navigation") if isinstance(snapshot.get("navigation"), dict) else {}
    origin = nav.get("live_origin_xy") or nav.get("origin_xy")
    map_id = str(nav.get("display_map") or nav.get("live_pack") or "")
    if not map_id or not origin:
        return []
    from session.field_terrain import terrain_cells

    return terrain_cells(map_id, origin, radius)


def _fmt_cell(value: object) -> str:
    if value is None or value == "":
        return "—"
    return str(value)


class _PreviewBridge(QObject):
    imageReady = Signal(object, bool)  # QImage|None, failed
    navReady = Signal(int, object, bool)  # seq, QImage|None, failed


class DebugPanel(QWidget):
    def __init__(
        self,
        *,
        controller: BotController,
        get_logs: Callable[[], list[str]],
        t: dict[str, str],
        get_arming: Callable[[], bool] | None = None,
        note_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.get_logs = get_logs
        self.get_arming = get_arming or (lambda: False)
        self.t = t
        self._note_text = note_text
        self._section = STATUS_SECTIONS[0]
        self._previewing = False
        self._preview_busy = False
        self._nav_worker = None
        self._nav_seq = 0
        self._last_nav_stamp = None
        self._last_tree_stamp = None
        self._last_log_len = -1
        self._nav_zoom = 1.0
        self._nav_source: QPixmap | None = None
        self._last_header = None
        self._field_watch = FieldWatch(
            profile_of=lambda: self.controller._profile,
            idle=self._field_idle,
        )
        self._bridge = _PreviewBridge(self)
        self._bridge.imageReady.connect(self._on_preview_image)
        self._bridge.navReady.connect(self._on_nav_image)
        self._build()

    def _tr(self, key: str, fallback: str | None = None) -> str:
        return self.t.get(key, fallback or key)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        header = QHBoxLayout()
        self.state_dot = QLabel("●")
        self.state_label = QLabel("")
        self.state_label.setStyleSheet("font-weight: 600;")
        self.note_label = QLabel(self._note_text or self._tr("debug_same_run"))
        self.note_label.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        header.addWidget(self.state_dot)
        header.addWidget(self.state_label)
        header.addWidget(self.note_label, stretch=1)
        copy_btn = QPushButton(self._tr("debug_copy"))
        copy_btn.clicked.connect(self.copy)
        header.addWidget(copy_btn)
        root.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(self._tr("debug_status_list")))
        self.listbox = QListWidget()
        _section_fallback = {
            "party": "Party",
            "overview": "Overview",
            "decision": "Decision",
            "field_view": "Field view",
            "nav_show": "Navigation show",
            "decide_time": "Decision time",
        }
        for section in STATUS_SECTIONS:
            self.listbox.addItem(
                self._tr(
                    f"debug_{section}",
                    _section_fallback.get(section, section.replace("_", " ").title()),
                )
            )
        self.listbox.setCurrentRow(0)
        self.listbox.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self.listbox)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel(self._tr("debug_details")))
        self.stack = QStackedWidget()
        self.tree = QTableWidget(0, 2)
        self.tree.verticalHeader().setVisible(False)
        self.stack.addWidget(self.tree)  # 0
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.stack.addWidget(self.log_widget)  # 1
        self.preview_label = QLabel(self._tr("debug_preview_waiting"))
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("background: #111111; color: #d1d5db;")
        self.preview_label.setMinimumHeight(240)
        self.stack.addWidget(self.preview_label)  # 2
        self.field_view = FieldView()
        self.stack.addWidget(self.field_view)  # 3
        nav_page = QWidget()
        nav_outer = QVBoxLayout(nav_page)
        nav_outer.setContentsMargins(0, 0, 0, 0)
        nav_bar = QHBoxLayout()
        zoom_out = QPushButton("−")
        zoom_in = QPushButton("+")
        zoom_reset = QPushButton(self._tr("debug_nav_show_reset", "Reset"))
        zoom_out.setFixedWidth(32)
        zoom_in.setFixedWidth(32)
        zoom_out.clicked.connect(lambda: self._nav_zoom_by(0.8))
        zoom_in.clicked.connect(lambda: self._nav_zoom_by(1.25))
        zoom_reset.clicked.connect(self._nav_zoom_reset)
        self.nav_zoom_label = QLabel("100%")
        nav_bar.addWidget(zoom_out)
        nav_bar.addWidget(zoom_in)
        nav_bar.addWidget(zoom_reset)
        nav_bar.addWidget(self.nav_zoom_label)
        nav_bar.addWidget(
            QLabel(self._tr("debug_nav_show_hint", "Wheel: zoom · Drag: pan"))
        )
        nav_bar.addStretch(1)
        nav_outer.addLayout(nav_bar)
        nav_body = QHBoxLayout()
        self.nav_scroll = QScrollArea()
        self.nav_scroll.setWidgetResizable(False)
        self.nav_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nav_scroll.setStyleSheet("background: #111111;")
        self.nav_label = QLabel(self._tr("debug_preview_waiting"))
        self.nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.nav_label.setStyleSheet("background: #111111; color: #d1d5db;")
        self.nav_scroll.setWidget(self.nav_label)
        self.nav_scroll.viewport().installEventFilter(self)
        self.nav_decision = QTextEdit()
        self.nav_decision.setReadOnly(True)
        self.nav_decision.setMaximumWidth(320)
        nav_body.addWidget(self.nav_scroll, stretch=4)
        nav_body.addWidget(self.nav_decision, stretch=1)
        nav_outer.addLayout(nav_body, stretch=1)
        self.stack.addWidget(nav_page)  # 4
        self.tables = QTableWidget(0, 2)
        self.tables.setHorizontalHeaderLabels(
            [self._tr("debug_field"), self._tr("debug_value")]
        )
        self.tables.verticalHeader().setVisible(False)
        self.stack.addWidget(self.tables)  # 5
        self.party_panel = PartyMonitorPanel(t=self.t, show_headline=True)
        self.stack.addWidget(self.party_panel)  # 6
        self.empty_label = QLabel(self._tr("debug_idle"))
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        self.stack.addWidget(self.empty_label)  # 7
        right_layout.addWidget(self.stack, stretch=1)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 4)
        root.addWidget(split, stretch=1)
        self._configure_tree(self._section)

    def _set_previewing(self, on: bool) -> None:
        if on == self._previewing:
            return
        self._previewing = on
        if on:
            self.controller.add_preview_watcher()
        else:
            self.controller.remove_preview_watcher()

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(STATUS_SECTIONS):
            return
        section = STATUS_SECTIONS[row]
        if section == self._section:
            return
        self._section = section
        self._last_tree_stamp = None
        self._last_log_len = -1
        if section == "logs":
            self._set_previewing(False)
            self.stack.setCurrentWidget(self.log_widget)
        elif section == "preview":
            self._set_previewing(True)
            self.stack.setCurrentWidget(self.preview_label)
        elif section == "field_view":
            self._set_previewing(False)
            self.stack.setCurrentWidget(self.field_view)
        elif section == "nav_show":
            self._set_previewing(False)
            self._ensure_nav_worker()
            self.stack.setCurrentWidget(self.stack.widget(4))
        elif section == "tables":
            self._set_previewing(False)
            self.stack.setCurrentWidget(self.tables)
        elif section == "party":
            self._set_previewing(False)
            self.stack.setCurrentWidget(self.party_panel)
        else:
            self._set_previewing(False)
            self._configure_tree(section)
            self.stack.setCurrentWidget(self.tree)
        self._sync_field_watch()
        self.refresh(force=True)

    def _configure_tree(self, section: str) -> None:
        columns = columns_for_section(section)
        self.tree.setColumnCount(len(columns))
        self.tree.setHorizontalHeaderLabels(
            [self._tr(label_key) for _cid, label_key in columns]
        )

    def _ensure_nav_worker(self):
        if self._nav_worker is None:
            from session.nav_debug_view import NavShowRenderWorker

            self._nav_worker = NavShowRenderWorker()
        return self._nav_worker

    def refresh(self, *, force: bool = False) -> None:
        snapshot = self.controller.debug_snapshot()
        overview = dict(snapshot.get("overview") or {})
        if self.get_arming():
            overview["arming"] = True
            snapshot = {**snapshot, "overview": overview}
        state_name = str(overview.get("state") or self.controller.state.value)
        try:
            state = RunState(state_name)
        except ValueError:
            state = self.controller.state
        colors = {
            RunState.STOPPED: "#dc2626",
            RunState.RUNNING: "#16a34a",
            RunState.PAUSED: "#f59e0b",
        }
        reason = str(overview.get("reason") or "")
        note = str(overview.get("note") or "")
        if overview.get("arming"):
            label = self._tr("debug_arming")
        else:
            label = self._tr(state_name, state_name)
        if reason:
            label = f"{label} — {reason}"
        elif note:
            label = f"{label} — {note}"
        header = (state, label)
        if force or header != self._last_header:
            self._last_header = header
            self.state_dot.setStyleSheet(f"color: {colors.get(state, '#dc2626')};")
            self.state_label.setText(label)

        if self._section == "logs":
            lines = self.get_logs()
            length = len(lines)
            if force or length != self._last_log_len:
                self._last_log_len = length
                self.log_widget.setPlainText("\n".join(lines[-400:]))
            return
        if self._section == "preview":
            self._refresh_preview()
            return
        if self._section == "field_view":
            if self._field_idle():
                live = self._field_watch.latest() or {}
                snapshot = {
                    **snapshot,
                    "navigation": live.get("navigation") or {},
                    "world": live.get("world") or {"objects": []},
                }
            span = max(self.field_view.width(), self.field_view.height())
            radius = int(span / (2 * 14)) + 2
            cells = _field_terrain(snapshot, radius)
            self.field_view.set_terrain(cells)
            self.field_view.set_dots(_field_dots(snapshot))
            nav = snapshot.get("navigation") if isinstance(snapshot.get("navigation"), dict) else {}
            origin = nav.get("live_origin_xy") or nav.get("origin_xy")
            self.field_view.set_status(
                "" if origin else self._tr("debug_field_view_waiting")
            )
            return
        if self._section == "nav_show":
            text = section_text("navigation", snapshot, self.get_logs())
            stamp = (
                snapshot.get("updated_at"),
                overview.get("frame_id"),
                overview.get("note"),
            )
            if force or stamp != self._last_tree_stamp:
                self._last_tree_stamp = stamp
                self.nav_decision.setPlainText(text or self._tr("debug_no_data"))
            self._refresh_nav_show(snapshot)
            return
        if self._section == "tables":
            self._refresh_tables(snapshot, force=force)
            return
        if self._section == "party":
            try:
                party_snap = self.controller.party_monitor_snapshot()
            except Exception as exc:
                party_snap = {"probe_error": f"snapshot failed: {exc}"}
            # Belt-and-suspenders: always merge a fresh DLL probe into the panel.
            try:
                from session.party_probe import probe_party_live

                live = probe_party_live()
                party_snap = dict(party_snap or {})
                party_snap["dll_path"] = live.get("dll_path") or party_snap.get(
                    "dll_path", ""
                )
                party_snap["dll_loaded"] = bool(live.get("dll_loaded"))
                party_snap["probe_error"] = str(
                    live.get("error") or party_snap.get("probe_error") or ""
                )
                if isinstance(live.get("party"), dict):
                    party_snap["party"] = live["party"]
            except Exception as exc:
                party_snap = dict(party_snap or {})
                party_snap.setdefault("dll_loaded", False)
                party_snap["probe_error"] = str(exc)
            try:
                party_snap["profile_party_enabled"] = bool(
                    getattr(self.controller._profile, "party_member_enabled", False)
                )
            except Exception:
                pass
            self.party_panel.apply(party_snap)
            return

        stamp = (
            snapshot.get("updated_at"),
            overview.get("frame_id"),
            overview.get("note"),
            overview.get("state"),
            overview.get("reason"),
            self._section,
        )
        rows = rows_for_section(self._section, snapshot)
        if not rows:
            idle = not overview.get("worker_alive") and state is RunState.STOPPED
            self.empty_label.setText(
                self._tr("debug_idle") if idle else self._tr("debug_no_data")
            )
            self.stack.setCurrentWidget(self.empty_label)
            self._last_tree_stamp = stamp
            return
        if not force and stamp == self._last_tree_stamp:
            return
        self._last_tree_stamp = stamp
        if self.stack.currentWidget() is not self.tree:
            self.stack.setCurrentWidget(self.tree)
        self.tree.setRowCount(0)
        for row in rows:
            r = self.tree.rowCount()
            self.tree.insertRow(r)
            values = row if isinstance(row, (list, tuple)) else (row,)
            for c, value in enumerate(values):
                self.tree.setItem(r, c, QTableWidgetItem(_fmt_cell(value)))

    def _refresh_tables(self, snapshot: dict, *, force: bool = False) -> None:
        tables = dict(snapshot.get("tables") or {})
        stamp = (
            snapshot.get("updated_at"),
            len(tables.get("entities") or []),
            len(tables.get("inventory") or []),
            len(tables.get("hotbar") or []),
            len(tables.get("buffs") or []),
        )
        if not force and stamp == self._last_tree_stamp:
            return
        self._last_tree_stamp = stamp
        self.tables.setRowCount(0)
        for group, rows in tables.items():
            if not isinstance(rows, list):
                continue
            for row in rows[:80]:
                if not isinstance(row, dict):
                    continue
                r = self.tables.rowCount()
                self.tables.insertRow(r)
                self.tables.setItem(r, 0, QTableWidgetItem(f"{group}"))
                self.tables.setItem(
                    r,
                    1,
                    QTableWidgetItem(
                        ", ".join(f"{k}={_fmt_cell(v)}" for k, v in list(row.items())[:8])
                    ),
                )

    def _refresh_preview(self) -> None:
        if self._preview_busy:
            return
        data = self.controller.pop_preview_jpeg()
        if not data:
            return
        self._preview_busy = True

        def decode() -> None:
            image = None
            failed = False
            try:
                from PIL import Image

                decoded = Image.open(io.BytesIO(data)).convert("RGB")
                decoded.thumbnail((960, 720))
                buf = io.BytesIO()
                decoded.save(buf, format="PNG")
                qimg = QImage.fromData(buf.getvalue())
                image = qimg
            except Exception:
                failed = True
            self._bridge.imageReady.emit(image, failed)

        threading.Thread(target=decode, name="qt-debug-preview", daemon=True).start()

    def _on_preview_image(self, image, failed: bool) -> None:
        self._preview_busy = False
        if failed or image is None or image.isNull():
            self.preview_label.setText(self._tr("debug_preview_waiting"))
            return
        self.preview_label.setPixmap(QPixmap.fromImage(image))

    def _refresh_nav_show(self, snapshot: dict) -> None:
        from session.nav_debug_view import nav_show_content_stamp

        stamp = nav_show_content_stamp(snapshot)
        if stamp == self._last_nav_stamp:
            return
        self._nav_seq += 1
        seq = self._nav_seq
        worker = self._ensure_nav_worker()

        def on_done(done_seq: int, done_stamp, image, failed: bool) -> None:
            qimg = None
            if image is not None and not failed:
                try:
                    buf = io.BytesIO()
                    image.save(buf, format="PNG")
                    qimg = QImage.fromData(buf.getvalue())
                except Exception:
                    failed = True
            self._bridge.navReady.emit(done_seq, qimg, bool(failed))

        self._last_nav_stamp = stamp
        worker.submit(seq=seq, snapshot=snapshot, stamp=stamp, on_done=on_done)

    def _on_nav_image(self, seq: int, image, failed: bool) -> None:
        if seq != self._nav_seq:
            return
        if failed or image is None or image.isNull():
            self._nav_source = None
            self.nav_label.setPixmap(QPixmap())
            self.nav_label.setText(self._tr("debug_no_data"))
            self.nav_label.adjustSize()
            return
        self._nav_source = QPixmap.fromImage(image)
        self._nav_zoom_fit()
        self._apply_nav_zoom()

    def _nav_zoom_by(self, factor: float) -> None:
        self._nav_zoom = max(0.05, min(4.0, self._nav_zoom * float(factor)))
        self._apply_nav_zoom()

    def _nav_zoom_reset(self) -> None:
        self._nav_zoom_fit()
        self._apply_nav_zoom()

    def _nav_zoom_fit(self) -> None:
        if self._nav_source is None or self._nav_source.isNull():
            self._nav_zoom = 1.0
            return
        vw = max(1, self.nav_scroll.viewport().width())
        vh = max(1, self.nav_scroll.viewport().height())
        sw = max(1, self._nav_source.width())
        sh = max(1, self._nav_source.height())
        self._nav_zoom = max(0.05, min(vw / float(sw), vh / float(sh), 4.0))

    def _apply_nav_zoom(self) -> None:
        if self._nav_source is None or self._nav_source.isNull():
            return
        zoom = max(0.05, float(self._nav_zoom))
        dw = max(1, int(round(self._nav_source.width() * zoom)))
        dh = max(1, int(round(self._nav_source.height() * zoom)))
        scaled = self._nav_source.scaled(
            dw,
            dh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.nav_label.setText("")
        self.nav_label.setPixmap(scaled)
        self.nav_label.resize(scaled.size())
        self.nav_zoom_label.setText(f"{int(round(zoom * 100))}%")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.nav_scroll.viewport() and isinstance(event, QWheelEvent):
            if event.angleDelta().y() > 0:
                self._nav_zoom_by(1.25)
            elif event.angleDelta().y() < 0:
                self._nav_zoom_by(0.8)
            return True
        return super().eventFilter(obj, event)

    def copy(self) -> None:
        snapshot = self.controller.debug_snapshot()
        text = section_text(self._section, snapshot, self.get_logs())
        if not text:
            text = self._tr("debug_no_data")
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.note_label.setText(self._tr("debug_copied"))

    def _field_idle(self) -> bool:
        """True when the bot worker is not publishing a live snapshot."""
        if self.controller.state != RunState.STOPPED:
            return False
        thread = getattr(self.controller, "_thread", None)
        return thread is None or not thread.is_alive()

    def _sync_field_watch(self) -> None:
        if self._section == "field_view":
            self._field_watch.ensure_running()
        else:
            self._field_watch.stop()

    def shutdown(self) -> None:
        self._field_watch.stop()
        self.field_view.hide()
        self._set_previewing(False)
        worker = self._nav_worker
        self._nav_worker = None
        if worker is not None:
            try:
                worker.stop()
            except Exception:
                pass
