"""Party-tab routine. Same screen as the solo routine, separate document.

Map art and the shared area catalog are read from the solo map folder.
Saving a patrol or a farm rectangle writes the party row only.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

from PySide6.QtWidgets import QLabel, QWidget

from session.probes import (
    farms_yaml_path,
    list_patrol_entries,
    safe_yaml_path,
)
from settings.farm_schedule import (
    DEFAULT_FARM_STAY_S,
    stay_minutes_from_s,
    stay_s_from_minutes,
)
from settings.party_routine import dungeon_plan_from_document, normalize_party_routine
from ui_qt.editors.move_tab import MoveTab
from ui_qt.i18n_overlay import tx
from ui_qt.viewmodels.routine_vm import RoutineViewModel
from ui_qt.viewmodels.settings_bag import SettingsBag


def shared_area_rects(map_id: str, *, rest: bool) -> list[dict[str, Any]]:
    """Read farm or rest rectangles from the shared map folder. Does not write."""
    import yaml

    path = safe_yaml_path(map_id) if rest else farms_yaml_path(map_id)
    if path is None or not path.is_file():
        return []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    areas = doc.get("areas") or doc.get("safe_areas") or doc.get("farm_areas") or []
    region = ""
    out: list[dict[str, Any]] = []
    if not isinstance(areas, list):
        return []
    for index, item in enumerate(areas):
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                {
                    "name": str(item.get("name") or f"area_{index + 1}"),
                    "region": str(item.get("region") or region),
                    "x0": int(item["x0"]),
                    "y0": int(item["y0"]),
                    "x1": int(item["x1"]),
                    "y1": int(item["y1"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


class PartyRoutineViewModel(RoutineViewModel):
    """Party rows keep their own coordinates. Ready means those coordinates exist."""

    def __init__(self, language: str, strings: dict | None = None) -> None:
        super().__init__(language)
        self.strings = strings or {}

    def payload(self) -> list[dict[str, Any]]:
        return normalize_party_routine(copy.deepcopy(self.rows))

    def _world_unavailable(self) -> str:
        return tx(self.strings, "party_ui_world_unavailable", "월드좌표 없음")

    def _axes_for_map(self, map_id: str):
        from app._03_world.space.tile_world import axes_from_pack
        from session.probes import load_map_pack_safe

        return axes_from_pack(load_map_pack_safe(map_id))

    def farm_summary_label(self, entry: dict[str, Any], name: str) -> str:
        from app._03_world.space.tile_world import stored_world_tuple

        for area in entry.get("areas") or []:
            if not isinstance(area, dict) or str(area.get("name") or "") != name:
                continue
            numbers = stored_world_tuple(
                self._axes_for_map(str(entry.get("map_id") or "")),
                area,
            )
            if numbers is None:
                return self._world_unavailable()
            if len(numbers) == 2:
                return tx(self.strings, "party_ui_point", "점 ({x}, {y})").format(
                    x=numbers[0], y=numbers[1]
                )
            return tx(
                self.strings, "party_ui_area", "구역 ({x0}, {y0} ~ {x1}, {y1})"
            ).format(
                x0=numbers[0],
                y0=numbers[1],
                x1=numbers[2],
                y1=numbers[3],
            )
        return str(name)

    def summary_patrol_count(self, entry: dict[str, Any], map_id: str) -> int:
        if not entry.get("coords_saved"):
            return 0
        return len(entry.get("patrol") or [])

    def setting_ready(self, entry: dict[str, Any]) -> bool:
        map_id = str(entry.get("map_id") or "")
        if not entry.get("coords_saved"):
            return False
        if self.is_dungeon(map_id):
            return len(entry.get("patrol") or []) > 0
        selected = [str(name) for name in (entry.get("selected_farms") or []) if str(name)]
        if not selected:
            return False
        names = {
            str(area.get("name") or "")
            for area in (entry.get("areas") or [])
            if isinstance(area, dict)
        }
        return all(name in names for name in selected)


class PartyRoutinePanel(MoveTab):
    def __init__(
        self,
        *,
        bag: SettingsBag,
        profile,
        strings: dict[str, str],
        language: str,
        on_log: Callable[[str], None] | None = None,
        can_edit_map: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        self.bag = bag
        self._can_edit_map = can_edit_map or (lambda: True)
        self._map_dialog = None
        super().__init__(
            profile=profile,
            strings=strings,
            language=language,
            on_log=on_log,
            on_open_map_editor=None,
            load_profile=False,
            parent=parent,
        )
        self.on_routine_changed = self._persist_routine
        self.setMinimumHeight(320)
        self._hide_top_hint()
        self.load_from_bag()

    def _hide_top_hint(self) -> None:
        hint = str(self.t.get("routine_hint", "") or "")
        if not hint:
            return
        for label in self.findChildren(QLabel):
            if label.text() == hint:
                label.hide()
                break

    def _make_vm(self) -> PartyRoutineViewModel:
        return PartyRoutineViewModel(self.language, self.t)

    def load_from_bag(self) -> None:
        raw = self.bag.get("party", "routine", None)
        self.vm.rows = normalize_party_routine(raw)
        self.vm.selected_id = self.vm.rows[0]["id"] if self.vm.rows else None
        self.refresh()

    def _persist_routine(self) -> None:
        rows = self.vm.payload()
        current = self.bag.get("party", "routine", None)
        if current is None and not rows:
            return
        if current == rows:
            return
        self.bag.set("party", "routine", rows)

    def apply_to_profile(self) -> None:
        """Never write the solo profile routine from this panel."""
        self._persist_routine()

    def reload_from_profile(self) -> None:
        self.load_from_bag()

    def load_from_move_settings(self, move: dict | None, *, inherit_profile: bool = True) -> None:
        self.load_from_bag()

    def _entry(self, entry_id: str) -> dict[str, Any] | None:
        return next((row for row in self.vm.rows if row.get("id") == entry_id), None)

    def _dialog_plan(self, entry: dict) -> list[dict] | None:
        """Plan rows for the setting table. A single legacy route stays a waypoint list."""
        plan = dungeon_plan_from_document(
            {
                "patrol": entry.get("patrol") or [],
                "dungeon_plan": entry.get("dungeon_plan"),
            }
        )
        routes = [item for item in plan if item.get("type") == "patrol"]
        points = [item for item in plan if item.get("type") == "point"]
        stored = isinstance(entry.get("dungeon_plan"), list) and bool(entry.get("dungeon_plan"))
        if stored or points or len(routes) > 1 or any("duration_s" in item for item in routes):
            return plan
        return None

    def _plan_row_title(self, kind: str, number: int) -> str:
        from i18n.strings import ui_strings

        strings = ui_strings(self.vm.language)
        if kind == "patrol":
            return strings.plan_patrol.format(n=number)
        return strings.plan_point.format(n=number)

    def _patrol_entries_for(self, map_id: str, entry: dict) -> list:
        plan = self._dialog_plan(entry)
        if plan is not None:
            rows = []
            patrol_number = 0
            point_number = 0
            for item in plan:
                if item.get("type") == "patrol":
                    patrol_number += 1
                    rows.append((0, 0, self._plan_row_title("patrol", patrol_number)))
                elif item.get("type") == "point":
                    point_number += 1
                    rows.append((0, 0, self._plan_row_title("point", point_number)))
            return rows
        if entry.get("coords_saved"):
            points = []
            for item in entry.get("patrol") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    points.append(
                        (int(item["x"]), int(item["y"]), str(item.get("name") or ""))
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            return points
        return list_patrol_entries(map_id)

    def _shows_patrol_stay(self, entry: dict | None = None) -> bool:
        return entry is not None and self._dialog_plan(entry) is not None

    def _ensure_dialog_plan(self, entry: dict) -> list[dict]:
        plan = entry.get("dungeon_plan")
        if isinstance(plan, list) and plan:
            return plan
        plan = self._dialog_plan(entry) or []
        entry["dungeon_plan"] = plan
        return plan

    def _patrol_stay_minutes(self, entry: dict, index: int) -> int:
        plan = self._dialog_plan(entry) or []
        if not (0 <= index < len(plan)):
            return self._routine_default_minutes(entry)
        item = plan[index]
        if item.get("type") == "patrol":
            if "duration_s" in item:
                return stay_minutes_from_s(item["duration_s"])
            return self._routine_default_minutes(entry)
        if "stay_s" in item:
            return stay_minutes_from_s(item["stay_s"])
        return stay_minutes_from_s(DEFAULT_FARM_STAY_S)

    def _routine_default_minutes(self, entry: dict) -> int:
        try:
            minutes = int(entry.get("duration_minutes"))
        except (TypeError, ValueError):
            minutes = stay_minutes_from_s(DEFAULT_FARM_STAY_S)
        return stay_minutes_from_s(max(1, minutes) * 60)

    def _set_patrol_stay_minutes(self, entry: dict, index: int, minutes: int) -> None:
        plan = self._ensure_dialog_plan(entry)
        if not (0 <= index < len(plan)):
            return
        item = plan[index]
        if item.get("type") == "patrol":
            item["duration_s"] = stay_s_from_minutes(minutes)
            return
        if item.get("type") == "point":
            item["stay_s"] = stay_s_from_minutes(minutes)

    def _edit_setting(self, entry_id: str) -> None:
        entry = self._entry(entry_id)
        if entry is not None and self.vm.is_dungeon(str(entry.get("map_id") or "")):
            self._snapshot_setting(entry_id)
        super()._edit_setting(entry_id)

    def _farm_choice_label(self, name: str, note: str, index: int) -> str:
        if str(name).startswith("point_"):
            return tx(self.t, "party_ui_point_row", "{index}. 점  {note}").format(
                index=index, note=note
            ).strip()
        if str(name).startswith("area_") or " ~ " in str(note):
            return tx(self.t, "party_ui_area_row", "{index}. 구역  {note}").format(
                index=index, note=note
            ).strip()
        if note:
            return f"{index}. {name}  {note}".strip()
        return f"{index}. {name}"

    def _area_details_for(self, map_id: str, *, rest: bool, entry: dict):
        from app._03_world.space.tile_world import axes_from_pack, stored_world_note
        from session.probes import load_map_pack_safe

        if entry.get("coords_saved"):
            areas = [
                area
                for area in (entry.get("areas") or [])
                if isinstance(area, dict) and area.get("name")
            ]
        else:
            areas = shared_area_rects(map_id, rest=rest)
        axes = axes_from_pack(load_map_pack_safe(map_id))
        unavailable = tx(self.t, "party_ui_world_unavailable", "월드좌표 없음")
        rows = [
            (str(area["name"]), stored_world_note(axes, area, unavailable=unavailable))
            for area in areas
        ]
        if not areas and axes is None and not entry.get("coords_saved"):
            return [], "Map pack could not be loaded."
        return rows, None

    def _snapshot_setting(self, entry_id: str) -> None:
        """Copy the shared map's current areas into this row once.

        Later edits stay on the party row. The shared yaml is not written.
        """
        entry = self._entry(entry_id)
        if entry is None or entry.get("coords_saved"):
            return
        map_id = str(entry.get("map_id") or "")
        dungeon = self.vm.is_dungeon(map_id)
        rest = str(entry.get("kind") or "") == "break" and not dungeon
        if dungeon:
            entry["patrol"] = [
                {"x": int(x), "y": int(y), "name": str(name)}
                for x, y, name in list_patrol_entries(map_id)
            ]
            entry["areas"] = []
        else:
            entry["areas"] = shared_area_rects(map_id, rest=rest)
            entry["patrol"] = []
        entry["coords_saved"] = True

    def _launch_map_editor(
        self,
        map_id: str,
        *,
        dungeon: bool,
        area_kind: str,
        on_closed,
        entry_id: str,
        host: QWidget,
    ) -> None:
        from ui_qt.dialogs.map_editor_dialog import open_map_editor

        existing = self._map_dialog
        if existing is not None:
            try:
                if existing.isVisible():
                    existing.close()
            except RuntimeError:
                pass
            self._map_dialog = None

        rest = area_kind == "safe" and not dungeon

        def _load() -> dict | None:
            entry = self._entry(entry_id)
            if entry is None or not entry.get("coords_saved"):
                return None
            loaded = {
                "areas": copy.deepcopy(entry.get("areas") or []),
                "patrol": copy.deepcopy(entry.get("patrol") or []),
                "routine_minutes": entry.get("duration_minutes"),
            }
            if isinstance(entry.get("dungeon_plan"), list):
                loaded["dungeon_plan"] = copy.deepcopy(entry.get("dungeon_plan") or [])
            return loaded

        def _save(payload: dict) -> None:
            entry = self._entry(entry_id)
            if entry is None:
                return
            if dungeon:
                entry["patrol"] = list(payload.get("patrol") or [])
                entry["areas"] = []
                if "dungeon_plan" in payload:
                    entry["dungeon_plan"] = list(payload.get("dungeon_plan") or [])
                else:
                    entry.pop("dungeon_plan", None)
            else:
                entry["areas"] = list(payload.get("areas") or [])
                entry["patrol"] = []
            entry["coords_saved"] = True
            self._persist_routine()
            self.refresh()

        self._map_dialog = open_map_editor(
            self.window(),
            map_id=map_id,
            dungeon=dungeon,
            language=self.vm.language,
            can_edit=self._can_edit_map,
            on_changed=on_closed,
            on_closed=on_closed,
            area_kind="safe" if rest else "farm",
            coord_load=_load,
            coord_save=_save,
        )
