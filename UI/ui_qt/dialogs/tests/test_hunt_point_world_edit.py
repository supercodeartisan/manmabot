"""Hunting-ground editor shows game world coordinates and edits them in memory."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[4]
for _path in (_ROOT / "UI", _ROOT / "Engine"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMenu

from app._03_world.space.tile_world import clamp_popup_top_left
from i18n.strings import ui_strings
from ui_qt.dialogs.map_editor_dialog import MapEditorWidget
from ui_qt.editors.party_routine_panel import PartyRoutinePanel, PartyRoutineViewModel


class _Grid:
    def __init__(self, blocked: tuple[int, int] | None = None) -> None:
        self.width = 2000
        self.height = 2000
        self.blocked = blocked

    def is_walkable(self, x: int, y: int) -> bool:
        if self.blocked is not None and (int(x), int(y)) == self.blocked:
            return False
        return 0 <= int(x) < self.width and 0 <= int(y) < self.height

    def can_step(self, x: int, y: int, tx: int, ty: int) -> bool:
        del tx, ty
        return self.is_walkable(x, y)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pack() -> SimpleNamespace:
    return SimpleNamespace(
        id="mainland",
        origin_x=32448,
        origin_y=32128,
        pixel_scale=4,
        default_region="mainland",
    )


def _editor() -> MapEditorWidget:
    _app()
    saved: list[dict] = []
    editor = MapEditorWidget(
        strings=ui_strings("ko"),
        can_edit=lambda: True,
        language="ko",
        coord_save=lambda payload: saved.append(copy.deepcopy(payload)),
    )
    editor._writes = saved
    editor.map_id = "mainland"
    editor._pack = _pack()
    editor._dungeon = False
    editor._terrain = _Grid()
    image = QImage(80, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("#888888"))
    editor._base = image
    return editor


def _titles(editor: MapEditorWidget) -> list[str]:
    titles: list[str] = []
    for index in range(editor.item_list.count()):
        item = editor.item_list.item(index)
        widget = editor.item_list.itemWidget(item)
        label = widget.findChild(QLabel) if widget is not None else None
        titles.append(label.text() if label is not None else "")
    return titles


def _point(x: int = 421, y: int = 1143, name: str = "point_1") -> dict:
    return {
        "shape": "point",
        "name": name,
        "region": "mainland",
        "x": x,
        "y": y,
    }


def _show(editor: MapEditorWidget, width: int = 720, height: int = 480) -> None:
    editor.resize(width, height)
    editor.show()
    _app().processEvents()


def test_list_and_hover_show_world_coordinates_without_changing_tiles() -> None:
    editor = _editor()
    area = {
        "shape": "area",
        "name": "area_1",
        "region": "mainland",
        "x0": 421,
        "y0": 1143,
        "x1": 533,
        "y1": 1315,
    }
    point = _point()
    before = (copy.deepcopy(area), copy.deepcopy(point))
    editor.farms = [area, point]
    editor._refresh_list()
    titles = _titles(editor)
    assert "32869, 33271 ~ 32981, 33443" in titles[0]
    assert "32869, 33271" in titles[1]
    assert "421, 1143" not in titles[0]
    assert "421, 1143" not in titles[1]
    assert editor.farms[0] == before[0]
    assert editor.farms[1] == before[1]
    editor._hover_tile = (734, 1317)
    assert editor._map_readout_text().startswith("33182, 33445")
    editor._pack = None
    editor._refresh_list()
    assert "월드좌표를 알 수 없습니다" in _titles(editor)[0]
    assert "421" not in _titles(editor)[0]
    editor.hide()


def test_placing_a_point_stores_the_tile_and_lists_the_world_coordinate() -> None:
    editor = _editor()
    editor._place_point(10, 20)
    assert editor.farms[-1]["x"] == 10
    assert editor.farms[-1]["y"] == 20
    assert "32458, 32148" in _titles(editor)[-1]
    editor.hide()


def test_point_menu_has_delete_and_coordinate_edit() -> None:
    editor = _editor()
    menu = QMenu()
    delete_act, edit_act = editor._point_menu_actions(menu)
    assert delete_act.text() == "삭제"
    assert edit_act.text() == "좌표편집"
    assert edit_act.isEnabled()
    editor._pack = None
    blocked = QMenu()
    _delete_act, disabled = editor._point_menu_actions(blocked)
    assert not disabled.isEnabled()
    assert editor.status.text() == "월드좌표를 알 수 없습니다."
    editor.hide()


def test_coordinate_edit_save_cancel_and_main_save_round_trip() -> None:
    editor = _editor()
    rect = {
        "shape": "area",
        "name": "area_1",
        "region": "mainland",
        "x0": 421,
        "y0": 1143,
        "x1": 533,
        "y1": 1315,
    }
    first = _point()
    second = _point(7, 8, "point_2")
    editor.farms = [rect, first, second]
    editor.selected = ("point", 2)
    _show(editor)
    editor._open_coord_popup(2)
    popup = editor._coord_popup
    assert popup is not None
    assert popup.x_edit.text() == "32455"
    assert popup.y_edit.text() == "32136"
    popup.x_edit.setText("1")
    popup.y_edit.setText("2")
    QTest.keyClick(popup.x_edit, Qt.Key.Key_Escape)
    _app().processEvents()
    assert editor._coord_popup is None
    assert editor.farms[2]["x"] == 7
    assert editor.farms[2]["y"] == 8
    assert editor._writes == []

    editor._open_coord_popup(2)
    popup = editor._coord_popup
    assert popup is not None
    popup.x_edit.setText("32458")
    popup.y_edit.setText("32148")
    QTest.keyClick(popup.y_edit, Qt.Key.Key_Return)
    _app().processEvents()
    assert editor._coord_popup is None
    assert editor.farms[2]["x"] == 10
    assert editor.farms[2]["y"] == 20
    assert editor.farms[2]["name"] == "point_2"
    assert editor.farms[2]["region"] == "mainland"
    assert editor.farms[2]["shape"] == "point"
    assert editor.farms[0]["x0"] == 421
    assert [item["name"] for item in editor.farms] == ["area_1", "point_1", "point_2"]
    assert "32458, 32148" in _titles(editor)[2]
    assert editor._writes == []

    assert editor.save() is True
    payload = editor._writes[-1]
    assert payload["areas"][2] == {
        "name": "point_2",
        "shape": "point",
        "region": "mainland",
        "x": 10,
        "y": 20,
    }
    assert payload["areas"][0]["x0"] == 421
    editor.farms = editor._farms_from_bound(payload)
    editor._refresh_list()
    assert editor.farms[2]["x"] == 10
    assert editor.farms[2]["y"] == 20
    assert "32458, 32148" in _titles(editor)[2]
    editor.hide()


def test_invalid_off_map_and_blocked_coordinates_do_not_move_the_point() -> None:
    editor = _editor()
    editor._terrain = _Grid(blocked=(3, 3))
    editor.farms = [_point()]
    _show(editor)
    editor._open_coord_popup(0)
    popup = editor._coord_popup
    assert popup is not None
    popup.x_edit.setText("nope")
    popup._store()
    assert editor.farms[0]["x"] == 421
    assert editor._coord_popup is popup
    assert editor.status.text() == "월드좌표는 정수여야 합니다."

    popup.x_edit.setText("40000")
    popup.y_edit.setText("40000")
    popup._store()
    assert editor.farms[0]["x"] == 421
    assert editor.status.text() == "이 맵 밖의 좌표입니다."

    popup.x_edit.setText(str(32448 + 3))
    popup.y_edit.setText(str(32128 + 3))
    popup._store()
    assert editor.farms[0]["x"] == 421
    assert editor.farms[0]["y"] == 1143
    assert editor.status.text() == editor.s.hunt_point_refused
    editor.hide()


def test_popup_tracks_the_point_through_pan_zoom_and_closes_on_map_change() -> None:
    editor = _editor()
    editor.farms = [_point(1, 1)]
    _show(editor, 1400, 700)
    editor._open_coord_popup(0)
    popup = editor._coord_popup
    assert popup is not None

    def anchored() -> tuple[int, int]:
        anchor = editor._point_global_anchor(editor.farms[0])
        edges = editor._viewport_global_edges()
        assert anchor is not None and edges is not None
        popup.adjustSize()
        return clamp_popup_top_left(
            anchor.x(),
            anchor.y(),
            popup.width(),
            popup.height(),
            *edges,
        )

    assert (popup.x(), popup.y()) == anchored()
    anchor = editor._point_global_anchor(editor.farms[0])
    edges = editor._viewport_global_edges()
    assert anchor is not None and edges is not None
    editor._pan[0] += (edges[0] + 8) - anchor.x()
    editor._pan[1] += (edges[1] + 8) - anchor.y()
    editor._place_coord_popup()
    anchor = editor._point_global_anchor(editor.farms[0])
    assert anchor is not None
    assert abs(anchor.x() - (edges[0] + 8)) <= 1
    assert abs(anchor.y() - (edges[1] + 8)) <= 1
    assert (popup.x(), popup.y()) == (anchor.x(), anchor.y())

    before = editor._point_global_anchor(editor.farms[0])
    editor._zoom_by(1.15)
    _app().processEvents()
    after = editor._point_global_anchor(editor.farms[0])
    assert before != after
    assert (popup.x(), popup.y()) == anchored()

    editor._pan[0] += 5000
    editor._place_coord_popup()
    _app().processEvents()
    anchor = editor._point_global_anchor(editor.farms[0])
    edges = editor._viewport_global_edges()
    assert anchor is not None and edges is not None
    assert (popup.x(), popup.y()) == anchored()
    assert popup.x() != anchor.x()
    assert edges[0] <= popup.x()
    assert popup.x() + popup.width() - 1 <= edges[2]

    editor.load_map("___missing_pack___")
    assert editor._coord_popup is None
    editor.hide()


def test_deleting_the_open_point_closes_the_popup() -> None:
    editor = _editor()
    editor.farms = [_point(), _point(4, 5, "point_2")]
    editor.selected = ("point", 0)
    _show(editor)
    editor._open_coord_popup(0)
    assert editor._coord_popup is not None
    editor._delete_selected()
    assert editor._coord_popup is None
    assert [item["name"] for item in editor.farms] == ["point_2"]
    editor.hide()


def test_party_labels_show_world_coordinates_and_keep_the_stored_tile() -> None:
    vm = PartyRoutineViewModel("ko", {})
    entry = {
        "map_id": "mainland",
        "coords_saved": True,
        "areas": [_point(), {
            "name": "area_1",
            "shape": "area",
            "region": "mainland",
            "x0": 421,
            "y0": 1143,
            "x1": 533,
            "y1": 1315,
        }],
    }
    before = copy.deepcopy(entry)
    assert vm.farm_summary_label(entry, "point_1") == "점 (32869, 33271)"
    assert vm.farm_summary_label(entry, "area_1") == "구역 (32869, 33271 ~ 32981, 33443)"
    assert entry == before
    rows, err = PartyRoutinePanel._area_details_for(
        SimpleNamespace(t={}),
        "mainland",
        rest=False,
        entry=entry,
    )
    assert err is None
    assert rows[0][1] == "(32869, 33271)"
    assert rows[1][1] == "(32869, 33271 ~ 32981, 33443)"
    assert entry == before
    missing = vm.farm_summary_label(
        {"map_id": "___missing_pack___", "areas": [_point()]},
        "point_1",
    )
    assert missing == "월드좌표 없음"
    assert "421" not in missing
