"""Qt map editor — farm rects and dungeon patrol points on real-map art."""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPolygonF,
    QShortcut,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QAbstractButton,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import route_point_display_name
from i18n.strings import ui_strings
from settings.map_previews import open_legacy_nav_preview, open_real_map_image
from session.paths import assert_userdata_write, ensure_userdata, manmabot_root
from session.probes import (
    farms_yaml_path,
    is_dungeon_map_id,
    list_patrol_entries,
    load_map_pack_safe,
    safe_yaml_path,
    writable_farms_yaml_path,
    writable_patrol_yaml_path,
    writable_safe_yaml_path,
)
from ui_qt.dialogs.mainland_region_overlay import (
    MainlandRegionOverlay,
    build_mainland_overlay,
    draw_visible_image,
)
from app._03_world.space.tile_world import (
    PackAxes,
    axes_from_pack,
    clamp_popup_top_left,
    parse_world_int,
    raw_map_id_from_pack,
)
from settings.farm_schedule import (
    DEFAULT_FARM_STAY_S,
    MAX_FARM_STAY_MIN,
    MIN_FARM_STAY_MIN,
    clamp_farm_stay_s,
    stay_minutes_from_s,
    stay_s_from_minutes,
)
from ui_qt.theme import tokens

Handle = Optional[str]
_HANDLE_PX = 8
_HANDLE_CURSORS = {
    "n": Qt.CursorShape.SizeVerCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "w": Qt.CursorShape.SizeHorCursor,
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
}
_ZOOM_MIN = 0.4
_ZOOM_MAX = 12.0
# Live character marker: expanding rings (period / count / outer radius px).
_LIVE_POSE_POLL_MS = 400
_LIVE_ANIM_MS = 50
_LIVE_RING_PERIOD_S = 1.35
_LIVE_RING_COUNT = 3
_LIVE_RING_MAX_R = 30.0


class MapCanvas(QWidget):
    def __init__(self, editor: "MapEditorWidget") -> None:
        super().__init__()
        self.editor = editor
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background: #e5e7eb;")

    def paintEvent(self, _event) -> None:
        self.editor.paint_canvas(self)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.editor.on_wheel(event)
        event.accept()

    def mousePressEvent(self, event) -> None:
        self.editor.on_mouse_press(event)

    def mouseMoveEvent(self, event) -> None:
        self.editor.on_mouse_move(event)

    def leaveEvent(self, event) -> None:
        self.editor._hover_tile = None
        self.editor._sync_map_readout()
        if (
            not self.editor._panning
            and self.editor._drag is None
            and self.editor._rect_anchor is None
        ):
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.editor.on_mouse_release(event)

    def sizeHint(self) -> QSize:
        # At least the viewport; grow with zoomed image so scrollbars appear.
        base = self.editor._base
        vp = self.editor._viewport_size()
        if base is None:
            return QSize(max(320, vp[0]), max(240, vp[1]))
        scale = max(0.05, float(getattr(self.editor, "_scale", 1.0)))
        return QSize(
            max(vp[0], int(base.width() * scale)),
            max(vp[1], int(base.height() * scale)),
        )


class _ChevronButton(QAbstractButton):
    """Small up/down mark, not a filled toolbar arrow."""

    def __init__(self, *, up: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._up = up
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            event.ignore()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#111827") if self.underMouse() else QColor("#4b5563")
        pen = QPen(color)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._up:
            pts = (QPointF(4, 10), QPointF(8, 5), QPointF(12, 10))
        else:
            pts = (QPointF(4, 6), QPointF(8, 11), QPointF(12, 6))
        painter.drawPolyline(QPolygonF(pts))
        painter.end()


class _OrderRow(QWidget):
    """List row: title on the left, order arrows on the right."""

    def __init__(
        self,
        editor: "MapEditorWidget",
        kind: str,
        idx: int,
        title: str,
        *,
        selected: bool,
        depth: int = 0,
        marker: str = "",
        toggle=None,
        expanded: bool | None = None,
        route: int | None = None,
    ) -> None:
        super().__init__()
        self._editor = editor
        self._kind = kind
        self._idx = idx
        self._route = route
        lay = QHBoxLayout(self)
        # The fold mark occupies the same left column on every top-level row.
        # Waypoints start to the right of that column and the title.
        fold_slot = 18
        if int(depth) == 0:
            lay.setContentsMargins(4, 1, 6, 1)
        else:
            lay.setContentsMargins(4 + fold_slot + 16, 1, 6, 1)
        lay.setSpacing(4)
        if toggle is not None:
            fold = QToolButton()
            fold.setObjectName("plan_fold")
            fold.setAutoRaise(True)
            fold.setFixedSize(fold_slot, fold_slot)
            fold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            fold.setCursor(Qt.CursorShape.PointingHandCursor)
            fold.setText("⌄" if expanded else "›")
            fold.setStyleSheet(
                "QToolButton#plan_fold {"
                " background: transparent; border: none; padding: 0px;"
                " color: #475569; font-size: 14px;"
                "}"
                "QToolButton#plan_fold:hover { background: transparent; color: #0f172a; }"
                "QToolButton#plan_fold:pressed { background: transparent; color: #64748b; }"
            )
            fold.clicked.connect(lambda: QTimer.singleShot(0, toggle))
            lay.addWidget(fold)
        elif int(depth) == 0:
            gap = QWidget()
            gap.setObjectName("plan_fold_gap")
            gap.setFixedSize(fold_slot, fold_slot)
            gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            gap.setStyleSheet(
                "QWidget#plan_fold_gap { background: transparent; border: none; }"
            )
            lay.addWidget(gap)
        shown = " ".join(part for part in (marker, title) if part)
        label = QLabel(shown)
        label.setObjectName("row_title")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(label, stretch=1)
        for up, delta in ((True, -1), (False, 1)):
            btn = _ChevronButton(up=up)
            if route is not None and kind == "patrol":
                btn.clicked.connect(
                    lambda _=False, d=delta, route_i=route: QTimer.singleShot(
                        0, lambda d=d, route_i=route_i: editor._nudge_waypoint(route_i, idx, d)
                    )
                )
            else:
                btn.clicked.connect(
                    lambda _=False, d=delta: QTimer.singleShot(
                        0, lambda d=d: editor._nudge_at(kind, idx, d)
                    )
                )
            lay.addWidget(btn)
        self.setMinimumHeight(24)
        if kind in ("patrol", "plan"):
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._open_patrol_menu)
        if selected:
            self.setAutoFillBackground(True)
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor("#dbeafe"))
            self.setPalette(pal)

    def _open_patrol_menu(self, pos) -> None:
        idx = self._idx
        kind = self._kind
        global_pos = self.mapToGlobal(pos)
        if kind == "plan":
            QTimer.singleShot(0, lambda: self._editor._plan_row_menu(idx, global_pos))
            return
        QTimer.singleShot(0, lambda: self._editor._patrol_row_menu(idx, global_pos))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            kind, idx, route = self._kind, self._idx, self._route
            if route is not None and kind == "patrol":
                QTimer.singleShot(0, lambda: self._editor._select_waypoint(route, idx))
            else:
                QTimer.singleShot(0, lambda: self._editor._select(kind, idx))
        super().mousePressEvent(event)


class _PointWorldEditor(QDialog):
    """Small world-coordinate editor. Its top-left sits on the map point."""

    def __init__(self, editor: "MapEditorWidget", farm: dict) -> None:
        super().__init__(editor)
        self._editor = editor
        self.farm = farm
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        axes = editor._display_axes()
        world_x, world_y = (0, 0)
        if axes is not None:
            world_x, world_y = axes.tile_to_world(int(farm["x"]), int(farm["y"]))
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)
        self.x_edit = QLineEdit(str(world_x))
        self.y_edit = QLineEdit(str(world_y))
        digit_width = self.fontMetrics().horizontalAdvance("00000") + 16
        for edit in (self.x_edit, self.y_edit):
            edit.setFixedWidth(digit_width)
            edit.setMaxLength(7)
        row.addWidget(QLabel("X"))
        row.addWidget(self.x_edit)
        row.addWidget(QLabel("Y"))
        row.addWidget(self.y_edit)
        store = QPushButton(editor.s.coord_store)
        cancel = QPushButton(editor.s.coord_cancel)
        store.setObjectName("coord_store")
        cancel.setObjectName("coord_cancel")
        store.clicked.connect(self._store)
        cancel.clicked.connect(self._cancel)
        store.setDefault(True)
        store.setAutoDefault(True)
        row.addWidget(store)
        row.addWidget(cancel)
        self.setStyleSheet(
            "QDialog { background: #ffffff; border: 1px solid #94a3b8; }"
        )
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._store)
        escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        escape.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        escape.activated.connect(self._cancel)
        self.x_edit.installEventFilter(self)
        self.y_edit.installEventFilter(self)
        self.x_edit.setFocus()
        self.x_edit.selectAll()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and watched in (self.x_edit, self.y_edit):
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._store()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._store()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _store(self) -> None:
        if self._editor._coord_popup is not self:
            return
        self._editor._apply_world_to_point(self.farm, self.x_edit.text(), self.y_edit.text())

    def _cancel(self) -> None:
        if self._editor._coord_popup is not self:
            return
        self._editor._close_coord_popup()


