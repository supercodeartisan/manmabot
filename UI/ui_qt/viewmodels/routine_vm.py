"""Move-tab routine state (parity with ttk ``UnifiedTaskEditor`` routine helpers)."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from settings.farm_schedule import MAX_ROUTINE_MINUTES, normalize_routine, routine_is_break_only
from session.probes import list_farms_for_map, list_map_choices, list_patrol_entries
from ui.hangul_sort import hangul_sort_key

_FARM_MAP_IDS = frozenset({"talking_island", "mainland"})


class RoutineViewModel:
    """Owns battle/break rows; no Qt imports."""

    def __init__(self, language: str) -> None:
        self.language = language
        self.rows: list[dict[str, Any]] = []
        self.selected_id: str | None = None
        self._map_choices: list[tuple[str, str, bool]] = []
        self._map_labels: dict[str, str] = {}
        self._map_dungeon: dict[str, bool] = {}
        self.reload_catalog()

    def reload_catalog(self) -> None:
        choices = list(list_map_choices(self.language))
        # Pickers show display names — order by Korean jamo, not pack id.
        choices.sort(key=lambda item: hangul_sort_key(item[1]))
        self._map_choices = choices
        self._map_labels = {map_id: label for map_id, label, _flag in choices}
        self._map_dungeon = {map_id: bool(flag) for map_id, _label, flag in choices}

    def load_from_profile(self, profile) -> None:
        routine = normalize_routine(getattr(profile, "routine", None))
        if not routine:
            saved_map = str(getattr(profile, "active_map", "") or "").strip()
            if saved_map:
                farms = [str(name) for name in (getattr(profile, "selected_farms", None) or [])]
                routine = normalize_routine(
                    [
                        {
                            "id": uuid.uuid4().hex,
                            "map_id": saved_map,
                            "kind": "battle",
                            "duration_minutes": 60,
                            "selected_farms": farms,
                            "farm_stays_s": {},
                        }
                    ]
                )
        self.rows = routine
        self.selected_id = self.rows[0]["id"] if self.rows else None

    def load_from_move_settings(self, move: dict[str, Any] | None, profile) -> None:
        move = dict(move or {})
        routine = normalize_routine(move.get("routine"))
        if routine:
            self.rows = routine
            self.selected_id = self.rows[0]["id"] if self.rows else None
            return
        self.load_from_profile(profile)

    def payload(self) -> list[dict[str, Any]]:
        return normalize_routine(copy.deepcopy(self.rows))

    def apply_to_profile(self, profile) -> None:
        rows = self.payload()
        profile.routine = rows
        primary = next((row for row in rows if row.get("kind") == "battle"), None)
        if primary is None and rows:
            primary = rows[0]
        if primary is not None:
            profile.active_map = str(primary.get("map_id") or profile.active_map)
            if not self.is_dungeon(profile.active_map):
                profile.selected_farms = list(primary.get("selected_farms") or [])
            else:
                profile.selected_farms = []
        self.invalidate_selection()

    def invalidate_selection(self) -> None:
        live = {str(row["id"]) for row in self.rows}
        if self.selected_id not in live:
            self.selected_id = self.rows[0]["id"] if self.rows else None

    def map_label(self, map_id: str) -> str:
        return str(self._map_labels.get(map_id) or map_id or "")

    def is_dungeon(self, map_id: str) -> bool:
        map_id = str(map_id or "").strip()
        if not map_id:
            return False
        if map_id in self._map_dungeon:
            return bool(self._map_dungeon[map_id])
        return map_id not in _FARM_MAP_IDS

    def map_choices(self, *, kind: str) -> list[tuple[str, str, bool]]:
        if kind == "break":
            return [item for item in self._map_choices if not item[2]]
        return list(self._map_choices)

    def add_row(self, kind: str, map_id: str) -> str | None:
        kind = "break" if kind == "break" else "battle"
        map_id = str(map_id or "").strip()
        if not map_id:
            return None
        entry = normalize_routine(
            [
                {
                    "id": uuid.uuid4().hex,
                    "map_id": map_id,
                    "kind": kind,
                    "duration_minutes": 60,
                    "selected_farms": [],
                    "farm_stays_s": {},
                }
            ]
        )[0]
        self.rows.append(entry)
        self.selected_id = str(entry["id"])
        return self.selected_id

    def delete_selected(self) -> None:
        if not self.selected_id:
            return
        self.rows = [row for row in self.rows if row["id"] != self.selected_id]
        self.invalidate_selection()

    def move_selected(self, delta: int) -> None:
        if not self.selected_id:
            return
        index = next(
            (i for i, row in enumerate(self.rows) if row["id"] == self.selected_id),
            None,
        )
        if index is None:
            return
        target = index + int(delta)
        if target < 0 or target >= len(self.rows):
            return
        self.rows[index], self.rows[target] = self.rows[target], self.rows[index]

    def set_duration(self, entry_id: str, minutes: int) -> None:
        limited = max(1, min(MAX_ROUTINE_MINUTES, int(minutes)))
        for row in self.rows:
            if row["id"] == entry_id:
                row["duration_minutes"] = limited
                break

    def set_farms(
        self,
        entry_id: str,
        farms: list[str],
        stays: dict[str, float] | None = None,
    ) -> None:
        from settings.farm_schedule import (
            DEFAULT_FARM_STAY_S,
            normalize_farm_stays_s,
            stay_seconds_for,
        )

        cleaned: list[str] = []
        for name in farms:
            text = str(name).strip()
            if text and text not in cleaned:
                cleaned.append(text)
        for row in self.rows:
            if row["id"] == entry_id:
                row["selected_farms"] = cleaned
                if stays is not None:
                    norm = normalize_farm_stays_s(stays)
                    row["farm_stays_s"] = {
                        name: stay_seconds_for(name, norm, DEFAULT_FARM_STAY_S)
                        for name in cleaned
                    }
                else:
                    prev = dict(row.get("farm_stays_s") or {})
                    row["farm_stays_s"] = {
                        name: prev[name] for name in cleaned if name in prev
                    }
                break

    def setting_ready(self, entry: dict[str, Any]) -> bool:
        map_id = str(entry.get("map_id") or "")
        if self.is_dungeon(map_id):
            return len(list_patrol_entries(map_id)) > 0
        return bool(entry.get("selected_farms"))

    def farms_for_map(self, map_id: str) -> list[str]:
        names, _error = list_farms_for_map(map_id)
        return list(names)

    def patrol_count(self, map_id: str) -> int:
        return len(list_patrol_entries(map_id))

    def is_break_only(self) -> bool:
        return routine_is_break_only(self.rows)

    def summary_lines(self, t: dict[str, str]) -> list[str]:
        if not self.rows:
            return [t.get("value_empty", "—")]
        lines: list[str] = []
        for index, entry in enumerate(self.rows, start=1):
            map_id = str(entry.get("map_id") or "")
            dungeon = self.is_dungeon(map_id)
            if entry.get("kind") == "break":
                kind_key = (
                    "routine_type_break_dungeon" if dungeon else "routine_type_break_general"
                )
            else:
                kind_key = (
                    "routine_type_battle_dungeon" if dungeon else "routine_type_battle_general"
                )
            minutes = int(entry.get("duration_minutes") or 60)
            lines.append(
                f"{index}. {self.map_label(map_id)} — {t.get(kind_key, kind_key)} — {minutes}m"
            )
            if dungeon:
                lines.append(
                    "    "
                    + t.get("routine_patrol_line", "patrol: {n}").format(
                        n=self.patrol_count(map_id)
                    )
                )
            else:
                farms = list(entry.get("selected_farms") or [])
                if farms:
                    lines.append("    " + ", ".join(farms))
                else:
                    lines.append("    " + t.get("routine_area_needed", "area needed"))
        return lines
