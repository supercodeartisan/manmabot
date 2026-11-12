"""Party dungeon maps use the field point editor and the party patrol document."""

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

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QTableWidget

from i18n.strings import ui_strings
from settings.party_routine import normalize_party_routine
from settings.profile import Profile
from ui_qt.dialogs.map_editor_dialog import MapEditorWidget
from ui_qt.editors.move_tab import MoveTab
from ui_qt.editors.party_routine_panel import PartyRoutinePanel
from ui_qt.viewmodels.settings_bag import SettingsBag


class _Grid:
    def __init__(self) -> None:
        self.width = 2000
        self.height = 2000

    def is_walkable(self, x: int, y: int) -> bool:
        return 0 <= int(x) < self.width and 0 <= int(y) < self.height

    def can_step(self, x: int, y: int, tx: int, ty: int) -> bool:
        del tx, ty
        return self.is_walkable(x, y)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _image() -> QImage:
    image = QImage(80, 80, QImage.Format.Format_RGB32)
    image.fill(QColor("#888888"))
    return image


def _titles(editor: MapEditorWidget) -> list[str]:
    titles: list[str] = []
    for index in range(editor.item_list.count()):
        item = editor.item_list.item(index)
        widget = editor.item_list.itemWidget(item)
        label = widget.findChild(QLabel) if widget is not None else None
        titles.append(label.text() if label is not None else "")
    return titles


def _party_editor(map_id: str, pack: SimpleNamespace) -> MapEditorWidget:
    _app()
    saved: list[dict] = []
    editor = MapEditorWidget(
        strings=ui_strings("ko"),
        can_edit=lambda: True,
        language="ko",
        coord_save=lambda payload: saved.append(copy.deepcopy(payload)),
    )
    editor._writes = saved
    editor.map_id = map_id
    editor._pack = pack
    editor._dungeon = True
    editor._area_kind = "farm"
    editor.tool = "select"
    editor._terrain = _Grid()
    editor._base = _image()
    editor._sync_tools()
    return editor


def _field_editor(map_id: str, pack) -> MapEditorWidget:
    _app()
    saved: list[dict] = []
    editor = MapEditorWidget(
        strings=ui_strings("ko"),
        can_edit=lambda: True,
        language="ko",
        coord_save=lambda payload: saved.append(copy.deepcopy(payload)),
    )
    editor._writes = saved
    editor.map_id = map_id
    editor._pack = pack
    editor._dungeon = False
    editor._terrain = _Grid()
    editor._base = _image()
    editor._sync_tools()
    return editor


