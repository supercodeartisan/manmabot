"""Queries: attackable enemies and loot candidates for mode policies."""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app._03_world import CharacterType, GameState, ObjectStatus, ObjectType
from app._03_world.objects import Position, WorldObject
from app._03_world.world_coords import (
    ATTACK_PATH_SLACK,
    CLICK_PATH_SLACK,
    WorldOrigin,
    content_to_world,
    in_mage_spell_range,
    max_distance,
    relative_to_absolute,
    tile_chebyshev,
)
from app._04_decision.pathfinding import find_path, is_click_valid
from app._04_decision import player_mode as pm
from app._04_decision.player_mode import LOOT_MODE_ADENA, LOOT_MODE_ALL
from app._04_decision.species_rules import (
    is_avoided_for_state,
    is_blacklisted_object,
    is_sleeping_golem,
)
from app._04_decision.target_selector import MAX_MISSED_FRAMES

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world.terrain_map import TerrainMap
    from app._04_decision.farm_area import FarmRect


def fresh_memory_sweep(game_state: object) -> bool:
    """True when this tick has a print_state entity list (dead mobs are omitted)."""
    snap = getattr(game_state, "last_print_state", None)
    return isinstance(snap, dict) and "entities" in snap


def memory_target_gone(game_state: object, obj: object | None) -> bool:
    """True when memory already dropped this mob (corpse / despawn).

    print_state skips dead entities. GameState still keeps the last cell for
    ``max_age_frames``, so sticky combat used to keep clicking that tile and
    the leftover attack cursor walked the character onto the corpse.
    """
    if obj is None:
        return True
    if getattr(obj, "status", None) is ObjectStatus.DEAD:
        return True
    tid = getattr(obj, "track_id", None)
    missing = getattr(game_state, "missing_frames", None)
    missed = int(missing(tid)) if callable(missing) and tid is not None else 0
    return bool(fresh_memory_sweep(game_state) and missed >= 1)


def _reachable(game_state: GameState, obj: WorldObject) -> bool:
    if obj.status is ObjectStatus.DEAD:
        return False
    if memory_target_gone(game_state, obj):
        obj.status = ObjectStatus.DEAD
        return False
    # Vision occlusion must not hide a live memory entity (species filter
    # is separate and does not use the 8-tile click range).
    if obj.occluded:
        rx = getattr(obj, "world_rx", None)
        cx = getattr(obj, "world_cx", None)
        if rx is None and cx is None:
            return False
    if game_state.missing_frames(obj.track_id) > MAX_MISSED_FRAMES:
        return False
    return True


def _is_mage(game_state: GameState) -> bool:
    player = game_state.player
    return player is not None and player.character_type is CharacterType.MAGE


def tile_distance_from_player(obj: WorldObject) -> int:
    """Chebyshev tiles from local player (relative WCS origin) to object."""
    from app._03_world.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return known
    tile = content_to_world(obj.position.x, obj.position.y)
    return max_distance(tile, Position(0.0, 0.0))


def relative_tile_xy(obj: object) -> tuple[int, int] | None:
    """Player-relative tile (dx, dy). Memory cells win over screen UV."""
    rx = getattr(obj, "world_rx", None)
    ry = getattr(obj, "world_ry", None)
    if rx is not None and ry is not None:
        return int(rx), int(ry)
    pos = getattr(obj, "position", None)
    if pos is None:
        return None
    try:
        tile = content_to_world(float(pos.x), float(pos.y))
    except (TypeError, ValueError, AttributeError):
        return None
    return int(tile.x), int(tile.y)


def in_near_monster_box(obj: object | None) -> bool:
    """True when ``obj`` sits in the 4-wide × 5-high tile box around the player."""
    if obj is None:
        return False
    cell = relative_tile_xy(obj)
    if cell is None:
        return False
    dx, dy = cell
    return (
        abs(dx) <= int(pm.NEAR_MONSTER_WIDTH_TILES)
        and abs(dy) <= int(pm.NEAR_MONSTER_HEIGHT_TILES)
    )


def in_loot_approach_threat(obj: object | None) -> bool:
    """True when ``obj`` is within the loot-walk interrupt radius (Chebyshev 5)."""
    if obj is None:
        return False
    try:
        return tile_distance_from_player(obj) <= int(pm.LOOT_APPROACH_THREAT_TILES)
    except (TypeError, ValueError):
        return False


