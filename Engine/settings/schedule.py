"""Schedule persistence and profile snapshots.

Disk layout (ops v1): ``UserData/schedules/{id}/{meta,settings,routine}.json``
plus ``timeline.json``. ``ScheduleTask`` remains the UI/clock compat shape
(settings may embed ``move.routine``; timing fields mirror timeline entries).
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from settings.farm_schedule import normalize_routine
from settings.hp_actions import normalize_hp_actions
from settings.spell_defaults import spell_slot_bindings
from session.paths import (
    LEGACY_SCHEDULES_PATH,
    SCHEDULES_DIR,
    USERDATA,
    assert_userdata_write,
    atomic_write_json,
    ensure_userdata,
    schedule_dir,
)
from settings.profile import Profile
from settings.settings_sections import (
    TOP_SECTIONS,
    merge_settings_routine,
    normalize_settings,
    read_json_list,
    read_json_object,
    split_settings_routine,
)

# Legacy path kept for migrate/tests; runtime uses SCHEDULES_DIR.
SCHEDULES_PATH = LEGACY_SCHEDULES_PATH
SCHEMA_VERSION = 2


def profile_snapshot(profile: Profile) -> dict[str, dict[str, Any]]:
    """Return schedule-shaped settings backed by the existing Profile."""
    from settings.profile import (
        DEFAULT_RETURN_WEIGHT_ABOVE,
        snap_return_weight_above,
    )

    return_weight_above = snap_return_weight_above(
        getattr(profile, "return_weight_above", DEFAULT_RETURN_WEIGHT_ABOVE),
        DEFAULT_RETURN_WEIGHT_ABOVE,
    )
    return {
        "move": {
            "map_id": profile.active_map,
            "map_style": (
                "dungeon"
                if str(getattr(profile, "map_style", "normal")).strip().lower()
                == "dungeon"
                else "normal"
            ),
            "selected_farms": list(profile.selected_farms),
            "farm_rotate_s": profile.farm_rotate_s,
            "farm_stays_s": dict(getattr(profile, "farm_stays_s", {}) or {}),
            "hunt_route": "",
            "hunt_radius": 5,
            "transit_route": "",
        },
        "hunt": {
            "attack_mode": "ranged",
            "attack_range": 16,
            "keep_distance": True,
            "keep_distance_tiles": 3,
            "close_attack": False,
            "mp_spell_enabled": False,
            "mp_spell_above": 80,
            "spell_count": 1,
            "ranged_count": 1,
            "fallback_melee": False,
            "fallback_mp_below": 20,
            "return_hp_below": round(getattr(profile, "return_hp_ratio", profile.hp_escape_ratio) * 100),
            "return_mp_below": round(getattr(profile, "return_mp_ratio", profile.mp_escape_ratio) * 100),
            "return_weight_above": return_weight_above,
            "return_no_supplies": True,
            "return_potion_npc": "",
            "return_arrow_npc": "",
            "return_enabled": True,
            "return_hp_enabled": False,
            "return_mp_enabled": bool(getattr(profile, "return_mp_enabled", True)),
            "return_idle_enabled": bool(getattr(profile, "return_idle_enabled", False)),
            "return_idle_seconds": int(getattr(profile, "return_idle_seconds", 60)),
            "return_potion_enabled": bool(
                getattr(profile, "return_potion_enabled", True)
            ),
            "return_potion_count": int(getattr(profile, "return_potion_count", 20)),
            "return_arrow_enabled": bool(getattr(profile, "return_arrow_enabled", True)),
            "return_arrow_count": int(getattr(profile, "return_arrow_count", 300)),
            "return_depoison_enabled": bool(
                getattr(profile, "return_depoison_enabled", False)
            ),
            "return_depoison_count": int(
                getattr(profile, "return_depoison_count", 1)
            ),
            "return_satiety_enabled": False,
            "return_satiety_below": 25,
            "return_weight_enabled": bool(
                getattr(profile, "return_weight_enabled", True)
            ),
            "return_then_resume": True,
            "recover_before_hunt": True,
            "species_levels": dict(profile.species_levels),
            "species_blacklist": list(profile.species_blacklist),
            "species_filter_mode": getattr(profile, "species_filter_mode", "blacklist"),
            "species_whitelist": list(getattr(profile, "species_whitelist", []) or []),
            "species_sort": profile.species_sort,
            "attack_jitter": bool(getattr(profile, "attack_jitter", False)),
            "attack_jitter_ms": max(10, min(50, int(getattr(profile, "attack_jitter_ms", 35)))),
            "target_delay": bool(getattr(profile, "target_delay", False)),
            "target_delay_min_ms": max(10, min(50, int(getattr(profile, "target_delay_min_ms", 20)))),
            "target_delay_max_ms": max(10, min(50, int(getattr(profile, "target_delay_max_ms", 50)))),
            "use_haste_potion": bool(getattr(profile, "use_haste_potion", False)),
            "haste_potion_item": str(getattr(profile, "haste_potion_item", "") or ""),
            "haste_potion_box": int(getattr(profile, "haste_potion_box", 0) or 0),
            "haste_potion_key": str(getattr(profile, "haste_potion_key", "") or ""),
            "use_antidote_potion": bool(getattr(profile, "use_antidote_potion", False)),
            "antidote_potion_item": str(getattr(profile, "antidote_potion_item", "") or ""),
            "antidote_potion_box": int(getattr(profile, "antidote_potion_box", 0) or 0),
            "antidote_potion_key": str(getattr(profile, "antidote_potion_key", "") or ""),
            "abandon_same": bool(getattr(profile, "abandon_same", False)),
            "abandon_seconds": int(getattr(profile, "abandon_seconds", 30)),
            "antidote_auto": bool(getattr(profile, "antidote_auto", False)),
            "area_empty": bool(getattr(profile, "area_empty", False)),
            "area_empty_seconds": int(getattr(profile, "area_empty_seconds", 60)),
            "area_low_yield": bool(getattr(profile, "area_low_yield", False)),
            "area_low_yield_adena": int(getattr(profile, "area_low_yield_adena", 1000)),
            "area_low_yield_seconds": int(getattr(profile, "area_low_yield_seconds", 180)),
            "area_players": bool(getattr(profile, "area_players", False)),
            "area_player_count": int(getattr(profile, "area_player_count", 3)),
        },
        "recovery": {
            "use_hp_potion": True,
            "use_heal": True,
            "hp_potion_below": round(profile.hp_potion_ratio * 100),
            "recovery_enabled": True,
            "hp_recover_enabled": True,
            "mp_recover_enabled": False,
            "mp_potion_below": 30,
            "use_mp_potion": False,
            "escape_hp_below": round(profile.hp_escape_ratio * 100),
            "escape_mp_enabled": False,
            "resume_after_relogin": True,
            "resurrect_if_dead": True,
            "max_retries": 3,
            "mother_tree_hp_to_mp_enabled": bool(
                getattr(profile, "mother_tree_hp_to_mp_enabled", True)
            ),
            "mother_tree_hp_to_mp_hp": round(
                float(getattr(profile, "mother_tree_hp_to_mp_hp_ratio", 0.85)) * 100
            ),
            "mother_tree_hp_to_mp_mp": round(
                float(getattr(profile, "mother_tree_hp_to_mp_mp_ratio", 0.80)) * 100
            ),
            "mother_tree_heal_enabled": bool(
                getattr(profile, "mother_tree_heal_enabled", True)
            ),
            "mother_tree_heal_hp": round(
                float(getattr(profile, "mother_tree_heal_hp_ratio", 0.40)) * 100
            ),
            "mother_tree_heal_mp": round(
                float(getattr(profile, "mother_tree_heal_mp_ratio", 0.80)) * 100
            ),
            "random_teleport_enabled": bool(
                getattr(profile, "random_teleport_enabled", False)
            ),
            "teleport_hp_enabled": True,
            "random_teleport_hp_below": 20,
            "teleport_on_player": bool(getattr(profile, "teleport_on_player", False)),
            "teleport_when_surrounded": bool(
                getattr(profile, "teleport_when_surrounded", False)
            ),
            "teleport_surround_count": int(
                getattr(profile, "teleport_surround_count", 10)
            ),
            "hp_actions": normalize_hp_actions(
                getattr(profile, "hp_actions", None),
                potion_pct=round(profile.hp_potion_ratio * 100),
                heal_pct=round(float(getattr(profile, "hp_heal_ratio", 0.70)) * 100),
                escape_pct=round(profile.hp_escape_ratio * 100),
                use_heal=bool(getattr(profile, "use_heal", True)),
                use_potion=bool(getattr(profile, "use_hp_potion", True)),
            ),
        },
        "magic": {
            "class": profile.character,
            "spell_slots": spell_slot_bindings(profile.spell_slots),
            "hotbar_layout": copy.deepcopy(profile.hotbar_layout),
            "heal_until_hp_pct": round(profile.heal_until_hp_ratio * 100),
            "spell_reserve_pct": round(profile.spell_reserve_ratio * 100),
            "disable_in_combat": False,
            "stop_below_mp": False,
            "stop_below_mp_pct": 20,
            "skills": {},
        },
        "equipment": {
            "buy_arrows": True,
            "buy_normal_arrows": True,
            "buy_silver_arrows": False,
            "arrow_quantity": profile.arrow_buy_qty,
            "silver_arrow_quantity": getattr(profile, "silver_arrow_buy_qty", profile.arrow_buy_qty),
            "buy_portion": getattr(profile, "hp_potion_buy_qty", 100),
            "buy_depoison": bool(getattr(profile, "buy_depoison", False)),
            "depoison_quantity": getattr(profile, "depoison_buy_qty", 1),
            "hp_potion_npc": str(getattr(profile, "hp_potion_npc", "") or ""),
            "sell_mode": "sell_except_keep",
            "sell_npc": "",
            "store_after_sell": False,
            "warehouse_npc": "",
            "repair_equipment": True,
            "restock_potions": True,
            "equip_profile": "Default",
            "use_potion_on_pickup": True,
            "minimize_combat_during_loot": True,
        },
        "other": {
            "loot_mode": profile.loot_mode,
            "loot_adena_weight_pct": round(profile.loot_adena_weight_ratio * 100),
            "ignore_small_adena": bool(getattr(profile, "ignore_small_adena", False)),
            "ignore_small_adena_qty": int(getattr(profile, "ignore_small_adena_qty", 10)),
            "item_pickup_mode": getattr(profile, "item_pickup_mode", "all"),
            "item_pickup_names": list(getattr(profile, "item_pickup_names", []) or []),
            "game_language": profile.game_language,
            "humanize": profile.humanize,
            "show_preview": False,
            "notes": "",
        },
    }


@dataclass
class ScheduleTask:
    name: str = "New task"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    enabled: bool = True
    account_id: str | None = None
    server: str = ""
    character_slot: int = 1
    character: str = "mage"
    role: str = ""
    start_time: str = "00:00:00"
    end_time: str = "23:59:59"
    duration_minutes: int = 90
    time_mode: str = "window"
    repeat_daily: bool = True
    weekdays: list[int] = field(default_factory=lambda: list(range(7)))
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScheduleTask":
        known = cls.__dataclass_fields__
        values = {key: copy.deepcopy(value) for key, value in raw.items() if key in known}
        task = cls(**values)
        task.id = str(task.id or uuid.uuid4().hex)
        task.name = str(task.name or "New task").strip()[:80]
        task.character_slot = max(1, min(10, int(task.character_slot or 1)))
        task.duration_minutes = max(1, min(10080, int(task.duration_minutes or 90)))
        task.time_mode = task.time_mode if task.time_mode in ("window", "duration") else "window"
        task.weekdays = sorted({int(day) for day in task.weekdays if 0 <= int(day) <= 6})
        task.settings = {
            section: dict(task.settings.get(section, {}))
            for section in TOP_SECTIONS
        }
        move = task.settings["move"]
        if "routine" in move:
            move["routine"] = normalize_routine(move.get("routine"))
        hunt = task.settings["hunt"]
        recovery = task.settings["recovery"]
        for key in ("random_teleport_enabled", "random_teleport_hp_below"):
            if key in hunt and key not in recovery:
                recovery[key] = hunt.pop(key)
        equipment = task.settings["equipment"]
        old_arrow_type = str(equipment.pop("arrow_type", "")).lower()
        if old_arrow_type and "buy_normal_arrows" not in equipment:
            equipment["buy_normal_arrows"] = old_arrow_type == "normal"
        if old_arrow_type and "buy_silver_arrows" not in equipment:
            equipment["buy_silver_arrows"] = old_arrow_type == "silver"
        magic = task.settings["magic"]
        if "spell_slots" in magic:
            magic["spell_slots"] = spell_slot_bindings(magic.get("spell_slots"))
        return task

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        magic = data.get("settings", {}).get("magic")
        if isinstance(magic, dict) and "spell_slots" in magic:
            magic["spell_slots"] = spell_slot_bindings(magic.get("spell_slots"))
        return data


def _load_schedule_task_from_dir(root: Path, timeline_entry: Any | None) -> ScheduleTask | None:
    meta = read_json_object(root / "meta.json") or {}
    settings = read_json_object(root / "settings.json") or {}
    routine = read_json_list(root / "routine.json")
    if routine is None:
        settings_n, routine = split_settings_routine(settings)
    else:
        settings_n = normalize_settings(settings)
        routine = normalize_routine(routine)
    sid = str(meta.get("id") or root.name).strip()
    if not sid or sid.startswith("."):
        return None
    if str(meta.get("role") or "") == "preset":
        # Named presets are not timeline schedules; skip list unless needed later.
        return None
    embedded = merge_settings_routine(settings_n, routine)
    raw: dict[str, Any] = {
        "id": sid,
        "name": meta.get("name") or sid,
        "enabled": bool(meta.get("enabled", True)),
        "account_id": meta.get("account_id"),
        "server": meta.get("server") or "",
        "character_slot": meta.get("character_slot") or 1,
        "character": meta.get("character") or "mage",
        "role": meta.get("role") or "",
        "settings": embedded,
    }
    if timeline_entry is not None:
        raw.update(
            {
                "enabled": bool(timeline_entry.enabled),
                "time_mode": timeline_entry.time_mode,
                "start_time": timeline_entry.start_time,
                "end_time": timeline_entry.end_time,
                "duration_minutes": timeline_entry.duration_minutes,
                "weekdays": list(timeline_entry.weekdays),
                "repeat_daily": bool(timeline_entry.repeat_daily),
            }
        )
    return ScheduleTask.from_dict(raw)


def _write_schedule_dir(task: ScheduleTask) -> None:
    sid = str(task.id or "").strip() or uuid.uuid4().hex
    task.id = sid
    root = schedule_dir(sid)
    root.mkdir(parents=True, exist_ok=True)
    settings, routine = split_settings_routine(task.settings)
    meta = {
        "id": sid,
        "name": str(task.name or "New task")[:80],
        "enabled": bool(task.enabled),
        "account_id": task.account_id,
        "character": str(task.character or "mage"),
        "character_slot": max(1, min(10, int(task.character_slot or 1))),
        "server": str(task.server or ""),
        "role": str(task.role or ""),
    }
    atomic_write_json(assert_userdata_write(root / "meta.json"), meta)
    atomic_write_json(assert_userdata_write(root / "settings.json"), settings)
    atomic_write_json(assert_userdata_write(root / "routine.json"), routine)


class ScheduleStore:
    """Loads/saves schedules under ``UserData/schedules/`` + ``timeline.json``.

    ``path`` is ignored for the new layout (kept for call-site compat).
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SCHEDULES_PATH
        self.randomize_enabled = False
        self.randomize_minutes = 0

    def load(self) -> list[ScheduleTask]:
        from settings.ops_migrate import ensure_ops_layout
        from settings.timeline import load_timeline

        ensure_ops_layout()
        timeline = load_timeline()
        self.randomize_enabled = bool(timeline.randomize_enabled)
        self.randomize_minutes = int(timeline.randomize_minutes or 0)
        tasks: list[ScheduleTask] = []
        if not SCHEDULES_DIR.is_dir():
            return tasks
        # Prefer timeline order; then any schedule dirs not on the timeline.
        seen: set[str] = set()
        for entry in timeline.entries:
            root = schedule_dir(entry.schedule_id)
            if not root.is_dir():
                continue
            task = _load_schedule_task_from_dir(root, entry)
            if task is None:
                continue
            tasks.append(task)
            seen.add(task.id)
        for root in sorted(SCHEDULES_DIR.iterdir(), key=lambda p: p.name):
            if not root.is_dir() or root.name in seen or root.name.startswith("_preset_"):
                continue
            task = _load_schedule_task_from_dir(root, None)
            if task is None:
                continue
            tasks.append(task)
        return tasks

    def save(self, tasks: Iterable[ScheduleTask]) -> None:
        from settings.ops_migrate import ensure_ops_layout
        from settings.timeline import (
            TimelineDocument,
            replace_entries_from_tasks,
            save_timeline,
        )

        ensure_ops_layout()
        task_list = list(tasks)
        keep_ids: set[str] = set()
        for task in task_list:
            _write_schedule_dir(task)
            keep_ids.add(str(task.id))
        # Remove obsolete schedule dirs (keep _preset_*).
        if SCHEDULES_DIR.is_dir():
            for root in list(SCHEDULES_DIR.iterdir()):
                if not root.is_dir():
                    continue
                if root.name.startswith("_preset_"):
                    continue
                if root.name not in keep_ids:
                    for child in root.glob("*"):
                        try:
                            child.unlink()
                        except OSError:
                            pass
                    try:
                        root.rmdir()
                    except OSError:
                        pass
        doc = TimelineDocument(
            randomize_enabled=bool(self.randomize_enabled),
            randomize_minutes=max(0, min(120, int(self.randomize_minutes or 0))),
        )
        replace_entries_from_tasks(doc, task_list)
        save_timeline(doc)

    def create(self, profile: Profile, name: str = "New task") -> ScheduleTask:
        snap = profile_snapshot(profile)
        if getattr(profile, "routine", None):
            snap = merge_settings_routine(snap, profile.routine)
        return ScheduleTask(
            name=name, character=profile.character, settings=snap
        )

    def duplicate(self, task: ScheduleTask) -> ScheduleTask:
        clone = ScheduleTask.from_dict(task.to_dict())
        clone.id = uuid.uuid4().hex
        clone.name = f"{task.name} copy"[:80]
        return clone
