"""Party hunt schedule. It reads party rows only.

The solo routine cursor is not installed and ``profile.routine`` is not read.
A row's saved areas and points are the hunt marks. A checked name is kept
only when that name is still on the row. Otherwise the saved marks are used.
"""
from __future__ import annotations

from typing import Any, Optional

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
        return {"name": name, "x0": x, "y0": y, "x1": x, "y1": y}
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
    return {"name": name, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def _mark_from_patrol(point: dict[str, Any]) -> Optional[dict[str, int | str]]:
    try:
        x = int(point["x"])
        y = int(point["y"])
    except (KeyError, TypeError, ValueError):
        return None
    name = str(point.get("name") or "").strip() or "patrol"
    return {"name": name, "x0": x, "y0": y, "x1": x, "y1": y}


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


def mark_contains(mark: dict[str, int | str], x: int, y: int) -> bool:
    return int(mark["x0"]) <= int(x) <= int(mark["x1"]) and int(mark["y0"]) <= int(y) <= int(mark["y1"])


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

    def goal_nav(self) -> Optional[tuple[str, int, int]]:
        """Nav-space center of the first mark. None when the row is map-only."""
        row = self.current()
        marks = self.marks()
        if row is None or not marks:
            return None
        x, y = mark_center(marks[0])
        return str(row.get("map_id") or ""), x, y

    def inside_nav(self, x: int, y: int) -> bool:
        marks = self.marks()
        if not marks:
            return False
        return any(mark_contains(mark, x, y) for mark in marks)

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
        self.finished = False
        return True


__all__ = [
    "PartyLeaderSchedule",
    "hunt_marks",
    "mark_center",
    "mark_contains",
]
