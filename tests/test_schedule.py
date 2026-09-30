from __future__ import annotations

import json
import inspect
import uuid

from manmabot_v1.paths import USERDATA, ensure_userdata
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleStore
from manmabot_v1.task_runtime import apply_runtime_settings
from manmabot_v1.ui.schedule_i18n import LANGUAGES, TABLE
from manmabot_v1.probes import Lamp, MapProbe
from manmabot_v1.ui.schedule_ui import (
    ScheduleWindow,
    UnifiedTaskEditor,
    _HUNT_PAD,
    _combo_char_width,
    _fit_icon,
    _game_chip_text,
    _hunt_icon_box,
    _hunt_row_height,
    _map_chip_text,
    _memory_chip_text,
    table_name_matches,
)


def test_schedule_atomic_crud_round_trip():
    ensure_userdata()
    path = USERDATA / f"test-schedules-{uuid.uuid4().hex}.json"
    store = ScheduleStore(path)
    try:
        task = store.create(Profile(), "Farm one")
        clone = store.duplicate(task)
        store.save([clone, task])
        loaded = store.load()
        assert [item.name for item in loaded] == ["Farm one copy", "Farm one"]
        assert loaded[0].id != loaded[1].id
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert not list(path.parent.glob(f".{path.name}.*.tmp"))
    finally:
        path.unlink(missing_ok=True)


def test_runtime_adapter_applies_only_supported_profile_fields():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.start_time = "10:00:00"
    task.settings["move"]["map_id"] = "gludio"
    task.settings["recovery"]["escape_hp_below"] = 41
    task.settings["recovery"].pop("hp_actions", None)
    task.settings["equipment"]["arrow_quantity"] = 321
    task.settings["other"]["loot_mode"] = "adena_weighted"
    changed = apply_runtime_settings(task, profile)
    assert profile.active_map == "gludio"
    assert profile.hp_escape_ratio == 0.41
    assert profile.arrow_buy_qty == 321
    assert profile.loot_mode == "all_items"
    assert "start_time" not in changed


def test_header_status_chips_are_short():
    texts = TABLE["ko"]
    assert _game_chip_text("Game window not found", Lamp.RED, texts) == "게임 없음"
    assert _game_chip_text("Game ready", Lamp.GREEN, texts) == "게임"
    assert _game_chip_text("Game window is minimized", Lamp.YELLOW, texts) == "최소화"
    assert _memory_chip_text("Memory monitor disconnected", Lamp.RED, texts) == "모니터 꺼짐"
    assert _memory_chip_text("Memory connected", Lamp.GREEN, texts) == "모니터"
    assert (
        _memory_chip_text("Memory connected — waiting for player data", Lamp.YELLOW, texts)
        == "좌표 대기"
    )
    ready = MapProbe(
        Lamp.GREEN,
        "말하는 섬 · 농장 2곳",
        ["a", "b"],
        map_name="말하는 섬",
    )
    assert _map_chip_text(ready, texts, ["a", "b"]) == "말하는 섬 · 2"
    missing = MapProbe(Lamp.YELLOW, "select", ["a"], map_name="말하는 섬")
    assert _map_chip_text(missing, texts, []) == "농장 없음"
    assert _map_chip_text(MapProbe(Lamp.RED, "missing", []), texts, []) == "맵 없음"


def test_header_map_chip_follows_editor_map_setting():
    """The badge uses the open map setting, not the last applied profile map."""
    from manmabot_v1.probes import probe_map

    texts = TABLE["ko"]
    profile_probe = probe_map(
        ["area_1", "area_3"], map_id="talking_island", language="ko",
    )
    assert profile_probe.map_name == "말하는 섬"
    assert _map_chip_text(profile_probe, texts, ["area_1", "area_3"]) == "말하는 섬 · 2"

    class _Editor:
        task = object()
        _map_ids = {"본토": "mainland"}

        def _map_id(self) -> str:
            return "mainland"

        def _is_dungeon_style(self) -> bool:
            return False

        def _selected_farm_names(self) -> list[str]:
            return ["area_1", "area_3"]

    class _App:
        language = "ko"
        editor = _Editor()

    app = _App()
    found = ScheduleWindow._map_setting_probe(app)
    assert found is not None
    probe, selected = found
    assert probe.map_id == "mainland"
    assert _map_chip_text(probe, texts, selected) == "본토 · 2"
    assert ScheduleWindow._map_setting_probe(app)[0] is probe

    app.editor = type("_Empty", (), {"task": None})()
    assert ScheduleWindow._map_setting_probe(app) is None


