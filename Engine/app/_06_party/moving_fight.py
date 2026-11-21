"""Moving-farm fight: a short step to an attack tile, and when the march waits.

A sighting does not stop the party. The march waits for a real fight, a rear
member who still needs help, or a hop that would leave that member outside
support range. Turret hunt does not use this.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

# How long a rear report still counts. One missed send stays inside this.
# Not measured.
REPORT_FRESH_S = 2.0

Tile = tuple[int, int]


def _cheb(a: Tile, b: Tile) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def combat_step(
    me: Tile,
    monster: Optional[Tile],
    *,
    can_hit: bool,
    approach_tiles: int,
    support_from: Optional[Tile],
    support_tiles: int,
    blocked: Sequence[Tile] = (),
    path_for: Any = None,
) -> tuple[str, Optional[Tile]]:
    """``attack`` here, ``approach`` one empty attack tile, or ``rejoin``.

    ``approach_tiles`` is the member's existing approach setting. The walk is
    the path length when ``path_for`` returns tiles, otherwise the straight
    gap. A stand that leaves support range, or a path longer than the
    approach setting, is not used.
    """
    if can_hit:
        return "attack", me
    if monster is None:
        return "rejoin", None
    from app._04_decision.behaviors.party_turret import melee_stands

    taken = {(int(t[0]), int(t[1])) for t in blocked}
    limit = max(1, int(approach_tiles))
    support = max(1, int(support_tiles))
    stands = []
    for stand in melee_stands(monster):
        if stand in taken or stand == me:
            continue
        path = None
        if path_for is not None:
            try:
                path = path_for(me, stand)
            except Exception:
                path = None
        if path:
            walk = len(path)
            outside = support_from is not None and any(
                _cheb((int(p[0]), int(p[1])), support_from) > support for p in path
            )
        else:
            walk = _cheb(me, stand)
            outside = (
                support_from is not None and _cheb(stand, support_from) > support
            )
        if outside or walk > limit:
            continue
        stands.append((walk, stand))
    if not stands:
        return "rejoin", None
    stands.sort(key=lambda item: (item[0], item[1][0], item[1][1]))
    return "approach", stands[0][1]


def crosses_corner(here: Optional[Tile], hop: Optional[Tile], guide: Sequence[Tile]) -> bool:
    """True when the hop passes a turn in ``guide``."""
    if here is None or hop is None or not guide:
        return False
    tiles = [(int(t[0]), int(t[1])) for t in guide]

    def _at(tile: Tile) -> Optional[int]:
        try:
            return tiles.index((int(tile[0]), int(tile[1])))
        except ValueError:
            return None

    start = _at(here)
    end = _at(hop)
    if start is None or end is None or end <= start:
        return False
    prev = None
    for i in range(start, end):
        step = (tiles[i + 1][0] - tiles[i][0], tiles[i + 1][1] - tiles[i][1])
        if step == (0, 0):
            continue
        if prev is not None and step != prev:
            return True
        prev = step
    return False


def march_hold_reason(
    *,
    leader_fighting: bool,
    rear_hot: bool,
    report_age: Optional[float],
    fresh_s: float = REPORT_FRESH_S,
    disconnected: bool = False,
    other_map: bool = False,
    here: Optional[Tile] = None,
    hop: Optional[Tile] = None,
    guide: Sequence[Tile] = (),
    engaged_member: Optional[Tile] = None,
    support_tiles: int = 10,
) -> str:
    """Why the next march hop waits. ``\"\"`` means the path may continue.

    A single missed report stays inside ``fresh_s``. An old report, a dropped
    connection, or another map does not hold the party.
    """
    hot = bool(rear_hot) and not disconnected and not other_map
    if report_age is None or float(report_age) > float(fresh_s):
        hot = False
    if leader_fighting:
        return "fight"
    if hot:
        return "rear"
    if (
        not hot
        and engaged_member is not None
        and hop is not None
        and here is not None
        and _cheb(here, engaged_member) <= int(support_tiles)
        and _cheb(hop, engaged_member) > int(support_tiles)
    ):
        return "support"
    return ""


__all__ = [
    "REPORT_FRESH_S",
    "combat_step",
    "crosses_corner",
    "march_hold_reason",
]
