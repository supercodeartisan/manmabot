"""Schedule persistence and profile snapshots.

Time windows are executed by ``schedule_clock`` while Start is armed.
This module only loads and saves the records.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from manmabot_v1.hp_actions import normalize_hp_actions
from manmabot_v1.paths import USERDATA, assert_userdata_write, ensure_userdata
from manmabot_v1.profile import Profile

SCHEDULES_PATH = USERDATA / "schedules.json"
SCHEMA_VERSION = 1
TOP_SECTIONS = ("move", "hunt", "recovery", "magic", "equipment", "other")


def profile_snapshot(profile: Profile) -> dict[str, dict[str, Any]]:
    """Return schedule-shaped settings backed by the existing Profile."""
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
            "return_weight_above": 85,
            "return_no_supplies": True,
            "return_potion_npc": "",
            "return_arrow_npc": "",
            "return_enabled": True,
            "return_hp_enabled": False,
            "return_mp_enabled": bool(getattr(profile, "return_mp_enabled", True)),
            "return_idle_enabled": bool(getattr(profile, "return_idle_enabled", False)),
            "return_idle_seconds": int(getattr(profile, "return_idle_seconds", 60)),
            "return_potion_enabled": True,
            "return_potion_count": 20,
            "return_arrow_enabled": True,
            "return_arrow_count": 300,
            "return_depoison_enabled": False,
            "return_depoison_count": 1,
            "return_satiety_enabled": False,
            "return_satiety_below": 25,
            "return_weight_enabled": True,
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
                getattr(profile, "teleport_surround_count", 4)
            ),
            "hp_actions": normalize_hp_actions(
                getattr(profile, "hp_actions", None),
                potion_pct=round(profile.hp_potion_ratio * 100),
                escape_pct=round(profile.hp_escape_ratio * 100),
                use_heal=bool(getattr(profile, "use_heal", True)),
                use_potion=bool(getattr(profile, "use_hp_potion", True)),
            ),
        },
        "magic": {
            "class": profile.character,
            "spell_slots": copy.deepcopy(profile.spell_slots),
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
        return task

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScheduleStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SCHEDULES_PATH
        self.randomize_enabled = False
        self.randomize_minutes = 0

    def load(self) -> list[ScheduleTask]:
        ensure_userdata()
        self.randomize_enabled = False
        self.randomize_minutes = 0
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return []
            self.randomize_enabled = bool(raw.get("randomize_enabled"))
            self.randomize_minutes = max(0, min(120, int(raw.get("randomize_minutes") or 0)))
            rows = raw.get("tasks", [])
            return [ScheduleTask.from_dict(row) for row in rows if isinstance(row, dict)]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.randomize_enabled = False
            self.randomize_minutes = 0
            return []

    def save(self, tasks: Iterable[ScheduleTask]) -> None:
        ensure_userdata()
        target = assert_userdata_write(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "randomize_enabled": bool(self.randomize_enabled),
            "randomize_minutes": max(0, min(120, int(self.randomize_minutes or 0))),
            "tasks": [task.to_dict() for task in tasks],
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def create(self, profile: Profile, name: str = "New task") -> ScheduleTask:
        return ScheduleTask(name=name, character=profile.character, settings=profile_snapshot(profile))

    def duplicate(self, task: ScheduleTask) -> ScheduleTask:
        clone = ScheduleTask.from_dict(task.to_dict())
        clone.id = uuid.uuid4().hex
        clone.name = f"{task.name} copy"[:80]
        return clone
