"""Party leader decide loop.

The session calls :meth:`PartyLeaderManager.decide` instead of calling
``DecisionManager`` itself. This module does not change the solo brain.
The routine it installs is the party document. ``profile.routine`` stays
with a solo run.
"""
from __future__ import annotations

from typing import Any

from settings.party_routine import normalize_party_routine


def _rect(area: dict[str, Any]) -> dict[str, Any] | None:
    """One party mark as a rectangle the existing farm reader already accepts.

    A point is a one-tile rectangle on that coordinate. The solo reader is
    not taught a new shape.
    """
    name = str(area.get("name") or "").strip()
    if not name:
        return None
    region = str(area.get("region") or "")
    if str(area.get("shape") or "") == "point":
        try:
            x = int(area["x"])
            y = int(area["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"name": name, "region": region, "x0": x, "y0": y, "x1": x, "y1": y}
    try:
        return {
            "name": name,
            "region": region,
            "x0": int(area["x0"]),
            "y0": int(area["y0"]),
            "x1": int(area["x1"]),
            "y1": int(area["y1"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _cursor_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "map_id": row["map_id"],
        "kind": row["kind"],
        "duration_minutes": row["duration_minutes"],
        "selected_farms": list(row.get("selected_farms") or []),
        "farm_stays_s": dict(row.get("farm_stays_s") or {}),
    }


def party_overlays(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Overlays built only from party rows. Shared map yaml is not read."""
    out: dict[str, Any] = {}
    for row in rows:
        pack_id = str(row.get("map_id") or "").strip()
        if not pack_id:
            continue
        slot = out.get(pack_id)
        if slot is None:
            slot = {
                "dungeon": "dungeon" in pack_id.lower(),
                "areas": [],
                "safe_areas": [],
                "patrol": [],
            }
            out[pack_id] = slot
        kind = str(row.get("kind") or "battle")
        bucket = "safe_areas" if kind == "break" else "areas"
        have = {str(item.get("name") or "") for item in slot[bucket]}
        for raw in row.get("areas") or []:
            if not isinstance(raw, dict):
                continue
            rect = _rect(raw)
            if rect is None or rect["name"] in have:
                continue
            have.add(rect["name"])
            slot[bucket].append(rect)
        if slot["patrol"]:
            continue
        for point in row.get("patrol") or []:
            if not isinstance(point, dict):
                continue
            try:
                slot["patrol"].append(
                    (int(point["x"]), int(point["y"]), str(point.get("name") or ""))
                )
            except (KeyError, TypeError, ValueError):
                continue
    return out


class PartyLeaderManager:
    """Leader tick. Farming still runs through the untouched solo ``decide``."""

    def __init__(self, decision: Any) -> None:
        self.decision = decision

    def decide(self, world: Any) -> Any:
        return self.decision.decide(world)

    def arm(self, routine: Any) -> int:
        """Install the party routine on this decision's blackboard.

        An empty party document installs an empty cursor. It does not copy
        the solo schedule.
        """
        from app._04_decision.world_nav import (
            begin_world_nav,
            init_routine_on_blackboard,
        )
        from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE
        from app._04_decision.world_nav.overlays import set_map_overlays
        from app._04_decision.world_nav.routine import RoutineCursor

        blackboard = self.decision.blackboard
        rows = normalize_party_routine(routine)
        set_map_overlays(blackboard, party_overlays(rows))
        if not rows:
            blackboard.scratch[SCRATCH_ROUTINE] = RoutineCursor.from_entries([])
            return 0
        init_routine_on_blackboard(
            blackboard,
            routine=[_cursor_row(row) for row in rows],
            fallback_map="",
            selected_farms=[],
            farm_stays_s={},
            entries_normalized=True,
        )
        begin_world_nav(blackboard, "party_leader")
        return len(rows)


__all__ = ["PartyLeaderManager", "party_overlays"]
