"""Qt map editor — farm rects and dungeon patrol points on real-map art."""

from __future__ import annotations

import sys
import time
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QSize, Qt, QPointF, QRectF, QTimer
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
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from i18n.localized_names import route_point_display_name
from i18n.strings import ui_strings
from settings.map_previews import open_real_map_image
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
from ui_qt.theme import tokens

Handle = Optional[str]
_HANDLE_PX = 8
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
    ) -> None:
        super().__init__()
        self._editor = editor
        self._kind = kind
        self._idx = idx
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 1, 6, 1)
        lay.setSpacing(2)
        label = QLabel(title)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(label, stretch=1)
        for up, delta in ((True, -1), (False, 1)):
            btn = _ChevronButton(up=up)
            btn.clicked.connect(
                lambda _=False, d=delta: QTimer.singleShot(
                    0, lambda d=d: editor._nudge_at(kind, idx, d)
                )
            )
            lay.addWidget(btn)
        self.setMinimumHeight(24)
        if kind == "patrol":
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.customContextMenuRequested.connect(self._open_patrol_menu)
        if selected:
            self.setAutoFillBackground(True)
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor("#dbeafe"))
            self.setPalette(pal)

    def _open_patrol_menu(self, pos) -> None:
        idx = self._idx
        global_pos = self.mapToGlobal(pos)
        QTimer.singleShot(0, lambda: self._editor._patrol_row_menu(idx, global_pos))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            kind, idx = self._kind, self._idx
            QTimer.singleShot(0, lambda: self._editor._select(kind, idx))
        super().mousePressEvent(event)


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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.s = strings
        self._can_edit = can_edit
        self._area_kind = "safe" if str(area_kind) == "safe" else "farm"
        self._on_changed = on_changed or (lambda: None)
        self._on_done = on_done or (lambda: None)
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
        self.selected: tuple[str, int] | None = None
        self.tool = "select"
        self._drag: Handle = None
        self._drag_origin: dict | tuple | None = None
        self._rect_anchor: tuple[int, int] | None = None
        self._hover_tile: tuple[int, int] | None = None
        self._hover_move: tuple[int, int] | None = None
        self._live_nav: tuple[int, int] | None = None
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
        self.status = QLabel("")
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
        patrol = self._tool_buttons.get("patrol")
        if patrol is not None:
            patrol.setVisible(self._dungeon)
            patrol.setStyleSheet(
                f"background: {tokens.ACCENT}; color: white;"
                if self._dungeon and self.tool == "patrol"
                else ""
            )
        if hasattr(self, "list_title"):
            self.list_title.setText(self._area_title())
        if hasattr(self, "title_label"):
            self.title_label.setText(self._area_title())

    def _area_title(self) -> str:
        if self._dungeon:
            return self.s.edit_patrol
        if self._area_kind == "safe":
            return self.s.edit_rest
        return self.s.edit_farms

    def _hint(self) -> str:
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
                return terrain
            except Exception:
                pass
        return TerrainMap.from_png(
            pack.terrain_path,
            pixel_scale=max(1, int(pack.pixel_scale)),
        )

    def load_map(self, map_id: str, *, dungeon: bool | None = None) -> None:
        self.map_id = str(map_id or "")
        self._pack = load_map_pack_safe(self.map_id)
        self.selected = None
        self.farms = []
        self.patrol = []
        self._patrol_paths = []
        self._live_nav = None
        self._terrain = None
        self._base = None
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        if dungeon is None:
            self._dungeon = is_dungeon_map_id(self.map_id)
        else:
            self._dungeon = bool(dungeon)
        self.subtitle.setText(
            self.s.editor_hint_dungeon if self._dungeon else self.s.editor_hint_island
        )
        self.tool = "patrol" if self._dungeon else "select"
        self._dirty = False
        self._sync_tools()
        if self._pack is None:
            self.status.setText(self.s.map_missing_short)
            self._refresh_list()
            self._fill_inspector()
            self._sync_canvas_size()
            self.canvas.update()
            return
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
        if not self._dungeon:
            try:
                self._load_farms()
            except Exception:
                self.farms = []
        self.patrol = list_patrol_entries(self.map_id) if self._dungeon else []
        try:
            self._terrain = self._load_terrain_for_editor()
        except Exception:
            self._terrain = None
        self.status.setText(
            self.s.map_missing_short if self._base is None else self._hint()
        )
        try:
            self._recompute_patrol_paths()
        except Exception:
            self._patrol_paths = []
        self._refresh_list()
        self._fill_inspector()
        self._fit()
        self._sync_canvas_size()
        self.canvas.update()

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
            painter.drawText(10, 20, self.s.map_missing_short)
            return
        self._fit()
        iw, ih = self._base.width(), self._base.height()
        dw, dh = max(1, int(iw * self._scale)), max(1, int(ih * self._scale))
        scaled = self._base.scaled(
            dw, dh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation
        )
        ox, oy = self._image_origin()
        painter.drawImage(int(ox), int(oy), scaled)
        ps = self._pixel_scale()
        if not self._dungeon:
            for i, f in enumerate(self.farms):
                x0, y0 = self._tile_to_canvas(f["x0"], f["y0"])
                x1, y1 = self._tile_to_canvas(f["x1"] + 1, f["y1"] + 1)
                selected = self.selected == ("farm", i)
                preview = bool(f.get("_preview"))
                color = QColor(250, 204, 21, 70) if preview else (
                    QColor(29, 111, 232, 80) if selected else QColor(56, 189, 248, 55)
                )
                outline = QColor(202, 138, 4) if preview else QColor(29, 111, 232)
                painter.fillRect(QRectF(x0, y0, x1 - x0, y1 - y0), color)
                painter.setPen(QPen(outline, 2))
                painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                painter.setPen(QColor("#1f2937"))
                painter.drawText(int(x0 + 4), int(max(12, y0 - 4)), str(f["name"]))
                if selected:
                    for hx, hy in self._handle_points(f).values():
                        painter.setBrush(QColor("white"))
                        painter.setPen(QPen(QColor("#1d6fe8"), 2))
                        painter.drawEllipse(QPointF(hx, hy), 5, 5)
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
        if self._hover_tile is not None:
            hx, hy = self._hover_tile
            painter.setPen(QColor("#1e3a5f"))
            hover = self.s.editor_hover.format(x=hx, y=hy)
            if self._live_nav is not None:
                lx, ly = self._live_nav
                hover = f"{hover}  ·  {self.s.editor_you_tile.format(x=lx, y=ly)}"
            painter.drawText(8, max(widget.height() - 10, 16), hover)
        elif self._live_nav is not None:
            lx, ly = self._live_nav
            painter.setPen(QColor("#0e7490"))
            painter.drawText(
                8,
                max(widget.height() - 10, 16),
                self.s.editor_you_tile.format(x=lx, y=ly),
            )
        self.zoom_label.setText(f"{int(round(self._zoom * 100))}%")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_live_timer()

    def hideEvent(self, event) -> None:
        self._stop_live_timer()
        super().hideEvent(event)

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
        except Exception:
            nav = None
        changed = nav != self._live_nav
        self._live_nav = nav
        self._sync_live_anim_timer()
        if changed:
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

    def on_mouse_press(self, event) -> None:
        # Right-click on a farm opens copy / duplicate / rename.
        # Empty ground and middle button pan. Do not reference SpaceModifier.
        if (
            event.button() == Qt.MouseButton.RightButton
            and not self._dungeon
            and self._base is not None
            and self._can_edit()
        ):
            tx, ty = self._canvas_to_tile(event.position().x(), event.position().y())
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
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._can_edit() or self._base is None:
            if self._base is not None and not self._can_edit():
                self.status.setText(self.s.editor_readonly)
            return
        tx, ty = self._canvas_to_tile(event.position().x(), event.position().y())
        if self._dungeon and self.tool == "patrol":
            hit = self._hit_patrol(tx, ty)
            if hit is not None:
                self._select("patrol", hit)
                self._drag = "move"
                self._drag_origin = self.patrol[hit]
                return
            if self._terrain is not None and not self._terrain.is_walkable(tx, ty):
                self.status.setText(self.s.patrol_not_walkable)
                return
            name = f"mid_{len(self.patrol) + 1}"
            self.patrol.append((tx, ty, name))
            self._mark_dirty()
            self._select("patrol", len(self.patrol) - 1)
            return
        if self._dungeon:
            self._deselect()
            return
        hit_f = self._hit_farm(tx, ty)
        if hit_f is not None:
            self._select("farm", hit_f)
            handle = self._hit_handle(
                self.farms[hit_f], event.position().x(), event.position().y()
            )
            self._drag = handle or "move"
            self._drag_origin = dict(self.farms[hit_f])
            self._hover_move = (tx, ty)
            return
        self._rect_anchor = (tx, ty)
        self.selected = None

    def on_mouse_move(self, event) -> None:
        if self._panning:
            self._pan[0] = self._pan_origin[0] + (
                event.position().x() - self._pan_start[0]
            )
            self._pan[1] = self._pan_origin[1] + (
                event.position().y() - self._pan_start[1]
            )
            self.canvas.update()
            return
        if self._base is None:
            return
        tx, ty = self._canvas_to_tile(event.position().x(), event.position().y())
        self._hover_tile = (tx, ty)
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
            if f.get("_preview"):
                continue
            if f["x0"] <= tx <= f["x1"] and f["y0"] <= ty <= f["y1"]:
                return i
        return None

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
        self.tool = "select"
        self._refresh_list()
        self._fill_inspector()
        self.canvas.update()

    def _on_list_row(self, row: int) -> None:
        if row < 0:
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

    def _refresh_list(self) -> None:
        self.item_list.blockSignals(True)
        self.item_list.clear()
        if self._dungeon:
            rows = [
                (route_point_display_name(name, self.language), "patrol", i)
                for i, (_x, _y, name) in enumerate(self.patrol)
            ]
        else:
            rows = [
                (route_point_display_name(str(f["name"]), self.language), "farm", i)
                for i, f in enumerate(self.farms)
                if not f.get("_preview")
            ]
        self.list_count.setText(str(len(rows)))
        for title, kind, idx in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, (kind, idx))
            item.setSizeHint(QSize(self._list_row_width(), 26))
            self.item_list.addItem(item)
            selected = self.selected == (kind, idx)
            self.item_list.setItemWidget(
                item,
                _OrderRow(self, kind, idx, title, selected=selected),
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
            if other.get("_preview"):
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
        if src.get("_preview"):
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
        if kind == "farm" and 0 <= idx < len(self.farms) and not self.farms[idx].get("_preview"):
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
        if self._dungeon:
            self.patrol.clear()
            self._recompute_patrol_paths()
        else:
            self.farms.clear()
        self.selected = None
        self._mark_dirty()
        self._refresh_list()
        self.canvas.update()

    def _nudge_at(self, kind: str, idx: int, delta: int) -> None:
        if not self._can_edit():
            self.status.setText(self.s.editor_readonly)
            return
        items = self.farms if kind == "farm" else self.patrol
        target = idx + int(delta)
        if target < 0 or target >= len(items):
            return
        if kind == "farm" and (
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