class MapEditorWidget(QWidget):
    def __init__(
        self,
        *,
        strings,
        can_edit: Callable[[], bool],
        on_changed: Callable[[], None] | None = None,
        on_done: Callable[[], None] | None = None,
        language: str = "en",
        area_kind: str = "farm",
        coord_load: Callable[[], dict | None] | None = None,
        coord_save: Callable[[dict], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = strings
        self._can_edit = can_edit
        self._area_kind = "safe" if str(area_kind) == "safe" else "farm"
        self._on_changed = on_changed or (lambda: None)
        self._on_done = on_done or (lambda: None)
        # When set, patrol/farm overlays load and save through the caller.
        # The shared map yaml is not written. None keeps the solo map files.
        self._coord_load = coord_load
        self._coord_save = coord_save
        self.language = str(language or "en")
        self.map_id = ""
        self._pack = None
        self._dungeon = False
        self._scale = 1.0
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._panning = False
        self._pan_start = (0, 0)
        self._pan_origin = [0.0, 0.0]
        self._base: QImage | None = None
        self._terrain = None
        self.farms: list[dict] = []
        self.patrol: list[tuple[int, int, str]] = []
        self._patrol_paths: list[list[tuple[int, int]]] = []
        # Party dungeon: routes and stationary points in list order.
        # Solo dungeon keeps ``patrol`` only. The active route's waypoint
        # list is ``self.patrol`` itself.
        self._plan: list[dict] = []
        self._active_route_id: str | None = None
        self._collapsed_plan_ids: set[str] = set()
        self._routine_minutes: int | None = None
        self.selected: tuple[str, int] | None = None
        self.tool = "select"
        self._drag: Handle = None
        self._drag_origin: dict | tuple | None = None
        self._rect_anchor: tuple[int, int] | None = None
        self._hover_tile: tuple[int, int] | None = None
        self._hover_move: tuple[int, int] | None = None
        self._region_overlay: MainlandRegionOverlay | None = None
        self._overlay_attempted = False
        self._defer_gen = 0
        self._image_loading = True
        self._live_nav: tuple[int, int] | None = None
        self._live_world: tuple[int, int] | None = None
        self._coord_popup: _PointWorldEditor | None = None
        self._live_timer: QTimer | None = None
        self._live_anim_timer: QTimer | None = None
        self._dirty = False
        self._filling_inspector = False
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(self._area_title())
        self.title_label = title
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        self.subtitle = QLabel(self.s.editor_hint_island)
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box, stretch=1)
        root.addLayout(header)

        tools = QHBoxLayout()
        tools.setSpacing(4)
        self._tool_buttons: dict[str, QPushButton] = {}
        patrol = QPushButton(self.s.place_patrol)
        patrol.clicked.connect(lambda: self._set_tool("patrol"))
        tools.addWidget(patrol)
        self._tool_buttons["patrol"] = patrol
        for key, label, handler in (
            ("clear", self.s.clear_all, self._clear_all),
            ("save", self.s.save_areas, self.save),
            ("reload", self.s.reload_areas, self._reload_from_disk),
            ("done", self.s.edit_done, self._done),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            tools.addWidget(btn)
            self._tool_buttons[key] = btn
        tools.addStretch(1)
        patrol_plus = QPushButton(self.s.tool_patrol_plus)
        patrol_plus.clicked.connect(self._on_patrol_plus)
        tools.addWidget(patrol_plus)
        self._tool_buttons["patrol_plus"] = patrol_plus
        area_btn = QPushButton(self._shape_label("area") + " +")
        point_btn = QPushButton(self._shape_label("point") + " +")
        area_btn.clicked.connect(lambda: self._set_tool("area"))
        point_btn.clicked.connect(lambda: self._set_tool("point"))
        tools.addWidget(area_btn)
        tools.addWidget(point_btn)
        self._tool_buttons["area"] = area_btn
        self._tool_buttons["point"] = point_btn
        zoom_out = QPushButton("−")
        zoom_in = QPushButton("+")
        zoom_out.setFixedSize(32, 28)
        zoom_in.setFixedSize(32, 28)
        zoom_out.clicked.connect(lambda: self._zoom_by(1 / 1.15))
        zoom_in.clicked.connect(lambda: self._zoom_by(1.15))
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setFixedHeight(28)
        self.zoom_label.setMinimumWidth(44)
        tools.addWidget(zoom_out)
        tools.addWidget(self.zoom_label)
        tools.addWidget(zoom_in)
        root.addLayout(tools)

        split = QSplitter(Qt.Orientation.Horizontal)
        side = QWidget()
        self._list_side = side
        side.setMinimumWidth(250)
        side_layout = QVBoxLayout(side)
        head = QHBoxLayout()
        self.list_title = QLabel(self._area_title())
        head.addWidget(self.list_title)
        self.list_count = QLabel("0")
        head.addWidget(self.list_count)
        head.addStretch(1)
        side_layout.addLayout(head)
        self.item_list = QListWidget()
        self.item_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.item_list.setMinimumWidth(230)
        self.item_list.currentRowChanged.connect(self._on_list_row)
        self.item_list.itemDoubleClicked.connect(self._on_list_double)
        self.item_list.viewport().installEventFilter(self)
        side_layout.addWidget(self.item_list, stretch=1)
        split.addWidget(side)

        canvas_widget = QWidget()
        canvas_host_w = QVBoxLayout(canvas_widget)
        canvas_host_w.setContentsMargins(0, 0, 0, 0)
        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = MapCanvas(self)
        self._canvas_scroll.setWidget(self.canvas)
        canvas_host_w.addWidget(self._canvas_scroll, stretch=1)
        from ui_qt.theme.fonts import body_font

        self.map_readout = QLabel("")
        self.map_readout.setFont(body_font(self.language, 13))
        self.map_readout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.map_readout.setStyleSheet(
            "color: #ffffff; background: #0f172a; padding: 5px 12px;"
        )
        self.map_readout.setMinimumHeight(30)
        canvas_host_w.addWidget(self.map_readout)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        # The hint is one long sentence. An unwrapped label's minimum width
        # grows the dialog after the map has already been fitted. Two lines
        # are reserved up front so wrapping does not shrink the map either.
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.status.setMinimumHeight(self.status.fontMetrics().lineSpacing() * 2)
        self.status.setStyleSheet(f"color: {tokens.TEXT_MUTED};")
        canvas_host_w.addWidget(self.status)
        split.addWidget(canvas_widget)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        split.setSizes([250, 750])
        root.addWidget(split, stretch=1)
        self._sync_tools()

    def _set_tool(self, tool: str) -> None:
        if not self._can_edit() and tool != "select":
            self.status.setText(self.s.editor_readonly)
            return
        self.tool = tool
        self._sync_tools()
        self.status.setText(self._hint())

    def _sync_tools(self) -> None:
        """Button visibility follows the editor kind, not the active tool.

        Party dungeon (``plan``): 경유점 + and 점 + stay visible together.
        Solo dungeon: the original 패트롤 배치 button, no 점 +.
        Field map: 구역 + and 점 +, no patrol button.
        ``self.tool`` only changes which of those buttons is highlighted.
        """
        patrol = self._tool_buttons.get("patrol")
        plan = self._dungeon_plan_mode()
        show_patrol = self._dungeon and not plan
        if patrol is not None:
            patrol.setVisible(show_patrol)
            patrol.setStyleSheet(
                f"background: {tokens.ACCENT}; color: white;"
                if show_patrol and self.tool == "patrol"
                else ""
            )
        patrol_plus = self._tool_buttons.get("patrol_plus")
        if patrol_plus is not None:
            patrol_plus.setVisible(plan)
            patrol_plus.setStyleSheet(
                f"background: {tokens.ACCENT}; color: white;"
                if plan and self.tool == "patrol"
                else ""
            )
        spot = self._spot_tools_active()
        points = self._point_tools_active()
        for key in ("area", "point"):
            button = self._tool_buttons.get(key)
            if button is None:
                continue
            visible = points if key == "point" else spot
            button.setVisible(visible)
            button.setStyleSheet(
                f"background: {tokens.ACCENT}; color: white;"
                if visible and self.tool == key
                else ""
            )
        if hasattr(self, "_list_side"):
            self._list_side.setMinimumWidth(360 if spot or points else 250)
        if hasattr(self, "list_title"):
            self.list_title.setText(self._area_title())
        if hasattr(self, "title_label"):
            self.title_label.setText(self._area_title())
        if hasattr(self, "subtitle"):
            self.subtitle.setText(self._subtitle_text())
        if self._dungeon_plan_mode():
            host = self.window()
            if host is not None and host is not self:
                try:
                    host.setWindowTitle(self.s.edit_dungeon_plan)
                except RuntimeError:
                    pass

    def _area_title(self) -> str:
        if self._dungeon_plan_mode():
            return self.s.edit_dungeon_plan
        if self._dungeon:
            return self.s.edit_patrol
        if self._area_kind == "safe":
            return self.s.edit_rest
        return self.s.edit_farms

    def _subtitle_text(self) -> str:
        """Muted guide under the title. Solo and rest editors keep their own text."""
        if self._dungeon_plan_mode():
            return self.s.editor_hint_dungeon_plan
        if self._spot_tools_active():
            return self.s.editor_hint_field
        if self._dungeon:
            return self.s.editor_hint_dungeon
        return self.s.editor_hint_island

    def _hint(self) -> str:
        if self._dungeon_plan_mode() or self._spot_tools_active():
            return self._subtitle_text()
        base = (
            self.s.editor_hint_dungeon if self._dungeon else self.s.editor_hint_island
        )
        nav = getattr(self.s, "editor_nav_hint", "") or ""
        return f"{base}  {nav}".strip() if nav else base

    def _load_terrain_for_editor(self):
        """Prefer offline nav_prebuild (fast); fall back to nav.png."""
        from app._03_world.space.terrain_map import TerrainMap
        from app._04_decision.nav_prebuild import (
            load_nav_prebuild,
            prebuild_dir_for_pack,
            prebuild_is_complete,
        )

        pack = self._pack
        if pack is None:
            return None
        pre_dir = prebuild_dir_for_pack(pack.root)
        if prebuild_is_complete(pre_dir):
            try:
                terrain, _coarse, _graph, _meta = load_nav_prebuild(
                    pre_dir,
                    source_path=pack.terrain_path,
                    clearance_tiles=pack.clearance_tiles,
                    wall_penalty=pack.wall_penalty,
                )
                from app._04_decision.nav_config import _seal_silver_knight_inn

                _seal_silver_knight_inn(terrain, str(getattr(pack, "id", "") or ""))
                return terrain
            except Exception:
                pass
        terrain = TerrainMap.from_png(
            pack.terrain_path,
            pixel_scale=max(1, int(pack.pixel_scale)),
        )
        from app._04_decision.nav_config import _seal_silver_knight_inn

        _seal_silver_knight_inn(terrain, str(getattr(pack, "id", "") or ""))
        return terrain

    def load_map(self, map_id: str, *, dungeon: bool | None = None) -> None:
        self._close_coord_popup()
        self.map_id = str(map_id or "")
        self._pack = load_map_pack_safe(self.map_id)
        self.selected = None
        self.farms = []
        self.patrol = []
        self._patrol_paths = []
        self._plan = []
        self._active_route_id = None
        self._collapsed_plan_ids = set()
        self._routine_minutes = None
        self._live_nav = None
        self._live_world = None
        self._terrain = None
        self._base = None
        self._region_overlay = None
        self._overlay_attempted = False
        self._hover_tile = None
        self._defer_gen += 1
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        if dungeon is None:
            self._dungeon = is_dungeon_map_id(self.map_id)
        else:
            self._dungeon = bool(dungeon)
        self.subtitle.setText(self._subtitle_text())
        if self._dungeon:
            self.tool = "patrol"
        elif self._spot_tools_active():
            self.tool = "area"
        else:
            self.tool = "select"
        self._dirty = False
        self._sync_tools()
        if self._pack is None:
            self._image_loading = False
            self.status.setText(self.s.map_missing_short)
            self._refresh_list()
            self._fill_inspector()
            self._sync_canvas_size()
            self._sync_map_readout()
            self.canvas.update()
            return
        try:
            pil = open_legacy_nav_preview(self._pack)
        except Exception:
            pil = None
        if pil is None:
            try:
                pil = open_real_map_image(self.map_id)
            except Exception:
                pil = None
        if pil is None and self._pack is not None:
            try:
                from PIL import Image

                pil = Image.open(self._pack.terrain_path).convert("RGBA")
            except Exception:
                pil = None
        if pil is not None:
            try:
                rgba = pil.convert("RGBA")
                data = bytes(rgba.tobytes("raw", "RGBA"))
                image = QImage(
                    data,
                    rgba.width,
                    rgba.height,
                    rgba.width * 4,
                    QImage.Format.Format_RGBA8888,
                )
                self._base = image.copy()
            except Exception:
                self._base = None
        else:
            self.status.setText(self.s.map_missing_short)
        bound = self._bound_coords()
        if self._dungeon_plan_mode():
            self._apply_loaded_plan(bound)
        elif not self._dungeon:
            try:
                if bound is not None:
                    self.farms = self._farms_from_bound(bound)
                else:
                    self._load_farms()
            except Exception:
                self.farms = []
            self.patrol = []
        elif bound is not None:
            self.patrol = self._patrol_from_bound(bound)
        else:
            self.patrol = list_patrol_entries(self.map_id)
        self._image_loading = False
        self.status.setText(
            self.s.map_missing_short if self._base is None else self._hint()
        )
        self._refresh_list()
        self._fill_inspector()
        # Settle the hint's wrapped height before fitting, so the first
        # paint is already the final viewport.
        host = self.window()
        if host is not None and host.layout() is not None:
            host.layout().activate()
        self._fit()
        self._sync_canvas_size()
        self._sync_map_readout()
        self.canvas.update()
        # Draw now, before terrain loading blocks the UI thread again.
        self.canvas.repaint()
        gen = self._defer_gen
        QTimer.singleShot(0, self, lambda g=gen: self._load_terrain_after_paint(g))

    def _load_terrain_after_paint(self, gen: int) -> None:
        if gen != self._defer_gen:
            return
        try:
            self._terrain = self._load_terrain_for_editor()
        except Exception:
            self._terrain = None
        try:
            self._recompute_patrol_paths()
        except Exception:
            self._patrol_paths = []
        self.canvas.update()

    def _ensure_region_overlay(self) -> None:
        """Mainland hover names. Built once, on the first mouse move."""
        if (
            self._overlay_attempted
            or self._dungeon
            or self._base is None
            or self._pack is None
        ):
            return
        self._overlay_attempted = True
        try:
            self._region_overlay = build_mainland_overlay(
                self._pack, language=self.language
            )
        except Exception:
            self._region_overlay = None

    def _recompute_patrol_paths(self) -> None:
        self._patrol_paths = []
        if not self._dungeon or self._terrain is None or len(self.patrol) < 2:
            return
        try:
            from app._04_decision.pathfinding import find_path
        except Exception:
            return
        try:
            for i in range(len(self.patrol) - 1):
                a = self.patrol[i][:2]
                b = self.patrol[i + 1][:2]
                self._patrol_paths.append(find_path(self._terrain, a, b))
            a = self.patrol[-1][:2]
            b = self.patrol[0][:2]
            self._patrol_paths.append(find_path(self._terrain, a, b))
        except Exception:
            self._patrol_paths = []

    def _bound_coords(self) -> dict | None:
        """Party document, when this editor was opened for a party routine.

        ``None`` means the shared map yaml (solo, or a party row not copied yet).
        """
        if self._coord_load is None:
            return None
        try:
            loaded = self._coord_load()
        except Exception:
            return None
        return loaded if isinstance(loaded, dict) else None

    def _shape_label(self, kind: str) -> str:
        """Display word only. Saved shape stays area or point."""
        if self.language == "zh":
            return "区域" if kind == "area" else "点"
        if self.language == "en":
            return "Area" if kind == "area" else "Point"
        return "구역" if kind == "area" else "점"

    def _point_tools_active(self) -> bool:
        """Party hunt points. Field maps and dungeon maps both use this.

        Solo leaves ``coord_save`` unset, so a solo dungeon stays on patrol.
        """
        return self._coord_save is not None and self._area_kind == "farm"

    def _spot_tools_active(self) -> bool:
        """Party field hunt editor: rectangles and stake points."""
        return self._point_tools_active() and not self._dungeon

    def _dungeon_plan_mode(self) -> bool:
        """Party dungeon: patrol routes and stationary points together.

        Solo dungeons leave ``coord_save`` unset and keep the single patrol list.
        """
        return self._dungeon and self._point_tools_active()

    def _active_route(self) -> dict | None:
        for entry in self._plan:
            if entry.get("type") == "patrol" and entry.get("waypoints") is self.patrol:
                return entry
        for entry in self._plan:
            if entry.get("type") == "patrol" and entry.get("id") == self._active_route_id:
                self.patrol = entry["waypoints"]
                return entry
        return None

    def _next_plan_id(self, prefix: str) -> str:
        taken = {str(entry.get("id") or "") for entry in self._plan}
        number = 1
        while f"{prefix}_{number}" in taken:
            number += 1
        return f"{prefix}_{number}"

    def _sync_point_farms(self) -> None:
        self.farms = [entry for entry in self._plan if entry.get("type") == "point"]

    def _routine_default_minutes(self) -> int:
        if self._routine_minutes is not None:
            return stay_minutes_from_s(clamp_farm_stay_s(int(self._routine_minutes) * 60))
        return stay_minutes_from_s(DEFAULT_FARM_STAY_S)

    def _route_minutes(self, route: dict) -> int:
        if "duration_s" in route:
            return stay_minutes_from_s(clamp_farm_stay_s(route.get("duration_s")))
        return self._routine_default_minutes()

    def _on_patrol_plus(self) -> None:
        """Waypoint tool. Another press adds to the one patrol, never a second route."""
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return
        self._set_tool("patrol")
        if not self._dungeon_plan_mode():
            return
        routes = [entry for entry in self._plan if entry.get("type") == "patrol"]
        if not routes:
            self._begin_patrol_route()
            return
        active = self._active_route()
        target = active if active is not None else routes[0]
        self._collapsed_plan_ids.discard(str(target.get("id") or ""))
        self._use_route(target)
        self._focus_plan(self._plan.index(target))

    def _begin_patrol_route(self) -> dict:
        route = {
            "type": "patrol",
            "id": self._next_plan_id("patrol"),
            "waypoints": [],
        }
        self._plan.append(route)
        self._active_route_id = route["id"]
        self.patrol = route["waypoints"]
        self._recompute_patrol_paths()
        self._mark_dirty()
        self._select("plan", len(self._plan) - 1)
        return route

    def _use_route(self, route: dict) -> None:
        if route.get("waypoints") is self.patrol:
            self._active_route_id = str(route.get("id") or "")
            return
        self.patrol = route["waypoints"]
        self._active_route_id = str(route.get("id") or "")
        self._recompute_patrol_paths()

    def _focus_plan(self, plan_index: int) -> None:
        if not (0 <= plan_index < len(self._plan)):
            return
        entry = self._plan[plan_index]
        if entry.get("type") == "patrol":
            self._use_route(entry)
        self._select("plan", plan_index)

    def _apply_loaded_plan(self, bound: dict | None) -> None:
        from settings.party_routine import dungeon_plan_from_document

        self._routine_minutes = None
        if isinstance(bound, dict) and bound.get("routine_minutes") is not None:
            try:
                self._routine_minutes = int(bound["routine_minutes"])
            except (TypeError, ValueError):
                self._routine_minutes = None
        source = bound if isinstance(bound, dict) else {"patrol": []}
        if bound is None:
            source = {
                "patrol": [
                    {"x": int(x), "y": int(y), "name": str(name)}
                    for x, y, name in list_patrol_entries(self.map_id)
                ]
            }
        self._plan = []
        self.patrol = []
        self._active_route_id = None
        self._collapsed_plan_ids = set()
        for item in dungeon_plan_from_document(source):
            if item.get("type") == "patrol":
                waypoints = [
                    (int(point["x"]), int(point["y"]), str(point.get("name") or ""))
                    for point in item.get("waypoints") or []
                    if isinstance(point, dict)
                ]
                route = {
                    "type": "patrol",
                    "id": str(item.get("id") or self._next_plan_id("patrol")),
                    "waypoints": waypoints,
                }
                if "duration_s" in item:
                    route["duration_s"] = item["duration_s"]
                if "game_map_id" in item:
                    route["game_map_id"] = item["game_map_id"]
                if "pack_id" in item:
                    route["pack_id"] = item["pack_id"]
                self._plan.append(route)
                if self._active_route_id is None:
                    self._active_route_id = route["id"]
                    self.patrol = route["waypoints"]
                continue
            point = {
                "type": "point",
                "shape": "point",
                "id": str(item.get("id") or self._next_plan_id("point")),
                "name": str(item.get("name") or item.get("id") or ""),
                "region": "",
                "x": int(item["x"]),
                "y": int(item["y"]),
            }
            if "stay_s" in item:
                point["stay_s"] = item["stay_s"]
            if "game_map_id" in item:
                point["game_map_id"] = item["game_map_id"]
            if "pack_id" in item:
                point["pack_id"] = item["pack_id"]
            self._plan.append(point)
        self._sync_point_farms()

    def _plan_identity(self, entry: dict) -> dict:
        """Pack folder plus this folder's raw_map. Never the folder name as a map id."""
        record = dict(entry)
        pack_id = str(self.map_id or getattr(self._pack, "id", "") or "").strip()
        if pack_id:
            record["pack_id"] = pack_id
        game_id = raw_map_id_from_pack(self._pack)
        if game_id is None and "game_map_id" in entry:
            try:
                stored = int(entry["game_map_id"])
            except (TypeError, ValueError):
                stored = None
            if stored is not None and not isinstance(entry.get("game_map_id"), bool):
                game_id = stored
        if game_id is not None:
            record["game_map_id"] = game_id
        else:
            record.pop("game_map_id", None)
        return record

    def _dungeon_save_payload(self) -> dict:
        from settings.party_routine import dungeon_plan_extends_legacy

        routes_and_points: list[dict] = []
        for entry in self._plan:
            if entry.get("type") == "patrol":
                item: dict = {
                    "type": "patrol",
                    "id": str(entry.get("id") or ""),
                    "waypoints": [
                        {"x": int(x), "y": int(y), "name": str(name)}
                        for x, y, name in entry.get("waypoints") or []
                    ],
                }
                if "duration_s" in entry:
                    item["duration_s"] = clamp_farm_stay_s(entry.get("duration_s"))
                routes_and_points.append(self._plan_identity(item))
                continue
            if entry.get("type") != "point":
                continue
            item = {
                "type": "point",
                "id": str(entry.get("id") or ""),
                "name": str(entry.get("name") or entry.get("id") or ""),
                "x": int(entry["x"]),
                "y": int(entry["y"]),
            }
            if "stay_s" in entry:
                item["stay_s"] = clamp_farm_stay_s(entry.get("stay_s"))
            routes_and_points.append(self._plan_identity(item))
        first = next(
            (item for item in routes_and_points if item.get("type") == "patrol"),
            None,
        )
        legacy = list(first.get("waypoints") or []) if first is not None else []
        payload: dict = {"areas": [], "patrol": legacy}
        if dungeon_plan_extends_legacy(routes_and_points):
            payload["dungeon_plan"] = routes_and_points
        return payload

    def _is_point(self, farm: dict) -> bool:
        return str(farm.get("shape") or "") == "point"

    def _farms_from_bound(self, bound: dict) -> list[dict]:
        farms: list[dict] = []
        for i, item in enumerate(bound.get("areas") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"area_{i + 1}")
            region = str(item.get("region") or "")
            shape = str(item.get("shape") or "area").strip().lower()
            try:
                if shape == "point":
                    farms.append(
                        {
                            "name": name,
                            "shape": "point",
                            "region": region,
                            "x": int(item["x"] if "x" in item else item["x0"]),
                            "y": int(item["y"] if "y" in item else item["y0"]),
                        }
                    )
                else:
                    farms.append(
                        {
                            "name": name,
                            "shape": "area",
                            "region": region,
                            "x0": int(item["x0"]),
                            "y0": int(item["y0"]),
                            "x1": int(item["x1"]),
                            "y1": int(item["y1"]),
                        }
                    )
            except (KeyError, TypeError, ValueError):
                continue
        return farms

    def _patrol_from_bound(self, bound: dict) -> list[tuple[int, int, str]]:
        points: list[tuple[int, int, str]] = []
        for item in bound.get("patrol") or []:
            if not isinstance(item, dict):
                continue
            try:
                points.append(
                    (int(item["x"]), int(item["y"]), str(item.get("name") or ""))
                )
            except (KeyError, TypeError, ValueError):
                continue
        return points

    def _points_from_patrol(self, raw) -> list[dict]:
        """Dungeon hunt points kept as the same point marks the field editor uses."""
        farms: list[dict] = []
        if not isinstance(raw, list):
            return farms
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            try:
                x = int(item["x"])
                y = int(item["y"])
            except (KeyError, TypeError, ValueError):
                continue
            farm: dict = {
                "shape": "point",
                "name": str(item.get("name") or f"point_{index + 1}"),
                "region": "",
                "x": x,
                "y": y,
            }
            if "stay_s" in item:
                farm["stay_s"] = clamp_farm_stay_s(item.get("stay_s"))
            if "game_map_id" in item:
                try:
                    game_id = int(item["game_map_id"])
                except (TypeError, ValueError):
                    game_id = None
                if game_id is not None and not isinstance(item["game_map_id"], bool):
                    farm["game_map_id"] = game_id
            farms.append(farm)
        return farms

    def _patrol_record(self, farm: dict) -> dict:
        """One dungeon point in the party patrol list.

        ``x``/``y`` stay nav tiles. ``game_map_id`` is this folder's ``raw_map``.
        ``pack_id`` is the folder the editor opened. A missing ``stay_s`` is
        left missing so an untouched legacy point is not rewritten.
        """
        record: dict = {
            "x": int(farm["x"]),
            "y": int(farm["y"]),
            "name": str(farm.get("name") or ""),
        }
        pack_id = str(self.map_id or getattr(self._pack, "id", "") or "").strip()
        if pack_id:
            record["pack_id"] = pack_id
        if "stay_s" in farm:
            record["stay_s"] = clamp_farm_stay_s(farm.get("stay_s"))
        game_id = raw_map_id_from_pack(self._pack)
        if game_id is None and "game_map_id" in farm:
            try:
                stored = int(farm["game_map_id"])
            except (TypeError, ValueError):
                stored = None
            if stored is not None and not isinstance(farm.get("game_map_id"), bool):
                game_id = stored
        if game_id is not None:
            record["game_map_id"] = game_id
        return record

    def _save_coord_document(self) -> bool:
        """Write overlays to the party routine document. Does not touch map yaml."""
        if self._coord_save is None:
            return False
        try:
            if self._dungeon_plan_mode():
                payload = self._dungeon_save_payload()
                areas = payload["areas"]
                patrol = payload["patrol"]
                extra = (
                    {"dungeon_plan": payload["dungeon_plan"]}
                    if "dungeon_plan" in payload
                    else {}
                )
            else:
                extra = {}
                areas = []
                for farm in self.farms:
                    if farm.get("_preview"):
                        continue
                    name = str(farm.get("name") or "").strip() or f"area_{len(areas) + 1}"
                    region = str(farm.get("region") or "")
                    if self._is_point(farm):
                        areas.append(
                            {
                                "name": name,
                                "shape": "point",
                                "region": region,
                                "x": int(farm["x"]),
                                "y": int(farm["y"]),
                            }
                        )
                    else:
                        areas.append(
                            {
                                "name": name,
                                "shape": "area",
                                "region": region,
                                "x0": int(farm["x0"]),
                                "y0": int(farm["y0"]),
                                "x1": int(farm["x1"]),
                                "y1": int(farm["y1"]),
                            }
                        )
                patrol = [
                    {"x": int(x), "y": int(y), "name": str(name)}
                    for x, y, name in self.patrol
                ]
            saved = {"areas": areas, "patrol": patrol}
            saved.update(extra)
            self._coord_save(saved)
        except Exception as exc:
            QMessageBox.warning(self, self.s.tab_farms, str(exc))
            self.status.setText(str(exc))
            return False
        self._dirty = False
        if self._dungeon:
            self.status.setText(self.s.saved_patrol)
        elif self._area_kind == "safe":
            self.status.setText(self.s.saved_rest)
        else:
            self.status.setText(self.s.saved_areas)
        self._on_changed()
        return True

    def _load_farms(self) -> None:
        import yaml

        path = (
            safe_yaml_path(self.map_id)
            if self._area_kind == "safe"
            else farms_yaml_path(self.map_id)
        )
        self.farms = []
        if path is None or not path.is_file():
            return
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        areas = doc.get("areas") or doc.get("safe_areas") or doc.get("farm_areas") or []
        region = (self._pack.default_region if self._pack else "") or ""
        for i, item in enumerate(areas):
            if not isinstance(item, dict):
                continue
            try:
                self.farms.append(
                    {
                        "name": str(item.get("name") or f"area_{i + 1}"),
                        "region": str(item.get("region") or region),
                        "x0": int(item["x0"]),
                        "y0": int(item["y0"]),
                        "x1": int(item["x1"]),
                        "y1": int(item["y1"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

    def save(self) -> bool:
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return False
        if self._pack is None:
            return False
        if self._coord_save is not None:
            return self._save_coord_document()
        try:
            ensure_userdata()
            root = manmabot_root()
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from app._04_decision.farm_area import FarmRect, save_farm_areas_yaml
            from app._04_decision.patrol import save_patrol_waypoints_yaml

            if self._dungeon:
                pts = [(x, y) for x, y, _n in self.patrol]
                names = [n for _x, _y, n in self.patrol]
                path = assert_userdata_write(writable_patrol_yaml_path(self.map_id))
                save_patrol_waypoints_yaml(path, pts, names)
                self.status.setText(self.s.saved_patrol)
            else:
                rects = [
                    FarmRect(
                        x0=f["x0"],
                        y0=f["y0"],
                        x1=f["x1"],
                        y1=f["y1"],
                        name=f["name"],
                        region=f["region"],
                    )
                    for f in self.farms
                    if not f.get("_preview")
                ]
                if self._area_kind == "safe":
                    areas_path = assert_userdata_write(writable_safe_yaml_path(self.map_id))
                    saved_text = self.s.saved_rest
                else:
                    areas_path = assert_userdata_write(writable_farms_yaml_path(self.map_id))
                    saved_text = self.s.saved_areas
                save_farm_areas_yaml(
                    areas_path, rects, default_region=self._pack.default_region
                )
                self.status.setText(saved_text)
            self._dirty = False
            self._on_changed()
            return True
        except Exception as exc:
            QMessageBox.warning(self, self.s.tab_farms, str(exc))
            self.status.setText(str(exc))
            return False

    def _done(self) -> None:
        if self._dirty and self._can_edit():
            if not self.save():
                return
        self._on_done()

    def _reload_from_disk(self) -> None:
        if not self._can_edit():
            return
        if self._dirty and QMessageBox.question(
            self, self.s.tab_farms, self.s.confirm_reload
        ) != QMessageBox.StandardButton.Yes:
            return
        self.load_map(self.map_id, dungeon=self._dungeon)

    def _pixel_scale(self) -> int:
        if self._pack is None:
            return 4
        return max(1, int(self._pack.pixel_scale))

    def _map_limits(self) -> tuple[int, int]:
        if self._terrain is not None:
            return self._terrain.width - 1, self._terrain.height - 1
        if self._base is not None:
            ps = self._pixel_scale()
            return max(0, self._base.width() // ps - 1), max(
                0, self._base.height() // ps - 1
            )
        return 9999, 9999

    def _clamp_tile(self, tx: int, ty: int) -> tuple[int, int]:
        mx, my = self._map_limits()
        return max(0, min(mx, tx)), max(0, min(my, ty))

    def _viewport_size(self) -> tuple[int, int]:
        try:
            vp = self._canvas_scroll.viewport()
            return max(int(vp.width()), 40), max(int(vp.height()), 40)
        except Exception:
            return 40, 40

    def _fit_scale(self) -> float:
        """Image→viewport fit at zoom=1 (independent of current canvas size)."""
        if self._base is None:
            return 1.0
        cw, ch = self._viewport_size()
        iw, ih = max(1, self._base.width()), max(1, self._base.height())
        return max(0.05, min(cw / iw, ch / ih))

    def _fit(self) -> None:
        if self._base is None:
            return
        self._scale = max(0.05, self._fit_scale() * self._zoom)

    def _image_origin(self) -> tuple[float, float]:
        """Top-left of the scaled image inside the canvas (centered + pan)."""
        if self._base is None:
            return float(self._pan[0]), float(self._pan[1])
        iw, ih = self._base.width(), self._base.height()
        dw = max(1, int(iw * self._scale))
        dh = max(1, int(ih * self._scale))
        cw = max(self.canvas.width(), dw)
        ch = max(self.canvas.height(), dh)
        return (cw - dw) / 2.0 + self._pan[0], (ch - dh) / 2.0 + self._pan[1]

    def _tile_to_canvas(self, tx: float, ty: float) -> tuple[float, float]:
        ps = self._pixel_scale()
        ox, oy = self._image_origin()
        return tx * ps * self._scale + ox, ty * ps * self._scale + oy

    def _canvas_to_tile(self, cx: float, cy: float) -> tuple[int, int]:
        ps = self._pixel_scale()
        scale = max(self._scale * ps, 1e-6)
        ox, oy = self._image_origin()
        tx = int((cx - ox) / scale)
        ty = int((cy - oy) / scale)
        return self._clamp_tile(tx, ty)

    def paint_canvas(self, widget: MapCanvas) -> None:
        painter = QPainter(widget)
        painter.fillRect(widget.rect(), QColor("#e5e7eb"))
        if self._base is None:
            painter.setPen(QColor("#888888"))
            placeholder = (
                self.s.map_loading_short
                if self._image_loading
                else self.s.map_missing_short
            )
            painter.drawText(10, 20, placeholder)
            return
        self._fit()
        ox, oy = self._image_origin()
        draw_visible_image(
            painter, self._base, ox, oy, self._scale, widget.width(), widget.height()
        )
        if not self._dungeon or self._point_tools_active():
            visible = [
                i
                for i, farm in enumerate(self.farms)
                if not farm.get("_preview")
            ]
            order_of = {index: n for n, index in enumerate(visible, start=1)}
            if not self._dungeon:
                for i, f in enumerate(self.farms):
                    if self._is_point(f):
                        continue
                    x0, y0 = self._tile_to_canvas(f["x0"], f["y0"])
                    x1, y1 = self._tile_to_canvas(f["x1"] + 1, f["y1"] + 1)
                    selected = self.selected == ("farm", i)
                    preview = bool(f.get("_preview"))
                    outline = QColor(202, 138, 4) if preview else QColor("#dc2626")
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(outline, 2))
                    painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                    if not preview:
                        painter.setPen(outline)
                        label = (
                            f"{self._shape_label('area')} {order_of.get(i, '')}"
                            if self._spot_tools_active()
                            else route_point_display_name(str(f["name"]), self.language)
                        )
                        painter.drawText(int(x0 + 4), int(max(12, y0 - 4)), label)
                    if selected:
                        for hx, hy in self._handle_points(f).values():
                            painter.setBrush(QColor("white"))
                            painter.setPen(QPen(QColor("#dc2626"), 2))
                            painter.drawEllipse(QPointF(hx, hy), 5, 5)
            for i, f in enumerate(self.farms):
                if not self._is_point(f):
                    continue
                cx, cy = self._tile_to_canvas(int(f["x"]) + 0.5, int(f["y"]) + 0.5)
                selected = self.selected == ("point", i)
                painter.setPen(QPen(QColor("#1d4ed8"), 2))
                painter.setBrush(QColor("#2563eb") if selected else QColor("#1d4ed8"))
                painter.drawEllipse(QPointF(cx, cy), 6 if selected else 4, 6 if selected else 4)
                painter.setPen(QColor("#1f2937"))
                painter.drawText(
                    int(cx + 8),
                    int(cy - 8),
                    f"{self._shape_label('point')} {order_of.get(i, '')}",
                )
        if self._dungeon_plan_mode():
            active = self._active_route()
            for entry in self._plan:
                if entry.get("type") != "patrol" or entry is active:
                    continue
                waypoints = entry.get("waypoints") or []
                if len(waypoints) >= 2:
                    painter.setPen(
                        QPen(QColor(148, 163, 184, 180), max(1, int(2 * self._scale)))
                    )
                    pts = [
                        self._tile_to_canvas(tx + 0.5, ty + 0.5)
                        for tx, ty, _name in waypoints
                    ]
                    for i in range(len(pts) - 1):
                        painter.drawLine(QPointF(*pts[i]), QPointF(*pts[i + 1]))
                for i, (tx, ty, _name) in enumerate(waypoints):
                    cx, cy = self._tile_to_canvas(tx + 0.5, ty + 0.5)
                    painter.setPen(QPen(QColor("#94a3b8"), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(cx, cy), 5, 5)
                    painter.drawText(int(cx + 8), int(cy - 8), str(i + 1))
        if len(self.patrol) >= 2:
            painter.setPen(QPen(QColor(56, 189, 248, 210), max(2, int(2 * self._scale))))
            paths = self._patrol_paths
            if paths:
                for path in paths:
                    if len(path) < 2:
                        continue
                    for i in range(len(path) - 1):
                        a = self._tile_to_canvas(path[i][0] + 0.5, path[i][1] + 0.5)
                        b = self._tile_to_canvas(path[i + 1][0] + 0.5, path[i + 1][1] + 0.5)
                        painter.drawLine(QPointF(*a), QPointF(*b))
            else:
                pts = [
                    self._tile_to_canvas(tx + 0.5, ty + 0.5) for tx, ty, _n in self.patrol
                ]
                for i in range(len(pts) - 1):
                    painter.drawLine(QPointF(*pts[i]), QPointF(*pts[i + 1]))
        for i, (tx, ty, _n) in enumerate(self.patrol):
            cx, cy = self._tile_to_canvas(tx + 0.5, ty + 0.5)
            selected = self.selected == ("patrol", i)
            painter.setPen(QPen(QColor("#f97316" if selected else "#eab308"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            r = 6 if selected else 5
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.setPen(QColor("#fde68a"))
            painter.drawText(int(cx + 8), int(cy - 8), str(i + 1))
        if self._live_nav is not None:
            lx, ly = self._live_nav
            cx, cy = self._tile_to_canvas(lx + 0.5, ly + 0.5)
            self._paint_live_marker(painter, cx, cy)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")

    def _display_axes(self) -> PackAxes | None:
        """Origin of the pack this editor already loaded. Never a map-id search."""
        return axes_from_pack(self._pack)

    def _world_pair_text(self, tile_x: int, tile_y: int) -> str | None:
        axes = self._display_axes()
        if axes is None:
            return None
        world_x, world_y = axes.tile_to_world(int(tile_x), int(tile_y))
        return self.s.editor_world_xy.format(x=world_x, y=world_y)

    def _map_readout_text(self) -> str:
        parts: list[str] = []
        if self._hover_tile is not None:
            hx, hy = self._hover_tile
            world = self._world_pair_text(hx, hy)
            parts.append(world if world is not None else self.s.editor_world_unavailable)
            self._ensure_region_overlay()
            overlay = self._region_overlay
            if overlay is not None:
                where = overlay.hover_text(hx, hy)
                if where:
                    parts.append(where)
        if self._live_world is not None:
            lx, ly = self._live_world
            parts.append(self.s.editor_you_tile.format(x=lx, y=ly))
        return "  ·  ".join(parts)

    def _sync_map_readout(self) -> None:
        label = getattr(self, "map_readout", None)
        if label is None:
            return
        text = self._map_readout_text()
        if label.text() != text:
            label.setText(text)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_live_timer()

    def hideEvent(self, event) -> None:
        self._close_coord_popup()
        self._stop_live_timer()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_coord_popup()

    def _ensure_live_timer(self) -> None:
        if self._live_timer is None:
            timer = QTimer(self)
            timer.setInterval(_LIVE_POSE_POLL_MS)
            timer.timeout.connect(self._poll_live_position)
            self._live_timer = timer
        if self._live_anim_timer is None:
            anim = QTimer(self)
            anim.setInterval(_LIVE_ANIM_MS)
            anim.timeout.connect(self._tick_live_marker_anim)
            self._live_anim_timer = anim
        if not self._live_timer.isActive():
            self._live_timer.start()
            self._poll_live_position()
        self._sync_live_anim_timer()

    def _stop_live_timer(self) -> None:
        for timer in (self._live_timer, self._live_anim_timer):
            if timer is not None and timer.isActive():
                timer.stop()

    def _sync_live_anim_timer(self) -> None:
        anim = self._live_anim_timer
        if anim is None:
            return
        if self._live_nav is not None and self.isVisible():
            if not anim.isActive():
                anim.start()
        elif anim.isActive():
            anim.stop()

    def _tick_live_marker_anim(self) -> None:
        if self._live_nav is None:
            self._sync_live_anim_timer()
            return
        self.canvas.update()

    def _paint_live_marker(self, painter: QPainter, cx: float, cy: float) -> None:
        """Cyan crosshair with repeating expanding rings."""
        now = time.monotonic()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(_LIVE_RING_COUNT):
            phase = (now / _LIVE_RING_PERIOD_S + i / float(_LIVE_RING_COUNT)) % 1.0
            radius = 8.0 + phase * _LIVE_RING_MAX_R
            alpha = max(0, min(255, int(210 * (1.0 - phase))))
            width = max(1.5, 2.6 * (1.0 - 0.45 * phase))
            painter.setPen(QPen(QColor(34, 211, 238, alpha), width))
            painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.setBrush(QColor(34, 211, 238, 230))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawEllipse(QPointF(cx, cy), 7, 7)
        painter.setPen(QPen(QColor("#0e7490"), 2))
        arm = 11.0
        painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))

    def _poll_live_position(self) -> None:
        """Show the character when live MapSubsystem mapId matches this pack."""
        nav: tuple[int, int] | None = None
        world: tuple[int, int] | None = None
        try:
            from app._01_perception.sensors import shared_sensors
            from app._03_world.merge.memory_sync import (
                player_game_xy_from_snapshot,
                player_map_id_from_snapshot,
            )
            from app._04_decision.world_nav.pack_ids import abs_to_nav, pack_id_to_map_id

            pack_mid = pack_id_to_map_id(self.map_id)
            if pack_mid is None or not self.map_id:
                nav = None
            else:
                snap = shared_sensors().pull_player()
                if isinstance(snap, dict):
                    live_mid = player_map_id_from_snapshot(snap)
                    xy = player_game_xy_from_snapshot(snap)
                    if live_mid is not None and xy is not None and int(live_mid) == int(
                        pack_mid
                    ):
                        converted = abs_to_nav(self.map_id, int(xy[0]), int(xy[1]))
                        if converted is not None:
                            nav = (int(converted[0]), int(converted[1]))
                            world = (int(xy[0]), int(xy[1]))
        except Exception:
            nav = None
            world = None
        changed = nav != self._live_nav or world != self._live_world
        self._live_nav = nav
        self._live_world = world
        self._sync_live_anim_timer()
        if changed:
            self._sync_map_readout()
            self.canvas.update()

    def _anchor_image_point(self, canvas_x: float, canvas_y: float) -> tuple[float, float]:
        """Map a canvas point to image-pixel coordinates at the current scale."""
        self._fit()
        ox, oy = self._image_origin()
        scale = max(self._scale, 1e-6)
        return (canvas_x - ox) / scale, (canvas_y - oy) / scale

    def _pan_to_place_image_point(
        self, img_x: float, img_y: float, canvas_x: float, canvas_y: float
    ) -> None:
        """Set pan so image pixel (img_x, img_y) sits at canvas (canvas_x, canvas_y)."""
        if self._base is None:
            return
        self._fit()
        dw = max(1, int(self._base.width() * self._scale))
        dh = max(1, int(self._base.height() * self._scale))
        base_ox = (self.canvas.width() - dw) / 2.0
        base_oy = (self.canvas.height() - dh) / 2.0
        self._pan[0] = canvas_x - img_x * self._scale - base_ox
        self._pan[1] = canvas_y - img_y * self._scale - base_oy

    def _viewport_center_on_canvas(self) -> tuple[float, float]:
        try:
            vp = self._canvas_scroll.viewport()
            center = self.canvas.mapFrom(vp, vp.rect().center())
            return float(center.x()), float(center.y())
        except Exception:
            c = self.canvas.rect().center()
            return float(c.x()), float(c.y())

    def _zoom_by(self, factor: float) -> None:
        """Toolbar − / + : zoom toward the visible viewport center."""
        if self._base is None:
            return
        ax, ay = self._viewport_center_on_canvas()
        img_x, img_y = self._anchor_image_point(ax, ay)
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * float(factor)))
        self._sync_canvas_size()
        ax2, ay2 = self._viewport_center_on_canvas()
        self._pan_to_place_image_point(img_x, img_y, ax2, ay2)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")
        self.canvas.update()
        self._place_coord_popup()

    def _recenter_view(self) -> None:
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._fit()
        self._sync_canvas_size()
        # Reset scroll so the centered canvas sits in view.
        try:
            self._canvas_scroll.horizontalScrollBar().setValue(0)
            self._canvas_scroll.verticalScrollBar().setValue(0)
        except Exception:
            pass
        self.canvas.update()

    def _sync_canvas_size(self) -> None:
        self._fit()
        hint = self.canvas.sizeHint()
        self.canvas.resize(hint)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")

    def on_wheel(self, event: QWheelEvent) -> None:
        if self._base is None:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        pos = event.position()
        img_x, img_y = self._anchor_image_point(float(pos.x()), float(pos.y()))
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * float(factor)))
        self._sync_canvas_size()
        # Cursor stays put in global space; remapping keeps the image point under it.
        try:
            local = self.canvas.mapFromGlobal(event.globalPosition().toPoint())
            ax, ay = float(local.x()), float(local.y())
        except Exception:
            ax, ay = float(pos.x()), float(pos.y())
        self._pan_to_place_image_point(img_x, img_y, ax, ay)
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")
        self.canvas.update()
        self._place_coord_popup()

    def on_mouse_press(self, event) -> None:
        # Right-click on a farm opens copy / duplicate / rename.
        # Empty ground and middle button pan. Do not reference SpaceModifier.
        if (
            event.button() == Qt.MouseButton.RightButton
            and self._base is not None
            and self._can_edit()
        ):
            tx, ty = self._canvas_to_tile(event.position().x(), event.position().y())
            if self._point_tools_active():
                hit_point = self._hit_point(tx, ty)
                if hit_point is not None:
                    self._select("point", hit_point)
                    self._point_menu(hit_point, event.globalPosition().toPoint())
                    event.accept()
                    return
            if not self._dungeon:
                hit = self._hit_farm(tx, ty)
                if hit is not None:
                    self._select("farm", hit)
                    self._farm_menu(hit, event.globalPosition().toPoint())
                    event.accept()
                    return
        if event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._panning = True
            self._pan_start = (event.position().x(), event.position().y())
            self._pan_origin = list(self._pan)
            self._sync_canvas_cursor()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._can_edit() or self._base is None:
            if self._base is not None and not self._can_edit():
                self.status.setText(self.s.editor_readonly)
            return
        cx, cy = event.position().x(), event.position().y()
        tx, ty = self._canvas_to_tile(cx, cy)
        if self._point_tools_active() and self.tool == "point":
            if self._dungeon_plan_mode():
                self._place_stationary(tx, ty)
            else:
                self._place_point(tx, ty)
            return
        if self._dungeon and self.tool == "patrol":
            self._drop_patrol_at(tx, ty)
            return
        if self._dungeon:
            self._deselect()
            return
        grabbed = self._handle_target(cx, cy)
        if grabbed is not None:
            hit_f, handle = grabbed
            self._select("farm", hit_f)
            self._drag = handle
            self._drag_origin = dict(self.farms[hit_f])
            self._hover_move = (tx, ty)
            self._sync_canvas_cursor(cx, cy)
            return
        hit_f = self._hit_farm(tx, ty)
        if hit_f is not None:
            self._select("farm", hit_f)
            self._drag = "move"
            self._drag_origin = dict(self.farms[hit_f])
            self._hover_move = (tx, ty)
            self._sync_canvas_cursor(cx, cy)
            return
        if self._spot_tools_active() and self.tool != "area":
            return
        self._rect_anchor = (tx, ty)
        self.selected = None
        self._sync_canvas_cursor(cx, cy)

    def on_mouse_move(self, event) -> None:
        cx, cy = event.position().x(), event.position().y()
        if self._panning:
            self._pan[0] = self._pan_origin[0] + (cx - self._pan_start[0])
            self._pan[1] = self._pan_origin[1] + (cy - self._pan_start[1])
            self._sync_canvas_cursor(cx, cy)
            self.canvas.update()
            self._place_coord_popup()
            return
        if self._base is None:
            return
        tx, ty = self._canvas_to_tile(cx, cy)
        self._hover_tile = (tx, ty)
        self._sync_map_readout()
        self._sync_canvas_cursor(cx, cy)
        if not self._can_edit():
            self.canvas.update()
            return
        if not self._dungeon and self._rect_anchor is not None:
            ax, ay = self._rect_anchor
            preview = {
                "name": "new",
                "region": self._pack.default_region if self._pack else "",
                "x0": min(ax, tx),
                "y0": min(ay, ty),
                "x1": max(ax, tx),
                "y1": max(ay, ty),
                "_preview": True,
            }
            if self._farm_overlaps(preview):
                self.status.setText(self.s.areas_overlap)
                self.canvas.update()
                return
            if self.farms and self.farms[-1].get("_preview"):
                self.farms[-1] = preview
            else:
                self.farms.append(preview)
            self.canvas.update()
            return
        if self.selected is None or self._drag is None:
            self.canvas.update()
            return
        kind, idx = self.selected
        if kind == "point" and self._drag == "move" and 0 <= idx < len(self.farms):
            if self._refuse_hunt_point(tx, ty):
                self.canvas.update()
                return
            self.farms[idx]["x"] = tx
            self.farms[idx]["y"] = ty
            self._mark_dirty()
            self.canvas.update()
            self._place_coord_popup()
            return
        if kind == "patrol":
            if self._terrain is not None and not self._terrain.is_walkable(tx, ty):
                return
            _x, _y, name = self.patrol[idx]
            self.patrol[idx] = (tx, ty, name)
            self._mark_dirty()
            self.canvas.update()
            return
        if self._dungeon or kind != "farm":
            return
        origin = self._drag_origin
        if not isinstance(origin, dict):
            return
        f = self.farms[idx]
        proposed = dict(origin)
        if self._drag == "move" and self._hover_move is not None:
            dx = tx - self._hover_move[0]
            dy = ty - self._hover_move[1]
            w = origin["x1"] - origin["x0"]
            h = origin["y1"] - origin["y0"]
            nx0, ny0 = self._clamp_tile(origin["x0"] + dx, origin["y0"] + dy)
            proposed["x0"], proposed["y0"] = nx0, ny0
            proposed["x1"], proposed["y1"] = self._clamp_tile(nx0 + w, ny0 + h)
        else:
            x0, y0, x1, y1 = origin["x0"], origin["y0"], origin["x1"], origin["y1"]
            handle = self._drag or ""
            if "n" in handle:
                y0 = ty
            if "s" in handle:
                y1 = ty
            if "w" in handle:
                x0 = tx
            if "e" in handle:
                x1 = tx
            x0, y0 = self._clamp_tile(x0, y0)
            x1, y1 = self._clamp_tile(x1, y1)
            proposed["x0"], proposed["x1"] = min(x0, x1), max(x0, x1)
            proposed["y0"], proposed["y1"] = min(y0, y1), max(y0, y1)
        if self._farm_overlaps(proposed, ignore=idx):
            self.status.setText(self.s.areas_overlap)
            self.canvas.update()
            return
        f["x0"], f["y0"], f["x1"], f["y1"] = (
            proposed["x0"],
            proposed["y0"],
            proposed["x1"],
            proposed["y1"],
        )
        self._mark_dirty()
        self.canvas.update()

    def on_mouse_release(self, event) -> None:
        if event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.LeftButton,
        ):
            self._panning = False
        if not self._dungeon and self._rect_anchor is not None:
            if self.farms and self.farms[-1].get("_preview"):
                farm = dict(self.farms[-1])
                farm.pop("_preview", None)
                degenerate = farm["x0"] == farm["x1"] and farm["y0"] == farm["y1"]
                if degenerate or self._farm_overlaps(farm):
                    self.farms.pop()
                    if not degenerate:
                        self.status.setText(self.s.areas_overlap)
                else:
                    taken = [
                        str(item.get("name"))
                        for item in self.farms
                        if not item.get("_preview")
                    ]
                    n = 1
                    while f"area_{n}" in taken:
                        n += 1
                    farm["name"] = f"area_{n}"
                    self.farms[-1] = farm
                    self._mark_dirty()
                    self._select("farm", len(self.farms) - 1)
            self._rect_anchor = None
        self._drag = None
        self._drag_origin = None
        self._hover_move = None
        self._sync_canvas_cursor(
            event.position().x(),
            event.position().y(),
        )
        if self._dungeon:
            self._recompute_patrol_paths()
        self._refresh_list()
        self.canvas.update()

    def _handle_points(self, f: dict) -> dict[str, tuple[float, float]]:
        x0, y0 = self._tile_to_canvas(f["x0"], f["y0"])
        x1, y1 = self._tile_to_canvas(f["x1"] + 1, f["y1"] + 1)
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return {
            "nw": (x0, y0),
            "n": (mx, y0),
            "ne": (x1, y0),
            "e": (x1, my),
            "se": (x1, y1),
            "s": (mx, y1),
            "sw": (x0, y1),
            "w": (x0, my),
        }

    def _sync_canvas_cursor(self, cx: float | None = None, cy: float | None = None) -> None:
        """Resize arrows on handles, an open hand to move, a closed hand while dragging."""
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        if self._panning or self._drag == "move":
            canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._drag in _HANDLE_CURSORS:
            canvas.setCursor(_HANDLE_CURSORS[self._drag])
            return
        if (
            not self._can_edit()
            or self._dungeon
            or self._base is None
            or cx is None
            or cy is None
        ):
            canvas.setCursor(
                Qt.CursorShape.CrossCursor
                if self._rect_anchor is not None
                else Qt.CursorShape.ArrowCursor
            )
            return
        if self._rect_anchor is not None:
            canvas.setCursor(Qt.CursorShape.CrossCursor)
            return
        grabbed = self._handle_target(cx, cy)
        if grabbed is not None:
            canvas.setCursor(_HANDLE_CURSORS[grabbed[1]])
            return
        tx, ty = self._canvas_to_tile(cx, cy)
        if self._hit_farm(tx, ty) is not None:
            canvas.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def _handle_target(self, cx: float, cy: float) -> tuple[int, str] | None:
        """Farm handle under the pointer, including the part that sits outside the box."""
        order: list[int] = []
        if self.selected and self.selected[0] == "farm":
            selected = self.selected[1]
            if 0 <= selected < len(self.farms):
                order.append(selected)
        for i in range(len(self.farms) - 1, -1, -1):
            if i not in order:
                order.append(i)
        for i in order:
            farm = self.farms[i]
            if farm.get("_preview") or self._is_point(farm):
                continue
            handle = self._hit_handle(farm, cx, cy)
            if handle:
                return i, handle
        return None

    def _hit_handle(self, f: dict, cx: float, cy: float) -> Handle:
        best: Handle = None
        best_d = _HANDLE_PX
        for name, (hx, hy) in self._handle_points(f).items():
            d = max(abs(cx - hx), abs(cy - hy))
            if d <= best_d:
                best_d = d
                best = name
        return best

    def _hit_farm(self, tx: int, ty: int) -> Optional[int]:
        for i in range(len(self.farms) - 1, -1, -1):
            f = self.farms[i]
            if f.get("_preview") or self._is_point(f):
                continue
            if f["x0"] <= tx <= f["x1"] and f["y0"] <= ty <= f["y1"]:
                return i
        return None

    def _hit_point(self, tx: int, ty: int) -> Optional[int]:
        best_i = None
        best_d = 2
        for i, farm in enumerate(self.farms):
            if not self._is_point(farm):
                continue
            distance = max(abs(int(farm["x"]) - tx), abs(int(farm["y"]) - ty))
            if distance <= best_d:
                best_d = distance
                best_i = i
        return best_i

    def _hit_inactive_patrol(self, tx: int, ty: int) -> tuple[dict, int] | None:
        best: tuple[dict, int] | None = None
        best_d = 3
        for entry in self._plan:
            if entry.get("type") != "patrol" or entry.get("waypoints") is self.patrol:
                continue
            for index, (x, y, _name) in enumerate(entry.get("waypoints") or []):
                distance = max(abs(int(x) - tx), abs(int(y) - ty))
                if distance <= best_d:
                    best_d = distance
                    best = (entry, index)
        return best

    def _refuse_hunt_point(self, tx: int, ty: int) -> bool:
        """Party hunt dot: the nav grid must be able to step onto this tile."""
        from app._03_world.space.hunt_point import hunt_point_refused

        if not hunt_point_refused(self._terrain, tx, ty):
            return False
        self.status.setText(self.s.hunt_point_refused)
        return True

    def _place_point(self, tx: int, ty: int) -> None:
        hit = self._hit_point(tx, ty)
        if hit is not None:
            self._select("point", hit)
            self._drag = "move"
            self._drag_origin = dict(self.farms[hit])
            return
        if self._refuse_hunt_point(tx, ty):
            return
        taken = {
            str(item.get("name"))
            for item in self.farms
            if self._is_point(item)
        }
        number = 1
        while f"point_{number}" in taken:
            number += 1
        point = {
            "shape": "point",
            "name": f"point_{number}",
            "region": self._pack.default_region if self._pack else "",
            "x": tx,
            "y": ty,
        }
        if self._dungeon:
            point["stay_s"] = DEFAULT_FARM_STAY_S
        self.farms.append(point)
        self._mark_dirty()
        self._select("point", len(self.farms) - 1)
        self._drag = "move"
        self._drag_origin = dict(self.farms[-1])

    def _drop_patrol_at(self, tx: int, ty: int) -> None:
        """Place or grab a waypoint on the active patrol route."""
        other = self._hit_inactive_patrol(tx, ty) if self._dungeon_plan_mode() else None
        if other is not None:
            route, hit = other
            self._use_route(route)
            self._select("patrol", hit)
            self._drag = "move"
            self._drag_origin = self.patrol[hit]
            return
        hit = self._hit_patrol(tx, ty)
        if hit is not None:
            self._select("patrol", hit)
            self._drag = "move"
            self._drag_origin = self.patrol[hit]
            return
        if self._terrain is not None and not self._terrain.is_walkable(tx, ty):
            self.status.setText(self.s.patrol_not_walkable)
            return
        if self._dungeon_plan_mode() and self._active_route() is None:
            self._begin_patrol_route()
        name = f"mid_{len(self.patrol) + 1}"
        self.patrol.append((tx, ty, name))
        self._mark_dirty()
        self._recompute_patrol_paths()
        self._select("patrol", len(self.patrol) - 1)

    def _place_stationary(self, tx: int, ty: int) -> None:
        """One dungeon hunt point. It is not a patrol waypoint."""
        hit = self._hit_point(tx, ty)
        if hit is not None:
            self._select("point", hit)
            self._drag = "move"
            self._drag_origin = dict(self.farms[hit])
            return
        if self._refuse_hunt_point(tx, ty):
            return
        point_id = self._next_plan_id("point")
        point = {
            "type": "point",
            "shape": "point",
            "id": point_id,
            "name": point_id,
            "region": self._pack.default_region if self._pack else "",
            "x": tx,
            "y": ty,
            "stay_s": DEFAULT_FARM_STAY_S,
        }
        self._plan.append(point)
        self._sync_point_farms()
        self._mark_dirty()
        self._select("point", self.farms.index(point))
        self._drag = "move"
        self._drag_origin = dict(point)

    def _point_menu_actions(self, menu: QMenu):
        """Delete, then coordinate edit. Edit stays disabled until an origin exists."""
        delete_act = menu.addAction(self.s.delete_selected)
        edit_act = menu.addAction(self.s.menu_edit_coords)
        if self._display_axes() is None:
            edit_act.setEnabled(False)
            self.status.setText(self.s.editor_world_unavailable)
        return delete_act, edit_act

    def _point_menu(self, idx: int, global_pos) -> None:
        menu = QMenu(self)
        delete_act, edit_act = self._point_menu_actions(menu)
        chosen = menu.exec(global_pos)
        if chosen is delete_act:
            self._delete_selected()
        elif chosen is edit_act:
            self._open_coord_popup(idx)

    def _tile_on_map(self, tile_x: int, tile_y: int) -> bool:
        if self._terrain is None and self._base is None:
            return False
        limit_x, limit_y = self._map_limits()
        return 0 <= int(tile_x) <= limit_x and 0 <= int(tile_y) <= limit_y

    def _open_coord_popup(self, idx: int) -> None:
        if not self._can_edit() or not (0 <= idx < len(self.farms)):
            return
        farm = self.farms[idx]
        if not self._is_point(farm):
            return
        if self._display_axes() is None:
            self.status.setText(self.s.editor_world_unavailable)
            return
        self._close_coord_popup()
        self._select("point", idx)
        popup = _PointWorldEditor(self, farm)
        self._coord_popup = popup
        popup.show()
        popup.setFixedSize(popup.sizeHint())
        self._place_coord_popup()
        popup.raise_()
        popup.activateWindow()
        popup.x_edit.setFocus()
        popup.x_edit.selectAll()

    def _close_coord_popup(self) -> None:
        popup = self._coord_popup
        self._coord_popup = None
        if popup is None:
            return
        try:
            popup.hide()
            popup.deleteLater()
        except RuntimeError:
            pass

    def _point_global_anchor(self, farm: dict) -> QPoint | None:
        try:
            canvas_x, canvas_y = self._tile_to_canvas(
                int(farm["x"]) + 0.5, int(farm["y"]) + 0.5
            )
        except (KeyError, TypeError, ValueError):
            return None
        return self.canvas.mapToGlobal(QPoint(int(round(canvas_x)), int(round(canvas_y))))

    def _viewport_global_edges(self) -> tuple[int, int, int, int] | None:
        try:
            viewport = self._canvas_scroll.viewport()
        except Exception:
            return None
        if viewport is None:
            return None
        origin = viewport.mapToGlobal(QPoint(0, 0))
        return (
            origin.x(),
            origin.y(),
            origin.x() + max(1, viewport.width()) - 1,
            origin.y() + max(1, viewport.height()) - 1,
        )

    def _place_coord_popup(self) -> None:
        popup = self._coord_popup
        if popup is None:
            return
        farm = popup.farm
        if farm not in self.farms or not self._is_point(farm):
            self._close_coord_popup()
            return
        anchor = self._point_global_anchor(farm)
        edges = self._viewport_global_edges()
        if anchor is None or edges is None:
            self._close_coord_popup()
            return
        popup.adjustSize()
        size = popup.size()
        if size.width() < 8 or size.height() < 8:
            size = popup.sizeHint()
        left, top, right, bottom = edges
        x, y = clamp_popup_top_left(
            anchor.x(),
            anchor.y(),
            size.width(),
            size.height(),
            left,
            top,
            right,
            bottom,
        )
        popup.move(x, y)

    def _apply_world_to_point(self, farm: dict, raw_x: str, raw_y: str) -> bool:
        """Write a typed world coordinate back into the in-memory tile. No file write."""
        if farm not in self.farms or not self._is_point(farm):
            self._close_coord_popup()
            return False
        axes = self._display_axes()
        if axes is None:
            self.status.setText(self.s.editor_world_unavailable)
            return False
        world_x = parse_world_int(raw_x)
        world_y = parse_world_int(raw_y)
        if world_x is None or world_y is None:
            self.status.setText(self.s.coord_invalid)
            return False
        tile_x, tile_y = axes.world_to_tile(world_x, world_y)
        if not self._tile_on_map(tile_x, tile_y):
            self.status.setText(self.s.coord_off_map)
            return False
        if self._refuse_hunt_point(tile_x, tile_y):
            return False
        if int(farm.get("x", tile_x)) != tile_x or int(farm.get("y", tile_y)) != tile_y:
            farm["x"] = tile_x
            farm["y"] = tile_y
            self._mark_dirty()
        self._close_coord_popup()
        self._refresh_list()
        self.canvas.update()
        return True

    def _hit_patrol(self, tx: int, ty: int) -> Optional[int]:
        best_i = None
        best_d = 3
        for i, (x, y, _n) in enumerate(self.patrol):
            d = max(abs(x - tx), abs(y - ty))
            if d <= best_d:
                best_d = d
                best_i = i
        return best_i

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _select(self, kind: str, idx: int) -> None:
        self.selected = (kind, idx)
        self._refresh_list()
        self._fill_inspector()
        self.canvas.update()

    def _deselect(self) -> None:
        self.selected = None
        if self.tool not in ("area", "point"):
            self.tool = "select"
        self._refresh_list()
        self._fill_inspector()
        self.canvas.update()

    def _point_stay_label(self, farm: dict) -> str:
        seconds = farm["stay_s"] if "stay_s" in farm else DEFAULT_FARM_STAY_S
        minutes = stay_minutes_from_s(clamp_farm_stay_s(seconds))
        return self.s.point_stay.format(minutes=minutes)

    def _on_list_double(self, item: QListWidgetItem) -> None:
        """Dungeon point dwell. Field stays stay in the setting table."""
        if not (self._dungeon_plan_mode() and self._can_edit()):
            return
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not (isinstance(data, tuple) and len(data) >= 2):
            return
        kind, idx = str(data[0]), int(data[1])
        if kind == "plan" and 0 <= idx < len(self._plan):
            entry = self._plan[idx]
            if entry.get("type") == "patrol":
                self._edit_route_duration(idx)
                return
            if entry.get("type") == "point" and entry in self.farms:
                self._edit_point_stay(self.farms.index(entry))
                return
        if kind == "point":
            self._edit_point_stay(idx)

    def _edit_point_stay(self, idx: int) -> None:
        if not (0 <= idx < len(self.farms)) or not self._is_point(self.farms[idx]):
            return
        farm = self.farms[idx]
        initial = stay_minutes_from_s(
            clamp_farm_stay_s(farm["stay_s"])
            if "stay_s" in farm
            else DEFAULT_FARM_STAY_S
        )
        value, ok = QInputDialog.getInt(
            self,
            self.s.point_stay_title,
            self.s.point_stay_prompt,
            initial,
            MIN_FARM_STAY_MIN,
            MAX_FARM_STAY_MIN,
        )
        if not ok:
            return
        self._apply_point_stay(idx, value)

    def _apply_point_stay(self, idx: int, minutes: int) -> None:
        if not (0 <= idx < len(self.farms)) or not self._is_point(self.farms[idx]):
            return
        self.farms[idx]["stay_s"] = stay_s_from_minutes(minutes)
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _edit_route_duration(self, plan_index: int) -> None:
        if not (0 <= plan_index < len(self._plan)):
            return
        route = self._plan[plan_index]
        if route.get("type") != "patrol":
            return
        initial = self._route_minutes(route)
        value, ok = QInputDialog.getInt(
            self,
            self.s.point_stay_title,
            self.s.point_stay_prompt,
            initial,
            MIN_FARM_STAY_MIN,
            MAX_FARM_STAY_MIN,
        )
        if not ok:
            return
        self._apply_route_duration(plan_index, value)

    def _apply_route_duration(self, plan_index: int, minutes: int) -> None:
        if not (0 <= plan_index < len(self._plan)):
            return
        route = self._plan[plan_index]
        if route.get("type") != "patrol":
            return
        route["duration_s"] = stay_s_from_minutes(minutes)
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _on_list_row(self, row: int) -> None:
        if row < 0:
            return
        item = self.item_list.item(row)
        data = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if isinstance(data, tuple) and len(data) >= 2:
            kind, idx = str(data[0]), int(data[1])
            if kind == "patrol" and len(data) >= 3:
                self._select_waypoint(int(data[2]), idx)
                return
            if kind == "plan":
                if self.selected != ("plan", idx):
                    self._focus_plan(idx)
                return
            if self.selected != (kind, idx):
                self._select(kind, idx)
            return
        if self._dungeon:
            if 0 <= row < len(self.patrol):
                self._select("patrol", row)
        else:
            farms = [i for i, f in enumerate(self.farms) if not f.get("_preview")]
            if 0 <= row < len(farms):
                self._select("farm", farms[row])

    def _list_row_width(self) -> int:
        try:
            width = int(self.item_list.viewport().width())
        except Exception:
            width = 0
        return max(width, 220)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            getattr(self, "item_list", None) is not None
            and watched is self.item_list.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._fit_list_rows()
        return super().eventFilter(watched, event)

    def _fit_list_rows(self) -> None:
        if getattr(self, "_fitting_rows", False):
            return
        width = self._list_row_width()
        self._fitting_rows = True
        try:
            for i in range(self.item_list.count()):
                item = self.item_list.item(i)
                if item is None or item.sizeHint().width() == width:
                    continue
                item.setSizeHint(QSize(width, 26))
        finally:
            self._fitting_rows = False

    def _plan_rows(self) -> list[dict]:
        """Top-level points and the one patrol. Waypoints stay under that patrol."""
        rows: list[dict] = []
        point_number = 0
        patrols = [entry for entry in self._plan if entry.get("type") == "patrol"]
        for index, entry in enumerate(self._plan):
            if entry.get("type") == "patrol":
                waypoints = list(entry.get("waypoints") or [])
                label = self.s.plan_patrol_label
                if len(patrols) > 1:
                    label = f"{label} ({entry.get('id') or ''})"
                title = (
                    f"{label} · {self.s.point_stay.format(minutes=self._route_minutes(entry))}"
                    f" · {self.s.plan_waypoint_count.format(n=len(waypoints))}"
                )
                route_id = str(entry.get("id") or "")
                expanded = route_id not in self._collapsed_plan_ids
                rows.append(
                    {
                        "title": title,
                        "kind": "plan",
                        "idx": index,
                        "toggle_id": route_id,
                        "expanded": expanded,
                    }
                )
                if not expanded:
                    continue
                for waypoint, (_x, _y, name) in enumerate(waypoints):
                    last = waypoint == len(waypoints) - 1
                    rows.append(
                        {
                            "title": route_point_display_name(str(name), self.language),
                            "kind": "patrol",
                            "idx": waypoint,
                            "route": index,
                            "depth": 1,
                            "marker": "└─" if last else "├─",
                        }
                    )
                continue
            if entry.get("type") != "point":
                continue
            point_number += 1
            pair = self._world_pair_text(int(entry["x"]), int(entry["y"]))
            shown = pair if pair is not None else self.s.editor_world_unavailable
            title = (
                f"{self.s.plan_point.format(n=point_number)} · "
                f"{self._point_stay_label(entry)} · {shown}"
            )
            rows.append(
                {
                    "title": title,
                    "kind": "plan",
                    "idx": index,
                }
            )
        return rows

    def _toggle_plan_route(self, route_id: str) -> None:
        key = str(route_id or "")
        if key in self._collapsed_plan_ids:
            self._collapsed_plan_ids.discard(key)
        else:
            self._collapsed_plan_ids.add(key)
        self._refresh_list()

    def _select_waypoint(self, plan_index: int, waypoint: int) -> None:
        if not (0 <= plan_index < len(self._plan)):
            return
        route = self._plan[plan_index]
        if route.get("type") != "patrol":
            return
        self._use_route(route)
        self._select("patrol", waypoint)

    def _nudge_waypoint(self, plan_index: int, waypoint: int, delta: int) -> None:
        """Reorder one patrol's waypoints. The top-level plan order stays put."""
        if not self._can_edit() or not (0 <= plan_index < len(self._plan)):
            self.status.setText(self.s.editor_readonly)
            return
        route = self._plan[plan_index]
        points = route.get("waypoints")
        if route.get("type") != "patrol" or not isinstance(points, list):
            return
        target = int(waypoint) + int(delta)
        if target < 0 or target >= len(points) or not (0 <= waypoint < len(points)):
            return
        points[waypoint], points[target] = points[target], points[waypoint]
        self._use_route(route)
        self._mark_dirty()
        self._recompute_patrol_paths()
        self._select("patrol", target)

    def _refresh_list(self) -> None:
        self.item_list.blockSignals(True)
        self.item_list.clear()
        if self._dungeon_plan_mode():
            rows = self._plan_rows()
        elif self._dungeon and not self._point_tools_active():
            rows = [
                (route_point_display_name(name, self.language), "patrol", i)
                for i, (_x, _y, name) in enumerate(self.patrol)
            ]
        else:
            rows = []
            order = 0
            for i, f in enumerate(self.farms):
                if f.get("_preview"):
                    continue
                order += 1
                if self._point_tools_active() and self._is_point(f):
                    pair = self._world_pair_text(int(f["x"]), int(f["y"]))
                    shown = pair if pair is not None else self.s.editor_world_unavailable
                    title = f"{order}. {self._shape_label('point')}  ({shown})"
                    if self._dungeon:
                        title = f"{title}  {self._point_stay_label(f)}"
                    kind = "point"
                elif self._spot_tools_active():
                    start = self._world_pair_text(int(f["x0"]), int(f["y0"]))
                    end = self._world_pair_text(int(f["x1"]), int(f["y1"]))
                    if start is None or end is None:
                        shown = self.s.editor_world_unavailable
                    else:
                        shown = f"{start} ~ {end}"
                    title = f"{order}. {self._shape_label('area')}  ({shown})"
                    kind = "farm"
                else:
                    title = route_point_display_name(str(f["name"]), self.language)
                    kind = "farm"
                rows.append((title, kind, i))
        self.list_count.setText(str(len(rows)))
        for row in rows:
            if isinstance(row, dict):
                title = str(row["title"])
                kind = str(row["kind"])
                idx = int(row["idx"])
                route = row.get("route")
            else:
                title, kind, idx = row
                route = None
            item = QListWidgetItem()
            role = (kind, idx) if route is None else (kind, idx, int(route))
            item.setData(Qt.ItemDataRole.UserRole, role)
            item.setSizeHint(QSize(self._list_row_width(), 26))
            self.item_list.addItem(item)
            selected = self.selected == (kind, idx)
            if kind == "patrol" and route is not None:
                active = self._active_route()
                selected = (
                    selected
                    and active is not None
                    and 0 <= int(route) < len(self._plan)
                    and self._plan[int(route)] is active
                )
            if (
                not selected
                and kind == "plan"
                and self.selected
                and self.selected[0] == "point"
                and 0 <= idx < len(self._plan)
                and 0 <= self.selected[1] < len(self.farms)
                and self._plan[idx] is self.farms[self.selected[1]]
            ):
                selected = True
            extra = {}
            if isinstance(row, dict):
                extra = {
                    "depth": int(row.get("depth") or 0),
                    "marker": str(row.get("marker") or ""),
                    "route": None if route is None else int(route),
                }
                toggle_id = row.get("toggle_id")
                if toggle_id is not None:
                    extra["toggle"] = lambda key=str(toggle_id): self._toggle_plan_route(key)
                    extra["expanded"] = bool(row.get("expanded"))
            self.item_list.setItemWidget(
                item,
                _OrderRow(self, kind, idx, title, selected=selected, **extra),
            )
            if selected:
                self.item_list.setCurrentItem(item)
        self.item_list.blockSignals(False)

    def _fill_inspector(self) -> None:
        return

    def _rects_overlap(self, a: dict, b: dict) -> bool:
        return not (
            int(a["x1"]) < int(b["x0"])
            or int(b["x1"]) < int(a["x0"])
            or int(a["y1"]) < int(b["y0"])
            or int(b["y1"]) < int(a["y0"])
        )

    def _farm_overlaps(self, rect: dict, ignore: int | None = None) -> bool:
        for i, other in enumerate(self.farms):
            if other.get("_preview") or self._is_point(other):
                continue
            if ignore is not None and i == ignore:
                continue
            if self._rects_overlap(rect, other):
                return True
        return False

    def _farm_menu(self, idx: int, global_pos) -> None:
        menu = QMenu(self)
        copy_act = menu.addAction(self.s.menu_copy)
        delete_act = menu.addAction(self.s.delete_selected)
        rename_act = menu.addAction(self.s.menu_rename)
        chosen = menu.exec(global_pos)
        if chosen is copy_act:
            self._clone_farm(idx)
        elif chosen is delete_act:
            self._delete_selected()
        elif chosen is rename_act:
            self._rename_farm(idx)

    def _clone_farm(self, idx: int) -> None:
        if not self._can_edit() or not (0 <= idx < len(self.farms)):
            return
        src = self.farms[idx]
        if src.get("_preview") or self._is_point(src):
            return
        w = int(src["x1"]) - int(src["x0"])
        h = int(src["y1"]) - int(src["y0"])
        mx, my = self._map_limits()
        step_x = max(1, w + 1)
        step_y = max(1, h + 1)
        offsets: list[tuple[int, int]] = []
        for dist in range(1, 24):
            offsets.extend(
                (
                    (step_x * dist, 0),
                    (-step_x * dist, 0),
                    (0, step_y * dist),
                    (0, -step_y * dist),
                    (step_x * dist, step_y * dist),
                    (-step_x * dist, step_y * dist),
                    (step_x * dist, -step_y * dist),
                    (-step_x * dist, -step_y * dist),
                )
            )
        names = {
            str(item.get("name"))
            for item in self.farms
            if not item.get("_preview")
        }
        base = f"{src['name']}_copy"
        name = base
        n = 2
        while name in names:
            name = f"{base}_{n}"
            n += 1
        for dx, dy in offsets:
            nx0 = int(src["x0"]) + dx
            ny0 = int(src["y0"]) + dy
            nx1 = nx0 + w
            ny1 = ny0 + h
            if nx0 < 0 or ny0 < 0 or nx1 > mx or ny1 > my:
                continue
            clone = dict(src)
            clone.pop("_preview", None)
            clone["name"] = name
            clone["x0"], clone["y0"], clone["x1"], clone["y1"] = nx0, ny0, nx1, ny1
            if self._farm_overlaps(clone):
                continue
            self.farms.insert(idx + 1, clone)
            self._mark_dirty()
            self._select("farm", idx + 1)
            return
        self.status.setText(self.s.areas_overlap)

    def _rename_farm(self, idx: int) -> None:
        if not self._can_edit() or not (0 <= idx < len(self.farms)):
            return
        current = str(self.farms[idx].get("name") or "")
        text, ok = QInputDialog.getText(
            self, self.s.menu_rename, self.s.rename_label, text=current
        )
        if not ok:
            return
        name = text.strip()
        if not name or name == current:
            return
        self.farms[idx]["name"] = name
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _patrol_row_menu(self, idx: int, global_pos) -> None:
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return
        if not (0 <= idx < len(self.patrol)):
            return
        self._select("patrol", idx)
        menu = QMenu(self)
        delete_act = menu.addAction(self.s.delete_selected)
        rename_act = menu.addAction(self.s.menu_rename)
        chosen = menu.exec(global_pos)
        if chosen is delete_act:
            self._delete_selected()
        elif chosen is rename_act:
            self._rename_patrol(idx)

    def _rename_patrol(self, idx: int) -> None:
        if not self._can_edit() or not (0 <= idx < len(self.patrol)):
            return
        x, y, current = self.patrol[idx]
        text, ok = QInputDialog.getText(
            self, self.s.menu_rename, self.s.rename_label, text=current
        )
        if not ok:
            return
        name = text.strip()
        if not name or name == current:
            return
        self.patrol[idx] = (x, y, name)
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _delete_selected(self) -> None:
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return
        if self.selected is None:
            return
        kind, idx = self.selected
        if self._dungeon_plan_mode() and kind == "plan" and 0 <= idx < len(self._plan):
            removed = self._plan.pop(idx)
            if removed.get("type") == "patrol" and removed.get("waypoints") is self.patrol:
                self.patrol = []
                self._active_route_id = None
                for entry in self._plan:
                    if entry.get("type") == "patrol":
                        self._use_route(entry)
                        break
                self._recompute_patrol_paths()
            self._sync_point_farms()
            self._mark_dirty()
            self._deselect()
            return
        if (
            kind in ("farm", "point")
            and 0 <= idx < len(self.farms)
            and not self.farms[idx].get("_preview")
        ):
            removed = self.farms[idx]
            if self._coord_popup is not None and self._coord_popup.farm is removed:
                self._close_coord_popup()
            if self._dungeon_plan_mode() and removed in self._plan:
                self._plan.remove(removed)
            del self.farms[idx]
        elif kind == "patrol" and 0 <= idx < len(self.patrol):
            del self.patrol[idx]
            self._recompute_patrol_paths()
        else:
            return
        self._mark_dirty()
        self._deselect()

    def confirm_close(self) -> bool:
        """Yes saves, No discards, Cancel stays open."""
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self._area_title())
        box.setText(self.s.confirm_unsaved)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        choice = box.exec()
        if choice == QMessageBox.StandardButton.Yes:
            return bool(self.save())
        if choice == QMessageBox.StandardButton.No:
            self._dirty = False
            return True
        return False

    def _clear_all(self) -> None:
        if not self._can_edit():
            return
        if self._dungeon:
            msg = self.s.confirm_clear_patrol
        elif self._area_kind == "safe":
            msg = self.s.confirm_clear_rest
        else:
            msg = self.s.confirm_clear_farms
        if QMessageBox.question(self, self.s.edit_farms, msg) != QMessageBox.StandardButton.Yes:
            return
        self._close_coord_popup()
        if self._dungeon_plan_mode():
            self._plan.clear()
            self.patrol = []
            self._active_route_id = None
            self._sync_point_farms()
            self._recompute_patrol_paths()
        elif self._dungeon:
            self.patrol.clear()
            self._recompute_patrol_paths()
        else:
            self.farms.clear()
        self.selected = None
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _plan_row_menu(self, idx: int, global_pos) -> None:
        if not self._can_edit() or not (0 <= idx < len(self._plan)):
            return
        entry = self._plan[idx]
        self._focus_plan(idx)
        if entry.get("type") == "point" and entry in self.farms:
            self._point_menu(self.farms.index(entry), global_pos)
            return
        menu = QMenu(self)
        delete_act = menu.addAction(self.s.delete_selected)
        chosen = menu.exec(global_pos)
        if chosen is delete_act:
            self.selected = ("plan", self._plan.index(entry) if entry in self._plan else idx)
            self._delete_selected()

    def _nudge_at(self, kind: str, idx: int, delta: int) -> None:
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return
        if kind == "plan" and self._dungeon_plan_mode():
            target = idx + int(delta)
            if target < 0 or target >= len(self._plan) or not (0 <= idx < len(self._plan)):
                return
            self._plan[idx], self._plan[target] = self._plan[target], self._plan[idx]
            self._sync_point_farms()
            self._mark_dirty()
            self._select("plan", target)
            return
        items = self.patrol if kind == "patrol" else self.farms
        target = idx + int(delta)
        if target < 0 or target >= len(items):
            return
        if kind != "patrol" and (
            items[idx].get("_preview") or items[target].get("_preview")
        ):
            return
        items[idx], items[target] = items[target], items[idx]
        self._mark_dirty()
        self._select(kind, target)


class MapEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        map_id: str,
        dungeon: bool,
        language: str,
        can_edit: Callable[[], bool],
        on_changed: Callable[[], None] | None = None,
        on_closed: Callable[[], None] | None = None,
        area_kind: str = "farm",
        coord_load: Callable[[], dict | None] | None = None,
        coord_save: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = ui_strings(language)
        self._on_closed = on_closed
        self._area_kind = "safe" if str(area_kind) == "safe" and not dungeon else "farm"
        if dungeon:
            self.setWindowTitle(self.s.edit_patrol)
        elif self._area_kind == "safe":
            self.setWindowTitle(self.s.edit_rest)
        else:
            self.setWindowTitle(self.s.edit_farms)
        self.resize(1000, 700)
        # Non-modal like classic CTkToplevel — avoids nested-exec crashes.
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        layout = QVBoxLayout(self)
        self.editor = MapEditorWidget(
            strings=self.s,
            can_edit=can_edit,
            on_changed=on_changed,
            on_done=self.accept,
            language=language,
            area_kind=self._area_kind,
            coord_load=coord_load,
            coord_save=coord_save,
        )
        layout.addWidget(self.editor)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete),
            self,
            self.editor._delete_selected,
            context=Qt.ShortcutContext.WidgetWithChildrenShortcut,
        )
        self._pending_map = (str(map_id or ""), bool(dungeon))
        self.finished.connect(self._emit_closed)
        # Show first; load map on next tick so a heavy TerrainMap/PIL path
        # cannot freeze construction (looks like a crash / blank window).
        QTimer.singleShot(0, self._load_pending_map)

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            if not self.editor.confirm_close():
                event.ignore()
                return
        except RuntimeError:
            pass
        super().closeEvent(event)

    def _load_pending_map(self) -> None:
        pending = getattr(self, "_pending_map", None)
        if not pending:
            return
        map_id, dungeon = pending
        self._pending_map = None
        try:
            self.editor.load_map(map_id, dungeon=dungeon)
        except Exception as exc:
            self.editor.status.setText(str(exc))

    def _emit_closed(self, _code: int = 0) -> None:
        cb = self._on_closed
        self._on_closed = None
        if cb is not None:
            try:
                cb()
            except Exception:
                pass


