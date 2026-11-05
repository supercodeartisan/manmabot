"""Nested task.settings bag shared by Qt editor tabs (parity with ttk vars)."""

from __future__ import annotations

import copy
from typing import Any, Callable

from settings.profile import Profile, save_profile
from settings.schedule import ScheduleTask, profile_snapshot
from settings.task_runtime import apply_runtime_settings

# Defaults present in ttk UI but not always in profile_snapshot.
_HUNT_UI_DEFAULTS: dict[str, Any] = {
    "prefer_nearest": True,
    "prefer_aggressor": True,
    "prefer_strong": False,
    "prefer_caster": True,
    "exclude_busy": True,
    "stick_target": True,
    "approach_no_engage": False,
    "use_haste_potion": False,
    "haste_potion_item": "",
    "haste_potion_box": 0,
    "haste_potion_key": "",
    "use_antidote_potion": False,
    "antidote_potion_item": "",
    "antidote_potion_box": 0,
    "antidote_potion_key": "",
}

_MAGIC_UI_DEFAULTS: dict[str, Any] = {
    "buff_after_death": True,
    "cast_delay": True,
    "cast_delay_min_ms": 80,
    "cast_delay_max_ms": 180,
    "buff_after_combat": True,
    "town_general_only": True,
}

_PARTY_UI_DEFAULTS: dict[str, Any] = {
    "member_enabled": False,
    "leader_name": "",
    "follow_tiles": 8,
    "stop_tiles": 2,
    "assist_leash_tiles": 10,
    "approach_tiles": 2,
    "potion_hp_ratio": 0.45,
    "random_loot": False,
    "loot_role": "none",
    "loot_priority": "follow",
    "farm_mode": "party",
    "role": "member",
    "ws_port": 8765,
    "leader_host": "",
    "roster": [],
}


class SettingsBag:
    def __init__(self, profile: Profile) -> None:
        self.profile = profile
        self.data: dict[str, dict[str, Any]] = copy.deepcopy(profile_snapshot(profile))
        hunt = self.data.setdefault("hunt", {})
        for key, value in _HUNT_UI_DEFAULTS.items():
            hunt.setdefault(key, value)
        magic = self.data.setdefault("magic", {})
        for key, value in _MAGIC_UI_DEFAULTS.items():
            magic.setdefault(key, value)
        magic.setdefault("skills", {})
        party = self.data.setdefault("party", {})
        for key, value in _PARTY_UI_DEFAULTS.items():
            party.setdefault(key, copy.deepcopy(value))
        self.on_changed: Callable[[], None] | None = None

    def _notify(self) -> None:
        callback = self.on_changed
        if callback is not None:
            callback()

    def section(self, name: str) -> dict[str, Any]:
        return self.data.setdefault(name, {})

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        bucket = self.section(section)
        if key in bucket and bucket[key] == value:
            return
        bucket[key] = value
        self._notify()

    def get_bool(self, section: str, key: str, default: bool = False) -> bool:
        return bool(self.get(section, key, default))

    def get_int(self, section: str, key: str, default: int = 0) -> int:
        try:
            return int(self.get(section, key, default))
        except (TypeError, ValueError):
            return int(default)

    def get_str(self, section: str, key: str, default: str = "") -> str:
        return str(self.get(section, key, default) or default)

    def skill_state(self, setting_key: str) -> dict[str, Any]:
        skills = self.section("magic").setdefault("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            self.section("magic")["skills"] = skills
        # Also accept flat keys written by ttk collect (magic.skill_*).
        flat = self.section("magic")
        enabled = flat.get(f"skill_{setting_key}")
        auto = flat.get(f"skill_{setting_key}_auto")
        priority = flat.get(f"skill_{setting_key}_priority")
        entry = skills.get(setting_key)
        if not isinstance(entry, dict):
            entry = {}
        if enabled is not None:
            entry["enabled"] = bool(enabled)
        if auto is not None:
            entry["auto"] = bool(auto)
        if priority is not None:
            try:
                entry["priority"] = int(priority)
            except (TypeError, ValueError):
                entry["priority"] = 1
        entry.setdefault("enabled", False)
        # The individual-skill checkbox is auto-use. Unset rows stay off;
        # Heal and Teleport are forced on by the magic tab.
        entry.setdefault("auto", False)
        entry.setdefault("priority", 1)
        entry.setdefault("hotkey", "")
        skills[setting_key] = entry
        return entry

    def set_skill_state(self, setting_key: str, **fields: Any) -> None:
        entry = self.skill_state(setting_key)
        entry.update(fields)
        flat = self.section("magic")
        flat[f"skill_{setting_key}"] = bool(entry.get("enabled"))
        flat[f"skill_{setting_key}_auto"] = bool(entry.get("auto", True))
        flat[f"skill_{setting_key}_priority"] = int(entry.get("priority") or 1)
        flat[f"skill_{setting_key}_hotkey"] = str(entry.get("hotkey") or "")
        self._notify()

    def load_task(self, task: ScheduleTask) -> None:
        self.data = copy.deepcopy(getattr(task, "settings", {}) or {})
        for section in (
            "move",
            "hunt",
            "party",
            "recovery",
            "magic",
            "equipment",
            "other",
        ):
            # Keep party even when disk/trial omit it (older TOP_SECTIONS).
            self.data.setdefault(section, {})
        hunt = self.data.setdefault("hunt", {})
        for key, value in _HUNT_UI_DEFAULTS.items():
            hunt.setdefault(key, value)
        magic = self.data.setdefault("magic", {})
        for key, value in _MAGIC_UI_DEFAULTS.items():
            magic.setdefault(key, value)
        magic.setdefault("skills", {})
        party = self.data.setdefault("party", {})
        for key, value in _PARTY_UI_DEFAULTS.items():
            party.setdefault(key, copy.deepcopy(value))

    def apply_to_profile(self) -> list[str]:
        task = ScheduleTask(settings=copy.deepcopy(self.data))
        changed = apply_runtime_settings(task, self.profile)
        save_profile(self.profile)
        return list(changed or [])

    def apply_task(self, task: ScheduleTask) -> list[str]:
        changed = apply_runtime_settings(task, self.profile)
        save_profile(self.profile)
        return list(changed or [])

    def reload_from_profile(self) -> None:
        self.__init__(self.profile)