def in_attack_click_range(obj: object | None) -> bool:
    """True when the mob can be clicked from here.

    On-screen is enough — this is not a species blacklist. The 8-tile
    value only covers off-screen memory so we still click nearby cells
    without walking adjacent first.
    """
    if obj is None:
        return False
    if object_on_screen(obj):
        return True
    from app._03_world.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return int(known) <= int(pm.ATTACK_CLICK_TILES)
    try:
        return tile_distance_from_player(obj) <= int(pm.ATTACK_CLICK_TILES)
    except (TypeError, ValueError):
        return False


def sticky_holds_loot(obj: object | None) -> bool:
    """True when an unfinished close fight (≤2 tiles) still beats loot."""
    if obj is None:
        return False
    try:
        return tile_distance_from_player(obj) <= int(pm.STICKY_LOOT_HOLD_TILES)
    except (TypeError, ValueError):
        return False


def loot_in_view(obj: object | None) -> bool:
    """True when the pile is on-screen or within memory keep tiles."""
    if obj is None:
        return False
    if object_on_screen(obj):
        return True
    try:
        return tile_distance_from_player(obj) <= int(pm.LOOT_KEEP_TILES)
    except (TypeError, ValueError):
        return False


def object_on_screen(obj: object | None) -> bool:
    """True when the object's content UV is inside the main client window."""
    if obj is None:
        return False
    pos = getattr(obj, "position", None)
    if pos is None:
        return False
    try:
        x = float(pos.x)
        y = float(pos.y)
    except (TypeError, ValueError, AttributeError):
        return False
    return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def _attack_candidates(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
) -> list[WorldObject]:
    """Monsters eligible before path/LOS filters.

    Attack yes/no is the operator allow/deny list only. Player vs monster
    level is not compared. Sleeping golems stay skipped.
    """
    by_id: dict[int, WorldObject] = {}
    for obj in game_state.monsters():
        if is_blacklisted_object(obj) or is_avoided_for_state(game_state, obj):
            continue
        if is_sleeping_golem(obj):
            continue
        if not _reachable(game_state, obj):
            continue
        by_id[obj.track_id] = obj
    candidates = list(by_id.values())
    if exclude:
        candidates = [o for o in candidates if o.track_id not in exclude]
    return candidates


def attack_line_clear(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
) -> bool:
    """Dungeon rule: segment player→monster has no blocked tiles."""
    from app._04_decision.dungeon import line_of_sight_clear
    from app._04_decision.nav_config import get_terrain_map

    if terrain is None:
        terrain = get_terrain_map()
    if terrain is None:
        return True
    start = (int(origin.x), int(origin.y))
    goal = object_absolute_tile(obj, origin)
    return line_of_sight_clear(terrain, start, goal)


def can_engage_target(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
) -> bool:
    """Whether a monster is attackable under map terrain rules.

    Island keeps click-range OR A* detour when the straight line is clear.
    When a wall/fence sits on the player→monster segment, engage only if an
    A* detour exists (or the mob is adjacent so a click does not need LOS).
    Dungeon: click-range OR straight LOS (intermediate tiles only).
    """
    from app._03_world.world_coords import tile_chebyshev
    from app._04_decision.dungeon import is_dungeon_map

    if is_dungeon_map():
        return in_attack_click_range(obj) or attack_line_clear(obj, origin, terrain)
    los = attack_line_clear(obj, origin, terrain)
    path_ok = attack_path_clickable(obj, origin, terrain)
    in_range = in_attack_click_range(obj)
    if los:
        return in_range or path_ok
    # Wall/fence on the line — detour path, or already next to the mob.
    if path_ok:
        return True
    try:
        if tile_distance_from_player(obj) <= 1:
            return True
    except (TypeError, ValueError):
        pass
    goal = object_absolute_tile(obj, origin)
    if tile_chebyshev(int(origin.x), int(origin.y), goal[0], goal[1]) <= 1:
        return True
    return False


def list_attackable(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
) -> list[WorldObject]:
    """Reachable monsters for combat selection.

    Island: click range or A* path, plus wall/fence gate (detour required when
    LOS is blocked). Dungeon: click range or straight-line LOS. Mage candidates
    must still be in spell range. Species allow/deny is the only attack
    eligibility gate (no level compare).
    """
    candidates = _attack_candidates(game_state, exclude=exclude)
    if _is_mage(game_state):
        candidates = [
            o
            for o in candidates
            if in_mage_spell_range(o.position.x, o.position.y)
        ]
    if check_path and origin is not None:
        candidates = [
            o for o in candidates if can_engage_target(o, origin)
        ]
    return candidates


