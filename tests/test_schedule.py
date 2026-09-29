from __future__ import annotations

import json
import inspect
import uuid

from manmabot_v1.paths import USERDATA, ensure_userdata
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleStore
from manmabot_v1.task_runtime import apply_runtime_settings
from manmabot_v1.ui.schedule_i18n import LANGUAGES, TABLE
from manmabot_v1.ui.schedule_ui import (
    ScheduleWindow,
    UnifiedTaskEditor,
    _combo_char_width,
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


def test_schedule_translations_cover_all_labels():
    assert set(LANGUAGES.values()) == {"en", "ko", "zh"}
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
