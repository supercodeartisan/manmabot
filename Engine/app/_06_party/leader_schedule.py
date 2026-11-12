"""Party hunt schedule. It reads party rows only.

The solo routine cursor is not installed and ``profile.routine`` is not read.
A row's saved areas and points are the hunt marks. A checked name is kept
only when that name is still on the row. Otherwise the saved marks are used.
"""
from __future__ import annotations

from typing import Any, Optional

from settings.farm_schedule import DEFAULT_FARM_STAY_S, stay_seconds_for
from settings.party_routine import normalize_party_routine


def _mark_from_area(area: dict[str, Any]) -> Optional[dict[str, int | str]]:
    name = str(area.get("name") or "").strip()
    if not name:
        return None
    if str(area.get("shape") or "") == "point":
        try:
            x = int(area["x"])
            y = int(area["y"])
        except (KeyError, TypeError, ValueError):
            return None
        return {"name": name, "shape": "point", "x0": x, "y0": y, "x1": x, "y1": y}
    try:
        x0 = int(area["x0"])
        y0 = int(area["y0"])
        x1 = int(area["x1"])
        y1 = int(area["y1"])
    except (KeyError, TypeError, ValueError):
        return None
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return {"name": name, "shape": "area", "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _mark_from_patrol(point: dict[str, Any]) -> Optional[dict[str, int | str]]:
    try:
        x = int(point["x"])
        y = int(point["y"])
    except (KeyError, TypeError, ValueError):
        return None
    name = str(point.get("name") or "").strip() or "patrol"
    return {"name": name, "shape": "point", "x0": x, "y0": y, "x1": x, "y1": y}


def hunt_marks(row: dict[str, Any]) -> list[dict[str, int | str]]:
    """Marks this party row actually hunts, in check order when the names match."""
    areas = [item for item in (row.get("areas") or []) if isinstance(item, dict)]
    by_name: dict[str, dict[str, Any]] = {}
    for area in areas:
        name = str(area.get("name") or "").strip()
        if name and name not in by_name:
            by_name[name] = area
    chosen = [
        by_name[name]
        for name in (row.get("selected_farms") or [])
        if str(name).strip() in by_name
    ]
    if not chosen:
        chosen = areas
    marks: list[dict[str, int | str]] = []
    for area in chosen:
        mark = _mark_from_area(area)
        if mark is not None:
            marks.append(mark)
    if marks:
        return marks
    for point in row.get("patrol") or []:
        if not isinstance(point, dict):
            continue
        mark = _mark_from_patrol(point)
        if mark is not None:
            marks.append(mark)
    return marks


# Chebyshev radius around a map dot. 2 → a 5×5 box with the dot at the center.
POINT_BOX_TILES = 2


def mark_contains(mark: dict[str, int | str], x: int, y: int) -> bool:
    return int(mark["x0"]) <= int(x) <= int(mark["x1"]) and int(mark["y0"]) <= int(y) <= int(mark["y1"])


def _chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def nearest_point_nav(
    marks: list[dict[str, int | str]], x: int, y: int
) -> Optional[tuple[int, int]]:
    """Nav tile of the closest ``shape == point`` mark, or None."""
    best: Optional[tuple[int, int]] = None
    best_d: Optional[int] = None
    for mark in marks:
        if str(mark.get("shape") or "") != "point":
            continue
        cx, cy = int(mark["x0"]), int(mark["y0"])
        dist = _chebyshev(x, y, cx, cy)
        if best_d is None or dist < best_d:
            best = (cx, cy)
            best_d = dist
    return best


def point_box_center(
    marks: list[dict[str, int | str]],
    x: int,
    y: int,
    *,
    radius: int = POINT_BOX_TILES,
) -> Optional[tuple[int, int]]:
    """Center of the point whose 5×5 contains ``(x, y)``, else None."""
    center = nearest_point_nav(marks, x, y)
    if center is None:
        return None
    if _chebyshev(x, y, center[0], center[1]) > int(radius):
        return None
    return center


def point_farm_bounds(mark: dict[str, int | str]) -> tuple[int, int, int, int]:
    """Farm rect for one mark. A dot expands to its 5×5 box."""
    if str(mark.get("shape") or "") == "point":
        cx, cy = int(mark["x0"]), int(mark["y0"])
        r = int(POINT_BOX_TILES)
        return cx - r, cy - r, cx + r, cy + r
    return int(mark["x0"]), int(mark["y0"]), int(mark["x1"]), int(mark["y1"])


def place_at(marks: list[dict[str, int | str]], x: int, y: int) -> str:
    """``point`` inside a dot's 5×5, ``area`` inside a rect, ``none`` elsewhere.

    A dot's box wins when a rect also covers that tile. A one-tile rect is
    still an area: only ``shape == point`` is a turret spot.
    """
    if point_box_center(marks, x, y) is not None:
        return "point"
    for mark in marks:
        if str(mark.get("shape") or "") != "point" and mark_contains(mark, x, y):
            return "area"
    return "none"


def mark_center(mark: dict[str, int | str]) -> tuple[int, int]:
    return (int(mark["x0"]) + int(mark["x1"])) // 2, (int(mark["y0"]) + int(mark["y1"])) // 2


class PartyLeaderSchedule:
    """One party document. Time counts only while the leader is inside the row."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)
        self.index = 0
        self.elapsed = 0.0
        self.finished = False
        self._inside_since: Optional[float] = None
        self.mark_index = 0
        self.mark_elapsed = 0.0
        self._mark_since: Optional[float] = None
        self.plan_index = 0
        self.patrol_waypoint_index: Optional[int] = None
        self.plan_generation = 0
        self.stage_elapsed = 0.0
        self._stage_since: Optional[float] = None
        self.point_arrived = False
        self.plan_invalid = False
        self.stage_state = "idle"
        self.plan_errors: list[str] = []
        self._reported_plan_errors: set[str] = set()

    @classmethod
    def from_routine(cls, raw: Any) -> "PartyLeaderSchedule":
        return cls(normalize_party_routine(raw))

    def current(self) -> Optional[dict[str, Any]]:
        if self.index < 0 or self.index >= len(self.rows):
            return None
        return self.rows[self.index]

    def marks(self) -> list[dict[str, int | str]]:
        row = self.current()
        if row is None:
            return []
        return hunt_marks(row)

    def current_mark(self) -> Optional[dict[str, int | str]]:
        """The checked mark this row is hunting now, in check order."""
        marks = self.marks()
        if not marks:
            return None
        self.mark_index = int(self.mark_index) % len(marks)
        return marks[self.mark_index]

    def goal_nav(self) -> Optional[tuple[str, int, int]]:
        """Nav-space center of the current mark. None when the row is map-only."""
        row = self.current()
        mark = self.current_mark()
        if row is None or mark is None:
            return None
        x, y = mark_center(mark)
        return str(row.get("map_id") or ""), x, y

    def inside_current_nav(self, x: int, y: int) -> bool:
        """True inside the current mark only. A later mark does not count."""
        mark = self.current_mark()
        if mark is None:
            return False
        return place_at([mark], x, y) != "none"

    def mark_stay_s(self) -> float:
        """Seconds saved for the current mark. A missing stay uses the solo default."""
        row = self.current()
        mark = self.current_mark()
        if row is None or mark is None:
            return float(DEFAULT_FARM_STAY_S)
        stays = row.get("farm_stays_s")
        if not isinstance(stays, dict):
            stays = {}
        return stay_seconds_for(str(mark.get("name") or ""), stays, DEFAULT_FARM_STAY_S)

    def note_mark(self, now: float, inside: bool, *, holding: bool = False) -> None:
        """Add time spent inside the current mark. A hold or a step outside pauses it."""
        if self.finished or holding or not inside:
            self._mark_since = None
            return
        if self._mark_since is None:
            self._mark_since = float(now)
            return
        self.mark_elapsed += float(now) - self._mark_since
        self._mark_since = float(now)

    def mark_due(self, now: float) -> bool:
        mark = self.current_mark()
        if mark is None or self.finished:
            return False
        elapsed = self.mark_elapsed
        if self._mark_since is not None:
            elapsed += float(now) - self._mark_since
        return elapsed >= self.mark_stay_s()

    def advance_mark(self) -> bool:
        """Move to the next checked mark. The last mark wraps to the first.

        One mark stays put and its stay clock restarts. The row clock is unchanged.
        """
        marks = self.marks()
        self.mark_elapsed = 0.0
        self._mark_since = None
        if len(marks) < 2:
            return False
        self.mark_index = (int(self.mark_index) + 1) % len(marks)
        return True

    def place_nav(self, x: int, y: int) -> str:
        """Nav tile: point (turret box), area (moving hunt), or none."""
        return place_at(self.marks(), x, y)

    def point_nav(self, x: int, y: int) -> Optional[tuple[int, int]]:
        """Dot at the center of the 5×5 that contains this nav tile."""
        return point_box_center(self.marks(), x, y)

    def nearest_point_nav(self, x: int, y: int) -> Optional[tuple[int, int]]:
        """Closest dot on this row, including when the player has left its box."""
        return nearest_point_nav(self.marks(), x, y)

    def has_point(self) -> bool:
        return any(str(mark.get("shape") or "") == "point" for mark in self.marks())

    def inside_nav(self, x: int, y: int) -> bool:
        """True inside a dot's 5×5 or inside an area rect."""
        return place_at(self.marks(), x, y) != "none"

    def note_inside(self, now: float, inside: bool, *, holding: bool = False) -> None:
        """Add time spent inside the row. A hold or a step outside pauses it."""
        if self.finished or holding or not inside:
            self._inside_since = None
            return
        if self._inside_since is None:
            self._inside_since = float(now)
            return
        self.elapsed += float(now) - self._inside_since
        self._inside_since = float(now)

    def due(self, now: float) -> bool:
        row = self.current()
        if row is None or self.finished:
            return False
        elapsed = self.elapsed
        if self._inside_since is not None:
            elapsed += float(now) - self._inside_since
        minutes = int(row.get("duration_minutes") or 0)
        return elapsed >= float(minutes) * 60.0

    def advance(self) -> bool:
        """Move to the next party row. The last row stays in place."""
        if self.finished or self.index + 1 >= len(self.rows):
            self.finished = True
            self._inside_since = None
            return False
        self.index += 1
        self.elapsed = 0.0
        self._inside_since = None
        self.mark_index = 0
        self.mark_elapsed = 0.0
        self._mark_since = None
        self._reset_plan_cursor()
        self.finished = False
        return True

    def dungeon_plan(self) -> Optional[list[dict[str, Any]]]:
        """The mixed patrol/point list, or None when this row stays legacy."""
        row = self.current()
        if row is None:
            return None
        plan = row.get("dungeon_plan")
        if not isinstance(plan, list) or not plan:
            return None
        return plan

    def _reset_plan_cursor(self) -> None:
        self.plan_index = 0
        self.patrol_waypoint_index = None
        self.plan_generation = 0
        self.stage_elapsed = 0.0
        self._stage_since = None
        self.point_arrived = False
        self.plan_invalid = False
        self.stage_state = "idle"

    def current_plan_entry(self) -> Optional[dict[str, Any]]:
        plan = self.dungeon_plan()
        if not plan or self.plan_invalid:
            return None
        return plan[int(self.plan_index) % len(plan)]

    def _patrol_duration_s(self, entry: dict[str, Any]) -> Optional[float]:
        if "duration_s" not in entry:
            return None
        try:
            value = float(entry.get("duration_s"))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value

    def _stage_limit_s(self, entry: dict[str, Any]) -> Optional[float]:
        if str(entry.get("type") or "") == "patrol":
            return self._patrol_duration_s(entry)
        if "stay_s" not in entry:
            return float(DEFAULT_FARM_STAY_S)
        try:
            value = float(entry.get("stay_s"))
        except (TypeError, ValueError):
            return float(DEFAULT_FARM_STAY_S)
        if value <= 0:
            return float(DEFAULT_FARM_STAY_S)
        return value

    def _plan_entry_error(self, entry: dict[str, Any]) -> Optional[str]:
        if str(entry.get("type") or "") != "patrol":
            return None
        ident = str(entry.get("id") or self.plan_index)
        if self._patrol_duration_s(entry) is None:
            return f"dungeon plan patrol {ident} has no positive duration_s"
        if not list(entry.get("waypoints") or []):
            return f"dungeon plan patrol {ident} has no waypoints"
        return None

    def _remember_plan_error(self, message: str) -> None:
        if message in self._reported_plan_errors:
            return
        self._reported_plan_errors.add(message)
        self.plan_errors.append(message)

    def _advance_plan_index(self) -> None:
        plan = self.dungeon_plan() or []
        if not plan:
            return
        self.plan_index = (int(self.plan_index) + 1) % len(plan)
        self.plan_generation = int(self.plan_generation) + 1
        self.patrol_waypoint_index = None
        self.stage_elapsed = 0.0
        self._stage_since = None
        self.point_arrived = False
        self.stage_state = "transition"

    def skip_invalid_plan_entries(self) -> None:
        """Leave a patrol that cannot time-box itself. Later entries still run."""
        plan = self.dungeon_plan()
        if not plan or self.plan_invalid:
            return
        for _ in range(len(plan)):
            entry = plan[int(self.plan_index) % len(plan)]
            message = self._plan_entry_error(entry)
            if message is None:
                return
            self._remember_plan_error(message)
            self._advance_plan_index()
        self.plan_invalid = True
        self.stage_state = "invalid"

    def bind_patrol_waypoint(self, x: int, y: int) -> None:
        """First goal of a patrol stage is the nearest saved waypoint."""
        entry = self.current_plan_entry()
        if entry is None or str(entry.get("type") or "") != "patrol":
            return
        if self.patrol_waypoint_index is not None:
            return
        waypoints = list(entry.get("waypoints") or [])
        if not waypoints:
            return
        best_i = 0
        best_d: Optional[int] = None
        for index, point in enumerate(waypoints):
            dist = _chebyshev(x, y, int(point["x"]), int(point["y"]))
            if best_d is None or dist < best_d:
                best_d = dist
                best_i = index
        self.patrol_waypoint_index = best_i

    def patrol_goal_xy(self) -> Optional[tuple[int, int]]:
        entry = self.current_plan_entry()
        if entry is None or str(entry.get("type") or "") != "patrol":
            return None
        waypoints = list(entry.get("waypoints") or [])
        if not waypoints or self.patrol_waypoint_index is None:
            return None
        point = waypoints[int(self.patrol_waypoint_index) % len(waypoints)]
        return int(point["x"]), int(point["y"])

    def note_patrol_arrival(self, x: int, y: int, *, radius: int = 1) -> None:
        """Step to the next waypoint. The stage clock is not touched."""
        goal = self.patrol_goal_xy()
        entry = self.current_plan_entry()
        if goal is None or entry is None:
            return
        if _chebyshev(x, y, goal[0], goal[1]) > int(radius):
            return
        waypoints = list(entry.get("waypoints") or [])
        if not waypoints:
            return
        self.patrol_waypoint_index = (int(self.patrol_waypoint_index or 0) + 1) % len(waypoints)

    def plan_point_xy(self) -> Optional[tuple[int, int]]:
        entry = self.current_plan_entry()
        if entry is None or str(entry.get("type") or "") != "point":
            return None
        try:
            return int(entry["x"]), int(entry["y"])
        except (KeyError, TypeError, ValueError):
            return None

    def point_contains(self, x: int, y: int) -> bool:
        center = self.plan_point_xy()
        if center is None:
            return False
        return _chebyshev(x, y, center[0], center[1]) <= int(POINT_BOX_TILES)

    def plan_point_goal_nav(self) -> Optional[tuple[str, int, int]]:
        """Nav goal while walking to a point. None after arrival and for patrols."""
        row = self.current()
        center = self.plan_point_xy()
        if row is None or center is None or self.point_arrived:
            return None
        return str(row.get("map_id") or ""), center[0], center[1]

    def note_plan_stage(self, now: float, *, running: bool, at_point: bool) -> None:
        """Add time for the active stage.

        A pause keeps the elapsed time and the plan index. Combat does not
        pause a patrol. A point starts only once the body is inside its box,
        and that dwell keeps running if a fight steps outside the box.
        """
        if not self.dungeon_plan():
            return
        self.skip_invalid_plan_entries()
        entry = self.current_plan_entry()
        if entry is None:
            return
        if not running:
            self._stage_since = None
            self.stage_state = "paused"
            return
        if str(entry.get("type") or "") == "point" and not self.point_arrived:
            if not at_point:
                self._stage_since = None
                self.stage_state = "traveling"
                return
            self.point_arrived = True
        self.stage_state = "hunting"
        if self._stage_since is None:
            self._stage_since = float(now)
            return
        self.stage_elapsed += float(now) - self._stage_since
        self._stage_since = float(now)

    def stage_due(self, now: float) -> bool:
        entry = self.current_plan_entry()
        if entry is None:
            return False
        if str(entry.get("type") or "") == "point" and not self.point_arrived:
            return False
        limit = self._stage_limit_s(entry)
        if limit is None:
            return False
        elapsed = self.stage_elapsed
        if self._stage_since is not None:
            elapsed += float(now) - self._stage_since
        return elapsed >= limit

    def advance_plan_stage(self) -> bool:
        """Select the next saved entry and drop this stage's clock."""
        if not self.dungeon_plan() or self.plan_invalid:
            return False
        self._advance_plan_index()
        self.skip_invalid_plan_entries()
        return True

    def motion_snapshot(self) -> Optional[dict[str, Any]]:
        """What the active entry wants the leader to walk toward."""
        plan = self.dungeon_plan()
        if not plan:
            return None
        if self.plan_invalid:
            return {
                "active": True,
                "kind": "invalid",
                "goal": None,
                "generation": int(self.plan_generation),
                "id": "",
                "arrived": False,
            }
        entry = self.current_plan_entry()
        if entry is None:
            return None
        kind = str(entry.get("type") or "")
        goal = self.patrol_goal_xy() if kind == "patrol" else self.plan_point_xy()
        return {
            "active": True,
            "kind": kind,
            "goal": None if goal is None else (int(goal[0]), int(goal[1])),
            "generation": int(self.plan_generation),
            "id": str(entry.get("id") or ""),
            "arrived": bool(self.point_arrived) if kind == "point" else False,
        }


def party_plan_motion(scratch: Any) -> Optional[dict[str, Any]]:
    """Active party dungeon plan, or None so solo patrol.yaml may run."""
    if not isinstance(scratch, dict):
        return None
    raw = scratch.get("party_dungeon_plan")
    if not isinstance(raw, dict) or not raw.get("active"):
        return None
    return raw


def yaml_patrol_allowed(scratch: Any) -> bool:
    return party_plan_motion(scratch) is None


__all__ = [
    "PartyLeaderSchedule",
    "POINT_BOX_TILES",
    "hunt_marks",
    "mark_center",
    "mark_contains",
    "nearest_point_nav",
    "place_at",
    "point_box_center",
    "point_farm_bounds",
    "party_plan_motion",
    "yaml_patrol_allowed",
]