def count_attackable(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
) -> int:
    return len(
        list_attackable(
            game_state, exclude=exclude, origin=origin, check_path=check_path
        )
    )


def count_monsters_within_tiles(
    game_state: GameState,
    tiles: int,
) -> int:
    """Living monsters inside a Chebyshev disk around the player.

    Dead, omitted, sleeping-golem, and scarecrow rows are ignored. Species
    allow/deny and walk-path are not applied — this is a surround count.
    """
    from app._04_decision.species_rules import (
        is_scarecrow_species,
        is_sleeping_golem,
    )

    limit = max(0, int(tiles))
    total = 0
    monsters = game_state.monsters() if hasattr(game_state, "monsters") else ()
    for obj in monsters:
        if obj is None:
            continue
        kind = getattr(obj, "object_type", None)
        if kind is not None and kind is not ObjectType.MONSTER:
            continue
        if getattr(obj, "status", None) is ObjectStatus.DEAD:
            continue
        if memory_target_gone(game_state, obj):
            continue
        if is_sleeping_golem(obj) or is_scarecrow_species(obj):
            continue
        try:
            if tile_distance_from_player(obj) <= limit:
                total += 1
        except (TypeError, ValueError):
            continue
    return total


def _is_adena(obj: WorldObject) -> bool:
    detail = (obj.detail_classification or "").strip().lower()
    species = (obj.species_name or "").strip().lower()
    name = ""
    if obj.identity is not None and getattr(obj.identity, "name", None):
        name = str(obj.identity.name).strip().lower()
    blob = f"{detail} {species} {name}"
    # English, Korean, and the Chinese labels used on the live client.
    if "adena" in blob or "아데나" in blob or "金幣" in blob or "金币" in blob:
        return True
    # Weight-gate adena-only must not skip unnamed piles (name read often empty).
    named = species if species not in {"item", "grounditem"} else ""
    if name in {"item", "grounditem"}:
        name = ""
    return not named and not name


def is_adena(obj: WorldObject) -> bool:
    """True when the ground item is adena (아데나)."""
    return _is_adena(obj)


def object_absolute_tile(
    obj: WorldObject,
    origin: WorldOrigin,
) -> tuple[int, int]:
    """Absolute nav tile. Memory world cells win over the screen-UV estimate."""
    from app._03_world.world_coords import memory_nav_tile

    cell = memory_nav_tile(obj)
    if cell is not None:
        return cell
    rel = content_to_world(obj.position.x, obj.position.y)
    return relative_to_absolute(rel.x, rel.y, origin)


def _path_within_slack(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"],
    *,
    slack: int,
) -> bool:
    """True when A* steps to ``obj`` are ≤ Chebyshev + ``slack``.

    If ``terrain`` is ``None``, tries ``get_terrain_map()`` and returns True
    when none is loaded (tests / boot). Explicit empty path (blocked) → False.
    """
    if terrain is None:
        from app._04_decision.nav_config import get_terrain_map

        terrain = get_terrain_map()
    if terrain is None:
        return True

    start = (int(origin.x), int(origin.y))
    goal = object_absolute_tile(obj, origin)
    # Adjacent (or same cell): click the sprite; A* to an occupied / blocked
    # monster tile must not hide a mob standing next to the player.
    if tile_chebyshev(start[0], start[1], goal[0], goal[1]) <= 1:
        return True
    path = find_path(terrain, start, goal)
    if len(path) < 2:
        # Same tile: already on it (or start==goal); clicking is fine.
        return len(path) == 1 and path[0] == start
    return is_click_valid(path, len(path) - 1, slack=slack)


def loot_path_clickable(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
    *,
    slack: int | None = None,
) -> bool:
    """True when a near-straight walk to the item exists (click will not stick).

    Uses the same rule as travel clicks: A* path steps ≤ Chebyshev + slack.
    Default slack is :data:`CLICK_PATH_SLACK` (3).
    """
    if slack is None:
        slack = CLICK_PATH_SLACK
    return _path_within_slack(obj, origin, terrain, slack=slack)


def attack_path_clickable(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
    *,
    slack: int | None = None,
) -> bool:
    """True when a near-straight walk to the monster exists (not walled off).

    Same rule as loot: A* path steps ≤ Chebyshev + slack.
    Default slack is :data:`ATTACK_PATH_SLACK` (4).
    """
    if slack is None:
        slack = ATTACK_PATH_SLACK
    return _path_within_slack(obj, origin, terrain, slack=slack)


