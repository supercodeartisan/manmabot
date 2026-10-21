"""NPC teleporter shortcuts for world-nav (same-map land → destination dungeon gate).

Land xy is unknown at plan time. Each teleporter behavior names a
``destination_dungeon`` (LC mapId). Planner edges link the NPC tile only to
``ground_enter`` transitions whose ``to_map`` matches that destination.
After SHOP_RUN, settle polls live pose until xy leaves the NPC cell, then
the nearest matching entrance is used for gate approach.

Which teleporters are eligible is ``world_nav: true`` on the behavior in
``npc_behaviors.yaml`` (Shopping Practice checkbox). Korean base ids are
stored; Chinese locale uses ``<base>_ch``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

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
    """YAML teleporter ids for the active shop locale (``ko`` / ``zh``).

    Enabled set = teleporters with ``world_nav: true`` (Shopping Practice).
    ``zh`` → ``<base>_ch``, ``ko`` → base. Missing catalog rows are skipped
    later by ``behavior_by_id``.
    """
    from app._04_decision.shops import SHOP_LOCALE, normalize_shop_locale

    chinese = (
        normalize_shop_locale(locale if locale is not None else SHOP_LOCALE)
        == "zh"
    )
    bases = list_world_nav_teleporter_base_ids()
    if not bases:
        # No flagged rows yet — keep historical three so old YAML still works.
        bases = WORLD_NAV_TELEPORTER_BASE_IDS
    if chinese:
        return frozenset(f"{bid}_ch" for bid in bases)
    return frozenset(bases)


@dataclass(frozen=True)
class NpcTeleporterLink:
    behavior_id: str
    name: str
    map_id: int
    npc_x: int
    npc_y: int
    adena_cost: int
    destination_dungeon: int
    gate_edge_id: str
    gate_x: int
    gate_y: int
    gate_to_x: int
    gate_to_y: int

    @property
    def npc_key(self) -> tuple[int, int, int]:
        return (int(self.map_id), int(self.npc_x), int(self.npc_y))

    @property
    def gate_key(self) -> tuple[int, int, int]:
        return (int(self.map_id), int(self.gate_x), int(self.gate_y))

    @property
    def cost_tiles(self) -> int:
        return int(TELEPORTER_META_COST_TILES)


def _cheb(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def load_npc_teleporter_links(
    transitions: Iterable[Any],
    *,
    adena: Optional[int] = None,
    behavior_ids: frozenset[str] | None = None,
    link_radius: int = GROUND_ENTER_LINK_RADIUS,
) -> list[NpcTeleporterLink]:
    """Build NPC→ground_enter links for planner edges.

    Only ``ground_enter`` edges with ``to_map == behavior.destination_dungeon``.
    ``adena``: when set, skip links whose fare exceeds current adena.
    Behaviors with ``destination_dungeon == 0`` are skipped.
    """
    from shop.behaviors import ACTION_TELEPORTER, behavior_by_id

    from . import pack_ids

    catalog = _cached_behaviors()
    want = (
        behavior_ids
        if behavior_ids is not None
        else resolve_world_nav_teleporter_ids()
    )
    npcs: list[tuple[Any, int, int, int, int]] = []
    for bid in sorted(want):
        b = behavior_by_id(bid, catalog)
        if b is None or str(b.action) != ACTION_TELEPORTER:
            continue
        dest = max(0, int(getattr(b, "destination_dungeon", 0) or 0))
        if dest <= 0:
            continue
        mid = pack_ids.pack_id_to_map_id(str(b.map_id or ""))
        if mid is None:
            continue
        fare = max(0, int(getattr(b, "adena_cost", 0) or 0))
        if adena is not None and fare > int(adena):
            continue
        npcs.append((b, int(mid), int(b.npc_world_x), int(b.npc_world_y), dest))

    links: list[NpcTeleporterLink] = []
    radius = max(0, int(link_radius))
    for b, mid, nx, ny, dest in npcs:
        fare = max(0, int(getattr(b, "adena_cost", 0) or 0))
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
                    map_id=mid,
                    npc_x=nx,
                    npc_y=ny,
                    adena_cost=fare,
                    destination_dungeon=dest,
                    gate_edge_id=str(getattr(t, "edge_id", "") or ""),
                    gate_x=gx,
                    gate_y=gy,
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