def test_schedule_translations_cover_all_labels():
    assert set(LANGUAGES.values()) == {"ko", "zh"}
    assert set(TABLE) == {"en", "ko", "zh"}
    expected = set(TABLE["en"])
    assert all(set(strings) == expected for strings in TABLE.values())
    for language in TABLE:
        assert TABLE[language]["attack_jitter_hint"]
        assert TABLE[language]["target_delay_hint"]
        assert TABLE[language]["target_delay_order"]


def test_draft_fields_round_trip_without_becoming_runtime_timers():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.time_mode = "duration"
    task.duration_minutes = 245
    task.settings["hunt"]["attack_mode"] = "magic"
    task.settings["magic"]["disable_in_combat"] = True
    task.settings["other"]["notes"] = "draft value"
    restored = type(task).from_dict(task.to_dict())
    assert restored.duration_minutes == 245
    assert restored.settings["hunt"]["attack_mode"] == "magic"
    assert restored.settings["magic"]["disable_in_combat"] is True
    assert restored.settings["other"]["notes"] == "draft value"
    changed = apply_runtime_settings(restored, profile)
    assert "duration_minutes" not in changed


def test_buy_portion_does_not_scale_arrow_quantities():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["equipment"]["arrow_quantity"] = 200
    task.settings["equipment"]["silver_arrow_quantity"] = 80
    task.settings["equipment"]["buy_portion"] = 50
    apply_runtime_settings(task, profile)
    assert profile.arrow_buy_qty == 200
    assert profile.silver_arrow_buy_qty == 80