def list_lootable(
    game_state: GameState,
    *,
    loot_mode: str = LOOT_MODE_ALL,
    farm: Optional["FarmRect"] = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
    exclude: Optional[set[int]] = None,
    screen_only: bool = False,
) -> list[WorldObject]:
    """Reachable ground items, optionally filtered to adena and/or farm rect.

    When ``farm`` and ``origin`` are set (farming), items whose absolute tile
    lies outside the active farm are ignored so the bot does not leave the
    farm chasing edge loot.

    ``check_path`` is accepted for callers but does not hide a live memory
    item: the pile is gone only when it leaves the entity list.
    """
    del check_path
    skip = exclude or set()
    # Live memory entities are the loot list. Drop GameState ghosts the same
    # way combat does: print_state already omitted the pile.
    candidates = [
        obj
        for obj in game_state.items()
        if obj.track_id not in skip and not memory_target_gone(game_state, obj)
    ]
    if screen_only:
        candidates = [o for o in candidates if loot_in_view(o)]
    if loot_mode == LOOT_MODE_ADENA:
        candidates = [o for o in candidates if _is_adena(o)]
    else:
        from app._04_decision.ground_loot import ground_item_allowed

        candidates = [o for o in candidates if ground_item_allowed(o)]
    if farm is not None and origin is not None:
        candidates = [
            o
            for o in candidates
            if _loot_in_farm(o, farm, origin)
        ]
    return candidates


def _loot_in_farm(
    obj: WorldObject,
    farm: "FarmRect",
    origin: WorldOrigin,
    *,
    slack: int = 3,
) -> bool:
    """True when the pile is in the farm, on the edge, or at the player's feet."""
    if tile_distance_from_player(obj) <= 2:
        return True
    x, y = object_absolute_tile(obj, origin)
    if farm.contains(x, y):
        return True
    return (
        farm.x0 - slack <= x <= farm.x1 + slack
        and farm.y0 - slack <= y <= farm.y1 + slack
    )


def nearest_attackable(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
    near_box: bool = False,
    near_tiles: int | None = None,
    screen_only: bool = False,
) -> Optional[WorldObject]:
    cands = list_attackable(
        game_state, exclude=exclude, origin=origin, check_path=check_path
    )
    if screen_only:
        cands = [o for o in cands if object_on_screen(o)]
    if near_tiles is not None:
        limit = int(near_tiles)
        cands = [o for o in cands if tile_distance_from_player(o) <= limit]
    elif near_box:
        cands = [o for o in cands if in_near_monster_box(o)]
    if not cands:
        return None
    return min(
        cands,
        key=lambda o: (
            tile_distance_from_player(o),
            int(getattr(o, "track_id", 0)),
        ),
    )


def nearest_lootable(
    game_state: GameState,
    *,
    loot_mode: str = LOOT_MODE_ALL,
    farm: Optional["FarmRect"] = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
    exclude: Optional[set[int]] = None,
    screen_only: bool = False,
) -> Optional[WorldObject]:
    cands = list_lootable(
        game_state,
        loot_mode=loot_mode,
        farm=farm,
        origin=origin,
        check_path=check_path,
        exclude=exclude,
        screen_only=screen_only,
    )
    if not cands:
        return None
    return min(
        cands,
        key=lambda o: (
            tile_distance_from_player(o),
            int(getattr(o, "track_id", 0)),
        ),
    )


def prefer_loot_over_combat(
    d_item: int,
    d_enemy: int,
    *,
    max_item_tiles: int = 7,
) -> bool:
    """Farm rule: loot if item is within half the enemy distance and ≤ max tiles."""
    if d_item > max_item_tiles:
        return False
    return d_item * 2 <= d_enemy


__all__ = [
    "fresh_memory_sweep",
    "memory_target_gone",
    "attack_path_clickable",
    "attack_line_clear",
    "can_engage_target",
    "count_attackable",
    "count_monsters_within_tiles",
    "list_attackable",
    "list_lootable",
    "loot_path_clickable",
    "nearest_attackable",
    "nearest_lootable",
    "prefer_loot_over_combat",
    "tile_distance_from_player",
    "relative_tile_xy",
    "in_near_monster_box",
    "in_loot_approach_threat",
    "in_attack_click_range",
    "sticky_holds_loot",
    "loot_in_view",
    "object_on_screen",
    "object_absolute_tile",
    "is_adena",
]
