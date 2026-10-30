"""NPC teleporter shortcuts for world-nav.

Two arrival models (``ShoppingBehavior.teleport_kind``):

- ``dungeon_gate`` (legacy): dialog lands on the NPC map near a dungeon door.
  Planner edges link the NPC tile to a ``ground_enter`` whose ``to_map`` matches
  ``destination_dungeon``. After SHOP_RUN, settle rewrites the next gate.
- ``field_land``: dialog lands at an absolute field xy (often same mainland map).
  Planner edges link the NPC tile to ``(land_map_id, land_world)``. No gate rewrite.

Which teleporters are eligible is ``world_nav: true`` on the behavior in
``npc_behaviors.yaml`` (Shopping Practice checkbox). Korean base ids are
stored; the UI game language ``zh`` uses ``<base>_ch`` when that row exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

from shop.behaviors import (
    TELEPORT_KIND_DUNGEON_GATE,
    TELEPORT_KIND_FIELD_LAND,
)

# Legacy hard-coded set (pre-YAML flag). Still used as default when the YAML
# key is omitted; prefer ``world_nav`` on each teleporter behavior.
WORLD_NAV_TELEPORTER_BASE_IDS: tuple[str, ...] = (
    "teleport_talking_island",
    "teleport_giran",
    "teleport_gludin",
)
# Back-compat alias.
WORLD_NAV_TELEPORTER_IDS = frozenset(WORLD_NAV_TELEPORTER_BASE_IDS)

# Chebyshev radius: NPC → same-map ground_enter.from (sanity; dest map is primary).
GROUND_ENTER_LINK_RADIUS = 400
# Meta-search cost only. Adena is an affordability gate, not tile cost.
TELEPORTER_META_COST_TILES = 15
# If start is within this Chebyshev of a goal ground_enter.from, prefer walk — no NPC TP.
NEAR_ENTRANCE_NO_TELEPORTER_TILES = 50


_behaviors_cache: tuple[int, list[Any]] | None = None


def _cached_behaviors() -> list[Any]:
    """NPC catalog for planning. Reread only when the yaml file changes."""
    global _behaviors_cache
    from shop.behaviors import BEHAVIORS_PATH, load_behaviors

    try:
        stamp = int(BEHAVIORS_PATH.stat().st_mtime_ns)
    except OSError:
        stamp = -1
    if _behaviors_cache is not None and _behaviors_cache[0] == stamp:
        return _behaviors_cache[1]
    rows = load_behaviors()
    try:
        stamp = int(BEHAVIORS_PATH.stat().st_mtime_ns)
    except OSError:
        stamp = -1
    _behaviors_cache = (stamp, rows)
    return rows


def warm_teleporter_catalog() -> None:
    """Read the NPC catalog once, before a route asks for teleporter links."""
    _cached_behaviors()


def list_world_nav_teleporter_base_ids(
    catalog: Iterable[Any] | None = None,
) -> tuple[str, ...]:
    """Korean (non-``_ch``) teleporter ids with ``world_nav`` enabled."""
    from shop.behaviors import ACTION_TELEPORTER

    rows = catalog if catalog is not None else _cached_behaviors()
    out: list[str] = []
    seen: set[str] = set()
    for b in rows:
        if str(getattr(b, "action", "") or "") != ACTION_TELEPORTER:
            continue
        if not bool(getattr(b, "world_nav", False)):
            continue
        bid = str(getattr(b, "id", "") or "").strip()
        if not bid or bid.endswith("_ch"):
            continue
        if bid in seen:
            continue
        seen.add(bid)
        out.append(bid)
    return tuple(out)


def resolve_world_nav_teleporter_ids(
    locale: object | None = None,
) -> frozenset[str]:
    """YAML teleporter ids for the client language (``ko`` / ``zh``).

    Enabled set = teleporters with ``world_nav: true`` (Shopping Practice).
    When ``locale`` is omitted, the UI game language (set at Start) is used.
    Account server locale does not pick these dialog clicks.
    ``zh`` → ``<base>_ch`` when that row exists, else the Korean base (so a
    newly calibrated field_land is not dropped until a ``_ch`` UV is saved).
    ``ko`` → base. Missing catalog rows are still skipped by ``behavior_by_id``.
    """
    from app._04_decision.shops import normalize_shop_locale
    from shop.behaviors import behavior_by_id

    if locale is None:
        from app._04_decision.game_language import get_game_language

        locale = get_game_language()
    chinese = normalize_shop_locale(locale) == "zh"
    bases = list_world_nav_teleporter_base_ids()
    if not bases:
        # No flagged rows yet — keep historical three so old YAML still works.
        bases = WORLD_NAV_TELEPORTER_BASE_IDS
    if not chinese:
        return frozenset(bases)
    catalog = _cached_behaviors()
    out: set[str] = set()
    for bid in bases:
        ch = f"{bid}_ch"
        if behavior_by_id(ch, catalog) is not None:
            out.add(ch)
        else:
            out.add(bid)
    return frozenset(out)


def dungeon_gate_serves_goal(
    transitions: Iterable[Any],
    *,
    destination_dungeon: int,
    goal_map: int,
) -> bool:
    """True when a dungeon_gate TP into ``destination_dungeon`` helps reach ``goal_map``.

    Same map, or ``goal_map`` reachable from the destination by ``floor_ladder``
    edges only (deeper floors of that complex). Stops mainland shutter TPs from
    being used as cheap blinks when the goal is an unrelated dungeon/field.
    """
    dest = int(destination_dungeon)
    goal = int(goal_map)
    if dest <= 0:
        return False
    if dest == goal:
        return True
    # BFS on floor_ladder only, starting at dest.
    adj: dict[int, set[int]] = {}
    for t in transitions:
        if str(getattr(t, "edge_type", "") or "") != "floor_ladder":
            continue
        a = int(getattr(t, "from_map", -1))
        b = int(getattr(t, "to_map", -1))
        if a < 0 or b < 0:
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen = {dest}
    stack = [dest]
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt in seen:
                continue
            if nxt == goal:
                return True
            seen.add(nxt)
            stack.append(nxt)
    return False


def filter_teleporter_links_for_goal(
    links: Iterable[NpcTeleporterLink],
    transitions: Iterable[Any],
    *,
    goal_map: int,
    same_map: bool,
) -> list[NpcTeleporterLink]:
    """Drop dungeon_gate links that do not serve the goal; keep field_land.

    On the goal map, only field_land remains (dungeon_gate would leave it).
    """
    out: list[NpcTeleporterLink] = []
    gm = int(goal_map)
    for link in links:
        if link.is_field_land:
            out.append(link)
            continue
        if same_map:
            continue
        if dungeon_gate_serves_goal(
            transitions,
            destination_dungeon=int(link.destination_dungeon),
            goal_map=gm,
        ):
            out.append(link)
    return out


@dataclass(frozen=True)
class NpcTeleporterLink:
    behavior_id: str
    name: str
    map_id: int
    npc_x: int
    npc_y: int
    adena_cost: int
    teleport_kind: str
    destination_dungeon: int
    # Planner arrival cell: dungeon gate approach, or field land xy.
    land_map_id: int
    land_x: int
    land_y: int
    gate_edge_id: str = ""
    gate_to_x: int = 0
    gate_to_y: int = 0

    @property
    def npc_key(self) -> tuple[int, int, int]:
        return (int(self.map_id), int(self.npc_x), int(self.npc_y))

    @property
    def land_key(self) -> tuple[int, int, int]:
        return (int(self.land_map_id), int(self.land_x), int(self.land_y))

    @property
    def gate_key(self) -> tuple[int, int, int]:
        """Back-compat alias for planner nodes (same as ``land_key``)."""
        return self.land_key

    @property
    def cost_tiles(self) -> int:
        return int(TELEPORTER_META_COST_TILES)

    @property
    def is_field_land(self) -> bool:
        return str(self.teleport_kind) == TELEPORT_KIND_FIELD_LAND


def _cheb(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def load_npc_teleporter_links(
    transitions: Iterable[Any],
    *,
    adena: Optional[int] = None,
    behavior_ids: frozenset[str] | None = None,
    link_radius: int = GROUND_ENTER_LINK_RADIUS,
) -> list[NpcTeleporterLink]:
    """Build NPC→arrival links for planner edges.

    - ``dungeon_gate``: ``ground_enter`` with ``to_map == destination_dungeon``.
    - ``field_land``: direct edge to ``(land_map_id, land_world)``.
    ``adena``: when set, skip links whose fare exceeds current adena.
    Incomplete rows (dest/land unset) are skipped.
    """
    from shop.behaviors import ACTION_TELEPORTER, behavior_by_id

    from . import pack_ids

    catalog = _cached_behaviors()
    want = (
        behavior_ids
        if behavior_ids is not None
        else resolve_world_nav_teleporter_ids()
    )
    links: list[NpcTeleporterLink] = []
    radius = max(0, int(link_radius))

    for bid in sorted(want):
        b = behavior_by_id(bid, catalog)
        if b is None or str(b.action) != ACTION_TELEPORTER:
            continue
        mid = pack_ids.pack_id_to_map_id(str(b.map_id or ""))
        if mid is None:
            continue
        fare = max(0, int(getattr(b, "adena_cost", 0) or 0))
        if adena is not None and fare > int(adena):
            continue
        nx, ny = int(b.npc_world_x), int(b.npc_world_y)
        kind = str(getattr(b, "teleport_kind", "") or TELEPORT_KIND_DUNGEON_GATE)
        if getattr(b, "is_field_land", None) and b.is_field_land():
            kind = TELEPORT_KIND_FIELD_LAND
        elif kind not in (TELEPORT_KIND_DUNGEON_GATE, TELEPORT_KIND_FIELD_LAND):
            kind = TELEPORT_KIND_DUNGEON_GATE

        if kind == TELEPORT_KIND_FIELD_LAND:
            land_mid = max(0, int(getattr(b, "land_map_id", 0) or 0))
            lx = int(getattr(b, "land_world_x", 0) or 0)
            ly = int(getattr(b, "land_world_y", 0) or 0)
            if land_mid <= 0:
                continue
            links.append(
                NpcTeleporterLink(
                    behavior_id=str(b.id),
                    name=str(b.name or b.id),
                    map_id=int(mid),
                    npc_x=nx,
                    npc_y=ny,
                    adena_cost=fare,
                    teleport_kind=TELEPORT_KIND_FIELD_LAND,
                    destination_dungeon=0,
                    land_map_id=land_mid,
                    land_x=lx,
                    land_y=ly,
                )
            )
            continue

        dest = max(0, int(getattr(b, "destination_dungeon", 0) or 0))
        if dest <= 0:
            continue
        for t in transitions:
            if str(getattr(t, "edge_type", "") or "") != "ground_enter":
                continue
            if int(getattr(t, "from_map", -1)) != mid:
                continue
            if int(getattr(t, "to_map", -1)) != dest:
                continue
            gx = int(t.from_x)
            gy = int(t.from_y)
            if _cheb(nx, ny, gx, gy) > radius:
                continue
            links.append(
                NpcTeleporterLink(
                    behavior_id=str(b.id),
                    name=str(b.name or b.id),
                    map_id=int(mid),
                    npc_x=nx,
                    npc_y=ny,
                    adena_cost=fare,
                    teleport_kind=TELEPORT_KIND_DUNGEON_GATE,
                    destination_dungeon=dest,
                    land_map_id=int(mid),
                    land_x=gx,
                    land_y=gy,
                    gate_edge_id=str(getattr(t, "edge_id", "") or ""),
                    gate_to_x=int(t.to_x),
                    gate_to_y=int(t.to_y),
                )
            )
    return links


def near_goal_ground_enter(
    transitions: Iterable[Any],
    *,
    goal_map: int,
    start_map: int,
    start_x: int,
    start_y: int,
    radius: int = NEAR_ENTRANCE_NO_TELEPORTER_TILES,
) -> bool:
    """True when start is already near a ground_enter into ``goal_map``."""
    r = max(0, int(radius))
    gm = int(goal_map)
    sm = int(start_map)
    sx, sy = int(start_x), int(start_y)
    for t in transitions:
        if str(getattr(t, "edge_type", "") or "") != "ground_enter":
            continue
        if int(getattr(t, "to_map", -1)) != gm:
            continue
        if int(getattr(t, "from_map", -1)) != sm:
            continue
        if _cheb(sx, sy, int(t.from_x), int(t.from_y)) <= r:
            return True
    return False


def nearest_ground_enter_for_destination(
    transitions: Iterable[Any],
    *,
    from_map: int,
    destination_dungeon: int,
    near_x: int,
    near_y: int,
) -> Any | None:
    """Closest ``ground_enter`` on ``from_map`` whose ``to_map`` is the dungeon."""
    dest = int(destination_dungeon)
    mid = int(from_map)
    nx, ny = int(near_x), int(near_y)
    best: Any | None = None
    best_d = 10**18
    for t in transitions:
        if str(getattr(t, "edge_type", "") or "") != "ground_enter":
            continue
        if int(getattr(t, "from_map", -1)) != mid:
            continue
        if int(getattr(t, "to_map", -1)) != dest:
            continue
        d = _cheb(nx, ny, int(t.from_x), int(t.from_y))
        if d < best_d:
            best_d = d
            best = t
    return best