def open_map_editor(
    parent: QWidget | None,
    *,
    map_id: str,
    dungeon: bool,
    language: str,
    can_edit: Callable[[], bool],
    on_changed: Callable[[], None] | None = None,
    on_closed: Callable[[], None] | None = None,
    area_kind: str = "farm",
    coord_load: Callable[[], dict | None] | None = None,
    coord_save: Callable[[dict], None] | None = None,
) -> MapEditorDialog:
    dialog = MapEditorDialog(
        parent,
        map_id=map_id,
        dungeon=dungeon,
        language=language,
        can_edit=can_edit,
        on_changed=on_changed,
        on_closed=on_closed,
        area_kind=area_kind,
        coord_load=coord_load,
        coord_save=coord_save,
    )
    # Flags only before the first show — never toggle after (QDialog hide/finished).
    # Stay on top whenever the shell does, so Edit map isn't buried under it.
    flags = (
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowMinMaxButtonsHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    try:
        host = parent.window() if parent is not None else None
        if host is not None and bool(
            host.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        ):
            flags |= Qt.WindowType.WindowStaysOnTopHint
    except RuntimeError:
        pass
    dialog.setWindowFlags(flags)
    dialog.show()
    _raise_map_editor(dialog)
    QTimer.singleShot(0, lambda: _raise_map_editor(dialog))
    QTimer.singleShot(80, lambda: _raise_map_editor(dialog))
    return dialog


def _raise_map_editor(dialog: MapEditorDialog) -> None:
    try:
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()
    except RuntimeError:
        pass