def test_saved_hunt_zones_remain_after_leaving_the_map(monkeypatch):
    """Save, switch maps, and come back — the farm checks must stay saved."""
    import tkinter as tk

    from manmabot_v1.hotkeys import HotkeyManager

    monkeypatch.setattr(HotkeyManager, "bind", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(ScheduleWindow, "_prepare_geometry_before_reveal", lambda self: None)
    monkeypatch.setattr(ScheduleWindow, "_reveal_window", lambda self: None)
    monkeypatch.setattr(ScheduleWindow, "_start_startup_asset_warmup", lambda self: None)
    monkeypatch.setattr(ScheduleWindow, "_poll", lambda self: None)

    path = USERDATA / f"test-schedules-{uuid.uuid4().hex}.json"
    store = ScheduleStore(path)
    window = None
    try:
        task = store.create(Profile(), "zones")
        task.settings["move"]["map_id"] = "mainland"
        task.settings["move"]["map_style"] = "normal"
        task.settings["move"]["selected_farms"] = ["area_1"]
        task.settings["move"]["farm_stays_s"] = {"area_1": 3600.0}
        store.save([task])

        window = ScheduleWindow(profile=Profile(), store=store)
        editor = window.editor
        assert editor._selected_farm_names() == ["area_1"]

        editor._set_farm_checked("area_1", False)
        editor._set_farm_checked("area_4", True)
        editor._farm_stays_s["area_4"] = 1200.0
        editor._refresh_farm_schedule_columns()
        assert editor.commit(confirm_update=False) is True

        saved = store.load()[0]
        assert saved.settings["move"]["selected_farms"] == ["area_4"]
        assert saved.settings["move"]["farm_stays_s"]["area_4"] == 1200.0

        def choose(map_id: str) -> None:
            label = next(
                name for name, mid in editor._map_ids.items() if mid == map_id
            )
            editor.map_var.set(label)
            editor._on_map_combo()

        choose("talking_island")
        assert editor._map_id() == "talking_island"
        choose("mainland")

        assert editor._map_id() == "mainland"
        assert editor._selected_farm_names() == ["area_4"]
        values = editor.farm_tree.item("area_4", "values")
        assert str(values[2]) == "20"
        assert not editor.form_is_dirty()
    finally:
        if window is not None:
            try:
                window._closing = True
                window.destroy()
            except tk.TclError:
                pass
        path.unlink(missing_ok=True)


def test_farm_schedule_order_and_stays_apply_to_profile():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["move"]["selected_farms"] = ["area_3", "area_1"]
    task.settings["move"]["farm_stays_s"] = {"area_3": 1200, "area_1": 480}
    apply_runtime_settings(task, profile)
    assert profile.selected_farms == ["area_3", "area_1"]
    assert profile.farm_stays_s == {"area_3": 1200.0, "area_1": 480.0}


def test_item_pickup_list_applies_to_profile():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["other"]["item_pickup_mode"] = "whitelist"
    task.settings["other"]["item_pickup_names"] = ["아데나", " 아데나", ""]
    apply_runtime_settings(task, profile)
    assert profile.item_pickup_mode == "whitelist"
    assert profile.item_pickup_names == ["아데나"]


def test_unified_ui_has_embedded_editor_and_no_subprocess_navigation():
    assert UnifiedTaskEditor.__mro__[1].__name__ == "Frame"
    source = inspect.getsource(ScheduleWindow)
    assert "subprocess" not in source
    assert "_open_operator" not in source


def test_table_name_matches_filters_monster_and_item_rows() -> None:
    assert table_name_matches("", "monster_오크", "Orc")
    assert table_name_matches("orc", "monster_오크 orc 오크 半兽人")
    assert table_name_matches("오크", "monster_오크 orc 오크 半兽人")
    assert table_name_matches("半兽人", "monster_오크 orc 오크 半兽人")
    assert not table_name_matches("wolf", "monster_오크 orc 오크 半兽人")
    assert table_name_matches("adena", "아데나 adena 金币")
    for language in TABLE:
        assert TABLE[language]["filter_search"]


def test_combo_width_fits_longest_label() -> None:
    assert _combo_char_width(["전체", "허용", "비허용"]) >= 4
    assert _combo_char_width(["Not allowed", "All"]) >= len("Not allowed")


def test_hunt_tables_include_name_search() -> None:
    source = inspect.getsource(UnifiedTaskEditor)
    assert "species_search_var" in source
    assert "item_search_var" in source
    assert "table_name_matches" in source


def test_monster_region_filter_follows_selected_map() -> None:
    assert "self._sync_species_region_to_map()" in inspect.getsource(
        UnifiedTaskEditor._on_map_combo
    )
    assert "self._sync_species_region_to_map()" in inspect.getsource(
        UnifiedTaskEditor._load_maps
    )
    assert "_matching_map_region" in inspect.getsource(
        UnifiedTaskEditor._species_region_choice
    )


def test_hunt_icon_shows_the_full_sprite() -> None:
    from PIL import Image

    sprite = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    for y in range(10, 70):
        for x in range(8, 32):
            sprite.putpixel((x, y), (20, 140, 40, 255))
    box = _hunt_icon_box()
    fitted = _fit_icon(sprite, box)
    assert fitted.size == (box, box)
    left, top, right, bottom = fitted.getbbox()
    assert bottom - top > right - left
    assert abs(top - (box - bottom)) <= 1
    assert abs(left - (box - right)) <= 1
    assert abs(top - _HUNT_PAD) <= 1
    square = Image.new("RGBA", (24, 24), (10, 20, 30, 255))
    even = _fit_icon(square, box)
    sleft, stop, sright, sbottom = even.getbbox()
    assert abs(stop - sleft) <= 1
    assert abs(stop - (box - sbottom)) <= 1
    assert abs(sleft - (box - sright)) <= 1
    assert _hunt_row_height() == box
    metrics = inspect.getsource(ScheduleWindow._apply_scaled_metrics)
    assert "rowheight=_hunt_row_height()" in metrics


def test_hunt_filter_toolbars_share_one_line_layout() -> None:
    monsters = inspect.getsource(UnifiedTaskEditor._build_hunt_monsters)
    items = inspect.getsource(UnifiedTaskEditor._build_hunt_items)
    assert 'text=self.t["sort"]' in monsters
    assert 'text=self.t["filter_show"]' in monsters
    assert 'text=self.t["filter_region"]' in monsters
    assert "region_row" not in monsters
    assert monsters.index('text=self.t["filter_search"]') < monsters.index('text=self.t["sort"]')
    assert items.index('text=self.t["filter_search"]') < items.index('text=self.t["filter_show"]')
    assert items.index('text=self.t["filter_show"]') < items.index('text=self.t["filter_blacklist"]')
    assert items.index('text=self.t["filter_blacklist"]') < items.index('text=self.t["item_pickup_hint"]')
    assert 'heading=self.t["species_image"]' in items