def _pack(root: Path, folder: str, raw_map: str, origin_x: int, origin_y: int) -> SimpleNamespace:
    root.mkdir(parents=True, exist_ok=True)
    (root / "meta.yaml").write_text(
        (
            f"id: {folder}\n"
            f'raw_map: "{raw_map}"\n'
            f"origin_x: {origin_x}\n"
            f"origin_y: {origin_y}\n"
            "pixel_scale: 1\n"
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(
        id=folder,
        root=root,
        origin_x=origin_x,
        origin_y=origin_y,
        pixel_scale=1,
        default_region="",
        terrain_path=root / "missing.png",
    )


def test_field_maps_still_show_point_and_keep_world_coordinates() -> None:
    from session.probes import load_map_pack_safe

    mainland = load_map_pack_safe("mainland")
    island = load_map_pack_safe("talking_island")
    assert mainland is not None and island is not None
    for map_id, pack, world in (
        ("mainland", mainland, "32458, 32148"),
        ("talking_island", island, "32266, 32724"),
    ):
        editor = _field_editor(map_id, pack)
        assert editor._tool_buttons["point"].isHidden() is False
        assert editor._tool_buttons["area"].isHidden() is False
        assert editor._tool_buttons["patrol"].isHidden() is True
        assert editor._tool_buttons["patrol_plus"].isHidden() is True
        editor.farms = [
            {
                "shape": "point",
                "name": "point_1",
                "region": map_id,
                "x": 10,
                "y": 20,
            }
        ]
        editor._refresh_list()
        assert world in _titles(editor)[0]
        assert "분" not in _titles(editor)[0]
        assert editor.save()
        payload = editor._writes[-1]
        assert payload["patrol"] == []
        assert payload["areas"][0]["x"] == 10
        assert payload["areas"][0]["y"] == 20
        assert "game_map_id" not in payload["areas"][0]
        assert "stay_s" not in payload["areas"][0]
        assert "dungeon_plan" not in payload
        editor.hide()


def test_solo_dungeon_keeps_the_original_patrol_button() -> None:
    _app()
    editor = MapEditorWidget(
        strings=ui_strings("ko"),
        can_edit=lambda: True,
        language="ko",
    )
    editor._dungeon = True
    editor._sync_tools()
    assert editor._tool_buttons["patrol"].isHidden() is False
    assert editor._tool_buttons["patrol_plus"].isHidden() is True
    assert editor._tool_buttons["point"].isHidden() is True
    editor.hide()


def test_party_dungeon_keeps_patrol_and_adds_points(tmp_path: Path) -> None:
    folder = "giran_dungeon_F1"
    pack = _pack(tmp_path / folder, folder, "53", 32640, 32640)
    editor = _party_editor(folder, pack)
    editor._routine_minutes = 60
    assert editor._tool_buttons["patrol_plus"].isHidden() is False
    assert editor._tool_buttons["point"].isHidden() is False
    assert editor._tool_buttons["patrol"].isHidden() is True
    assert editor._tool_buttons["area"].isHidden() is True
    assert editor._tool_buttons["save"].isHidden() is False
    assert editor._tool_buttons["reload"].isHidden() is False

    editor._on_patrol_plus()
    editor._drop_patrol_at(10, 20)
    editor._drop_patrol_at(40, 50)
    assert [item["type"] for item in editor._plan] == ["patrol"]
    assert len(editor.patrol) == 2
    editor._nudge_at("patrol", 1, -1)
    assert [(point[0], point[1]) for point in editor.patrol] == [(40, 50), (10, 20)]
    editor.selected = ("patrol", 0)
    editor._delete_selected()
    assert len(editor.patrol) == 1
    assert editor.patrol[0][:2] == (10, 20)

    editor.tool = "point"
    editor._place_stationary(80, 90)
    editor._place_stationary(120, 130)
    editor._on_patrol_plus()
    editor._on_patrol_plus()
    editor._drop_patrol_at(150, 160)
    editor.tool = "point"
    editor._place_stationary(180, 190)
    editor._apply_route_duration(0, 30)
    editor._apply_point_stay(0, 10)
    editor._apply_point_stay(1, 15)
    editor._apply_point_stay(2, 8)

    titles = "\n".join(_titles(editor))
    assert "패트롤 1" in titles
    assert "패트롤 2" in titles
    assert "점 1" in titles
    assert "점 2" in titles
    assert "점 3" in titles
    assert "point_1" not in titles
    assert "30분" in titles
    assert "32720, 32730" in titles

    menu = QMenu()
    delete_act, edit_act = editor._point_menu_actions(menu)
    assert delete_act.text() == "삭제"
    assert edit_act.text() == "좌표편집"
    assert editor._apply_world_to_point(editor.farms[0], "32725", "32735")
    assert (editor.farms[0]["x"], editor.farms[0]["y"]) == (85, 95)

    point_row = next(
        index
        for index, entry in enumerate(editor._plan)
        if entry.get("type") == "point" and entry is editor.farms[2]
    )
    editor.selected = ("plan", point_row)
    editor._delete_selected()
    assert [entry.get("type") for entry in editor._plan].count("point") == 2
    assert [entry.get("type") for entry in editor._plan].count("patrol") == 2

    assert editor.save()
    payload = editor._writes[-1]
    assert "duration_minutes" not in payload
    assert payload["areas"] == []
    assert payload["patrol"][0]["x"] == 10
    assert payload["patrol"][0]["y"] == 20
    assert "game_map_id" not in payload["patrol"][0]
    assert "stay_s" not in payload["patrol"][0]
    plan = payload["dungeon_plan"]
    assert [item["type"] for item in plan] == ["patrol", "point", "point", "patrol"]
    assert plan[0]["duration_s"] == 1800.0
    assert plan[0]["game_map_id"] == 53
    assert plan[0]["pack_id"] == folder
    assert plan[0]["waypoints"][0] == {"x": 10, "y": 20, "name": payload["patrol"][0]["name"]}
    assert [item["game_map_id"] for item in plan] == [53, 53, 53, 53]
    assert plan[1]["stay_s"] == 600.0
    assert plan[1]["x"] == 85
    assert plan[2]["stay_s"] == 900.0
    assert plan[3]["waypoints"][0]["x"] == 150
    assert plan[1]["game_map_id"] != folder

    restored = normalize_party_routine(
        [
            {
                "id": "row",
                "map_id": folder,
                "duration_minutes": 60,
                "coords_saved": True,
                "areas": [],
                "patrol": payload["patrol"],
                "dungeon_plan": payload["dungeon_plan"],
            }
        ]
    )
    assert restored[0]["duration_minutes"] == 60
    reopened = _party_editor(folder, pack)
    reopened._apply_loaded_plan(
        {
            "patrol": restored[0]["patrol"],
            "dungeon_plan": restored[0]["dungeon_plan"],
            "routine_minutes": restored[0]["duration_minutes"],
        }
    )
    reopened._refresh_list()
    again = "\n".join(_titles(reopened))
    assert "패트롤 1" in again and "패트롤 2" in again
    assert "점 1" in again and "점 2" in again
    assert "point_" not in again
    assert reopened._plan[0]["duration_s"] == 1800.0
    assert reopened._plan[1]["stay_s"] == 600.0
    assert reopened._plan[2]["stay_s"] == 900.0
    assert (reopened._plan[1]["x"], reopened._plan[1]["y"]) == (85, 95)
    editor.hide()
    reopened.hide()


def test_legacy_patrol_reloads_as_one_route_without_a_new_document(tmp_path: Path) -> None:
    folder = "cave_legacy"
    pack = _pack(tmp_path / folder, folder, "11", 33000, 33000)
    editor = _party_editor(folder, pack)
    editor._apply_loaded_plan(
        {"patrol": [{"x": 9, "y": 8, "name": "길"}], "routine_minutes": 45}
    )
    editor._refresh_list()
    titles = "\n".join(_titles(editor))
    assert "패트롤 1" in titles
    assert "45분" in titles
    assert "길" in titles
    assert "duration_s" not in editor._plan[0]
    assert editor.save()
    payload = editor._writes[-1]
    assert payload["patrol"] == [{"x": 9, "y": 8, "name": "길"}]
    assert "dungeon_plan" not in payload
    editor.hide()


def test_previous_point_only_save_loads_as_stationary_points(tmp_path: Path) -> None:
    folder = "cave_prev"
    pack = _pack(tmp_path / folder, folder, "74", 34000, 34100)
    editor = _party_editor(folder, pack)
    editor._apply_loaded_plan(
        {
            "patrol": [
                {"x": 4, "y": 5, "name": "mid_1"},
                {
                    "x": 6,
                    "y": 7,
                    "name": "point_1",
                    "stay_s": 480,
                    "game_map_id": 74,
                    "pack_id": folder,
                },
            ]
        }
    )
    editor._refresh_list()
    titles = "\n".join(_titles(editor))
    assert "패트롤 1" in titles
    assert "점 1" in titles
    assert "point_1" not in titles
    assert editor._plan[1]["stay_s"] == 480
    assert (editor._plan[1]["x"], editor._plan[1]["y"]) == (6, 7)
    editor.hide()


def test_two_dungeon_maps_keep_separate_game_map_ids(tmp_path: Path) -> None:
    first = _party_editor(
        "cave_a",
        _pack(tmp_path / "cave_a", "cave_a", "53", 32640, 32640),
    )
    second = _party_editor(
        "cave_b",
        _pack(tmp_path / "cave_b", "cave_b", "11", 33000, 33000),
    )
    first._on_patrol_plus()
    first._drop_patrol_at(1, 2)
    first.tool = "point"
    first._place_stationary(8, 9)
    second._on_patrol_plus()
    second._drop_patrol_at(5, 6)
    second.tool = "point"
    second._place_stationary(20, 21)
    assert first.save() and second.save()
    assert {item["game_map_id"] for item in first._writes[-1]["dungeon_plan"]} == {53}
    assert {item["game_map_id"] for item in second._writes[-1]["dungeon_plan"]} == {11}
    assert first._writes[-1]["dungeon_plan"][0]["pack_id"] == "cave_a"
    assert second._writes[-1]["dungeon_plan"][0]["pack_id"] == "cave_b"
    assert "33020, 33021" in "\n".join(_titles(second))
    first.hide()
    second.hide()


def test_party_setting_shows_plan_durations_and_leaves_the_visit_duration(tmp_path: Path) -> None:
    del tmp_path
    _app()
    profile = Profile()
    bag = SettingsBag(profile)
    panel = PartyRoutinePanel(
        bag=bag,
        profile=profile,
        strings={
            "farm_stay": "체류",
            "minutes": "분",
            "patrol_name": "이름",
            "map_registered_patrol_line": "patrol: {n}",
            "ok": "OK",
        },
        language="ko",
    )
    rows = normalize_party_routine(
        [
            {
                "id": "field",
                "map_id": "mainland",
                "duration_minutes": 40,
                "selected_farms": ["point_1"],
                "farm_stays_s": {"point_1": 600},
                "coords_saved": True,
                "areas": [
                    {
                        "name": "point_1",
                        "shape": "point",
                        "region": "mainland",
                        "x": 10,
                        "y": 20,
                    }
                ],
                "patrol": [],
            },
            {
                "id": "legacy",
                "map_id": "giran_dungeon_F1",
                "duration_minutes": 70,
                "coords_saved": True,
                "areas": [],
                "patrol": [{"x": 1, "y": 2, "name": "mid_1"}],
            },
            {
                "id": "dungeon",
                "map_id": "giran_dungeon_F2",
                "duration_minutes": 90,
                "coords_saved": True,
                "areas": [],
                "patrol": [{"x": 3, "y": 4, "name": "mid_1"}],
                "dungeon_plan": [
                    {
                        "type": "patrol",
                        "id": "patrol_1",
                        "game_map_id": 54,
                        "pack_id": "giran_dungeon_F2",
                        "waypoints": [{"x": 3, "y": 4, "name": "mid_1"}],
                    },
                    {
                        "type": "point",
                        "id": "point_1",
                        "name": "point_1",
                        "x": 8,
                        "y": 9,
                        "stay_s": 900,
                        "game_map_id": 54,
                        "pack_id": "giran_dungeon_F2",
                    },
                ],
            },
        ]
    )
    panel.vm.rows = rows
    panel._persist_routine()
    before = copy.deepcopy(bag.get("party", "routine"))

    panel._edit_setting("legacy")
    legacy_dialog = panel._setting_dialog
    assert legacy_dialog is not None
    legacy_table = legacy_dialog.findChild(QTableWidget)
    assert legacy_table is not None and legacy_table.columnCount() == 2
    legacy_dialog.close()
    _app().processEvents()

    panel._edit_setting("dungeon")
    dialog = panel._setting_dialog
    assert dialog is not None
    table = dialog.findChild(QTableWidget)
    assert table is not None
    assert table.columnCount() == 3
    assert table.item(0, 1).text() == "패트롤 1"
    assert table.item(1, 1).text() == "점 1"
    assert table.item(0, 2).text() == "90분"
    assert table.item(1, 2).text() == "15분"
    panel._set_patrol_stay_minutes(panel._entry("dungeon"), 0, 30)
    dialog.close()
    _app().processEvents()
    stored = bag.get("party", "routine")
    assert stored[0] == before[0]
    assert stored[1]["patrol"] == before[1]["patrol"]
    assert stored[1]["duration_minutes"] == 70
    assert "dungeon_plan" not in stored[1]
    assert stored[2]["duration_minutes"] == 90
    assert stored[2]["dungeon_plan"][0]["duration_s"] == 1800.0
    assert stored[2]["dungeon_plan"][1]["stay_s"] == 900.0
    assert stored[2]["patrol"] == [{"x": 3, "y": 4, "name": "mid_1"}]

    solo = MoveTab(profile=Profile(), strings={}, language="ko", load_profile=False)
    solo.vm.rows = [
        {
            "id": "solo",
            "map_id": "giran_dungeon_F1",
            "kind": "battle",
            "selected_farms": [],
            "farm_stays_s": {},
        }
    ]
    solo._edit_setting("solo")
    solo_table = solo._setting_dialog.findChild(QTableWidget)
    assert solo_table is not None and solo_table.columnCount() == 2
    solo._setting_dialog.close()
    panel.hide()
    solo.hide()
    _app().processEvents()


def _both_dungeon_buttons(editor: MapEditorWidget) -> None:
    assert editor._tool_buttons["patrol_plus"].isHidden() is False
    assert editor._tool_buttons["point"].isHidden() is False
    assert editor._tool_buttons["patrol"].isHidden() is True
    assert editor._tool_buttons["area"].isHidden() is True


def test_patrol_and_point_buttons_stay_visible_across_tools(tmp_path: Path) -> None:
    editor = _party_editor(
        "giran_dungeon_F1",
        _pack(tmp_path / "giran_dungeon_F1", "giran_dungeon_F1", "53", 32640, 32640),
    )
    _both_dungeon_buttons(editor)
    editor._set_tool("patrol")
    _both_dungeon_buttons(editor)
    editor._set_tool("point")
    _both_dungeon_buttons(editor)
    editor._on_patrol_plus()
    _both_dungeon_buttons(editor)
    assert editor.tool == "patrol"
    editor._set_tool("point")
    _both_dungeon_buttons(editor)
    assert editor.tool == "point"
    editor.hide()


def test_legacy_route_survives_points_edits_and_reload(tmp_path: Path) -> None:
    folder = "giran_dungeon_F1"
    editor = _party_editor(folder, _pack(tmp_path / folder, folder, "53", 32640, 32640))
    editor._apply_loaded_plan(
        {
            "patrol": [
                {"x": 10, "y": 20, "name": "mid_1"},
                {"x": 40, "y": 50, "name": "mid_2"},
            ],
            "routine_minutes": 80,
        }
    )
    editor._refresh_list()
    _both_dungeon_buttons(editor)
    assert [(point[0], point[1], point[2]) for point in editor.patrol] == [
        (10, 20, "mid_1"),
        (40, 50, "mid_2"),
    ]

    editor._set_tool("patrol")
    editor._drop_patrol_at(70, 80)
    editor._nudge_at("patrol", 2, -1)
    assert [(point[0], point[1], point[2]) for point in editor.patrol] == [
        (10, 20, "mid_1"),
        (70, 80, "mid_3"),
        (40, 50, "mid_2"),
    ]
    editor.selected = ("patrol", 0)
    editor._delete_selected()
    assert [(point[0], point[1], point[2]) for point in editor.patrol] == [
        (70, 80, "mid_3"),
        (40, 50, "mid_2"),
    ]

    editor._set_tool("point")
    _both_dungeon_buttons(editor)
    editor._place_stationary(100, 110)
    editor._on_patrol_plus()
    _both_dungeon_buttons(editor)
    assert editor.tool == "patrol"
    editor._on_patrol_plus()
    editor._drop_patrol_at(150, 160)
    editor._set_tool("point")
    editor._place_stationary(180, 190)
    editor._apply_route_duration(0, 25)
    editor._apply_point_stay(0, 12)
    editor._apply_point_stay(1, 9)
    assert editor._apply_world_to_point(editor.farms[0], "32750", "32760")

    assert editor.save()
    payload = editor._writes[-1]
    assert "duration_minutes" not in payload
    assert payload["patrol"] == [
        {"x": 70, "y": 80, "name": "mid_3"},
        {"x": 40, "y": 50, "name": "mid_2"},
    ]
    assert [item["type"] for item in payload["dungeon_plan"]] == [
        "patrol",
        "point",
        "patrol",
        "point",
    ]
    assert payload["dungeon_plan"][0]["duration_s"] == 1500.0
    assert payload["dungeon_plan"][0]["waypoints"] == payload["patrol"]
    assert payload["dungeon_plan"][1]["stay_s"] == 720.0
    assert (payload["dungeon_plan"][1]["x"], payload["dungeon_plan"][1]["y"]) == (110, 120)
    assert payload["dungeon_plan"][2]["waypoints"] == [{"x": 150, "y": 160, "name": "mid_1"}]
    assert payload["dungeon_plan"][3]["stay_s"] == 540.0
    assert {item["game_map_id"] for item in payload["dungeon_plan"]} == {53}

    reopened = _party_editor(folder, editor._pack)
    reopened._apply_loaded_plan(
        {
            "patrol": payload["patrol"],
            "dungeon_plan": payload["dungeon_plan"],
            "routine_minutes": 80,
        }
    )
    reopened._refresh_list()
    titles = [line.split("  ")[0] for line in _titles(reopened)]
    assert titles == ["패트롤 1", "중간점 3", "중간점 2", "점 1", "패트롤 2", "점 2"]
    assert "point_" not in titles
    assert reopened._plan[0]["waypoints"] == [
        (70, 80, "mid_3"),
        (40, 50, "mid_2"),
    ]
    assert reopened._plan[0]["duration_s"] == 1500.0
    assert reopened._routine_minutes == 80
    assert reopened._plan[1]["stay_s"] == 720.0
    assert (reopened._plan[1]["x"], reopened._plan[1]["y"]) == (110, 120)
    _both_dungeon_buttons(reopened)
    editor.hide()
    reopened.hide()

