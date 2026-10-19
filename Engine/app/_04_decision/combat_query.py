"""L6 queries: attackable / loot candidates (no ActionIntent emit).

Live engage selection for L5. See ``Docs/architecture/DECISION_HIERARCHY.md``.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Optional

from app._03_world import CharacterType, GameState, ObjectStatus, ObjectType
from app._02_state.objects import Position, WorldObject
from app._03_world.space.world_coords import (
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
    from app._03_world.space.terrain_map import TerrainMap
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

    ``force_attacks_me`` synthetics stay alive only while that entity's
    print_state row still has AttackAction tgt == MyPlayer. Dead or bait
    synthetics are always treated as gone (no finish_kill hold).
    """
    if obj is None:
        return True
    if getattr(obj, "status", None) is ObjectStatus.DEAD:
        return True
    if bool(getattr(obj, "bait", False)):
        return True
    if getattr(obj, "force_attacks_me", False):
        ent = str(getattr(obj, "memory_ent", None) or "").strip().lower()
        if not ent:
            return True
        from app._03_world.merge.memory_entities import attacks_targeting_me

        rows = attacks_targeting_me(getattr(game_state, "last_print_state", None))
        return not any(
            str(r.get("ent") or "").strip().lower() == ent for r in rows
        )
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
    from app._03_world.space.world_coords import distance_tiles_from_memory

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
    from app._03_world.space.world_coords import distance_tiles_from_memory

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


def loot_within_engage_tiles(obj: object | None) -> bool:
    """True when Chebyshev distance to the pile is below ``LOOT_ENGAGE_MAX_TILES``."""
    if obj is None:
        return False
    try:
        return tile_distance_from_player(obj) < int(pm.LOOT_ENGAGE_MAX_TILES)
    except (TypeError, ValueError):
        return False


def loot_in_view(obj: object | None) -> bool:
    """True when the pile is on-screen or within memory keep tiles.

    Far piles (≥ ``LOOT_ENGAGE_MAX_TILES``) are excluded even if on-screen.
    """
    if obj is None:
        return False
    if not loot_within_engage_tiles(obj):
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
    level is not compared. Sleeping golems and bait/dormant mobs stay skipped
    (including ``force_attacks_me`` self-defense synthetics).
    """
    by_id: dict[int, WorldObject] = {}
    for obj in game_state.monsters():
        if is_blacklisted_object(obj) or is_avoided_for_state(game_state, obj):
            continue
        if is_sleeping_golem(obj):
            continue
        if bool(getattr(obj, "bait", False)):
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


# Last dungeon path-cap skips from ``list_attackable`` / ``list_lootable``
# (debug UI / dungeon combat GUI). Kind-scoped so loot does not wipe combat.
_PATH_CAP_SKIPS: list[dict] = []


def path_cap_skips() -> list[dict]:
    """Recent dungeon A* path-cap skips for the debug snapshot / UI."""
    return list(_PATH_CAP_SKIPS)


def path_cap_skip_reason(steps: int | None, *, limit: int | None = None) -> str:
    """Exact UI/log reason when a dungeon new target fails the path cap."""
    cap = int(pm.DUNGEON_ENGAGE_MAX_PATH_TILES if limit is None else limit)
    if steps is None:
        return f"path>{cap}:blocked"
    return f"path>{cap}:{int(steps)}"


def _note_path_cap_skips(kind: str, rows: list[dict]) -> None:
    global _PATH_CAP_SKIPS
    kept = [row for row in _PATH_CAP_SKIPS if row.get("kind") != kind]
    _PATH_CAP_SKIPS = (kept + list(rows))[-24:]


def dungeon_engage_path_measure(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
) -> tuple[bool, int | None]:
    """Measure dungeon A* steps for the new-target path cap.

    Returns ``(apply_cap, steps)``.
    - ``apply_cap`` False → non-dungeon / no terrain → caller treats as OK.
    - ``steps`` 0 when adjacent; ``None`` when no path; else A* step count.
    """
    from app._04_decision.dungeon import is_dungeon_map
    from app._04_decision.nav_config import get_terrain_map

    if not is_dungeon_map():
        return False, None
    if terrain is None:
        terrain = get_terrain_map()
    if terrain is None:
        return False, None
    start = (int(origin.x), int(origin.y))
    goal = object_absolute_tile(obj, origin)
    if tile_chebyshev(start[0], start[1], goal[0], goal[1]) <= 1:
        return True, 0
    path = find_path(terrain, start, goal)
    if not path:
        return True, None
    return True, max(0, len(path) - 1)


def dungeon_new_engage_path_ok(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
) -> bool:
    """Dungeon new-target gate: A* steps must be ≤ ``DUNGEON_ENGAGE_MAX_PATH_TILES``.

    Non-dungeon → True. Missing terrain → True (boot / tests).
    Adjacent (Chebyshev ≤ 1) → True. Sticky combat/loot must not call this
    to drop an existing lock — only ``list_attackable`` / ``list_lootable``.
    """
    apply_cap, steps = dungeon_engage_path_measure(obj, origin, terrain)
    if not apply_cap:
        return True
    if steps is None:
        return False
    return steps <= int(pm.DUNGEON_ENGAGE_MAX_PATH_TILES)


def _filter_dungeon_path_cap(
    candidates: list[WorldObject],
    origin: WorldOrigin,
    *,
    kind: str,
    limit: int | None = None,
) -> list[WorldObject]:
    """Drop dungeon candidates over the A* path cap; record UI skip reasons."""
    cap = int(pm.DUNGEON_ENGAGE_MAX_PATH_TILES if limit is None else limit)
    kept: list[WorldObject] = []
    skips: list[dict] = []
    for obj in candidates:
        apply_cap, steps = dungeon_engage_path_measure(obj, origin)
        if not apply_cap:
            kept.append(obj)
            continue
        if steps is not None and steps <= cap:
            kept.append(obj)
            continue
        reason = path_cap_skip_reason(steps, limit=cap)
        tid = int(getattr(obj, "track_id", 0) or 0)
        skips.append(
            {
                "id": tid,
                "kind": kind,
                "steps": steps,
                "limit": cap,
                "reason": reason,
            }
        )
        from app.bot_log import get_logger

        get_logger("combat").info(
            "dungeon path cap skip id=%s kind=%s reason=%s",
            tid,
            kind,
            reason,
        )
    _note_path_cap_skips(kind, skips)
    return kept


def can_engage_target(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"] = None,
) -> bool:
    """Whether a monster can be shot from here.

    A blocked tile on the straight line between the character and the
    monster blocks the attack. The monster's own tile does not count.
    A clear line inside click range is attackable. The client walk
    polyline is a walking-click test and is not consulted here.
    """
    if not attack_line_clear(obj, origin, terrain):
        return False
    return in_attack_click_range(obj)


def _guid_key(value: object) -> int | None:
    """Normalize ``0x...`` / decimal guid text. ``0`` and blank are absent."""
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def contested_mob_guids(game_state: GameState) -> set[int]:
    """Monster guids currently targeted by a visible other player.

    Built from print_state rows: another Player, or a summon whose owner is
    not me, with AttackAction tgt equal to a Monster ``guid``. That guid is
    the same id handoff stores as ``memory_guid``. Empty means free to engage.
    World cells are not used.
    """
    from app._03_world.merge.memory_entities import contested_monster_guids

    return contested_monster_guids(getattr(game_state, "last_print_state", None))


def is_contested_monster(game_state: GameState, obj: WorldObject) -> bool:
    """True when ``obj.memory_guid`` is a contested_mobs claim.

    A monster with no guid is not claimed. A shared world cell is not a claim.
    """
    key = _guid_key(getattr(obj, "memory_guid", None))
    if key is None:
        return False
    return key in contested_mob_guids(game_state)


def _monster_skip_label(obj: WorldObject) -> str:
    name = str(getattr(obj, "species_name", None) or getattr(obj, "label", None) or "")
    name = name.strip() or "?"
    tid = int(getattr(obj, "track_id", 0) or 0)
    try:
        dist = int(tile_distance_from_player(obj))
        return f"{tid}:{name}:d{dist}"
    except (TypeError, ValueError):
        return f"{tid}:{name}"


_contested_log_at = 0.0


def _note_contested_guid_filter(
    claimed: set[int],
    dropped: list[WorldObject],
) -> None:
    """One combat log line per second while other players hold mob guids."""
    global _contested_log_at
    if not claimed:
        return
    import time

    now = time.time()
    if now - _contested_log_at < 1.0:
        return
    _contested_log_at = now
    if dropped:
        parts = [
            f"{_monster_skip_label(obj)}:{getattr(obj, 'memory_guid', None) or '?'}"
            for obj in dropped[:6]
        ]
        text = ",".join(parts)
        if len(dropped) > 6:
            text += f" +{len(dropped) - 6}"
    else:
        text = "none"
    from app.bot_log import get_logger

    get_logger("combat").info(
        "contested guid filter claimed=%s dropped=%s",
        len(claimed),
        text,
    )


def describe_attackable_filter_skips(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    screen_only: bool = True,
    check_path: bool = True,
    limit: int = 6,
) -> str:
    """Compact why base candidates failed screen/path filters (debug).

    Empty string when there are no base candidates or no skips among the
    nearest ``limit`` monsters. Groups: ``off_screen``, ``contested``,
    ``mage_range``, ``path``, ``path_cap``. Does not mutate path-cap UI state.
    """
    base = _attack_candidates(game_state, exclude=exclude)
    if not base:
        return ""

    def _dist_key(o: WorldObject) -> int:
        try:
            return int(tile_distance_from_player(o))
        except (TypeError, ValueError):
            return 10**9

    ordered = sorted(base, key=_dist_key)
    claimed = contested_mob_guids(game_state)
    mage = _is_mage(game_state)
    cap = max(1, int(limit))
    buckets: dict[str, list[str]] = {
        "off_screen": [],
        "contested": [],
        "mage_range": [],
        "path": [],
        "path_cap": [],
    }
    passed = 0
    considered = 0
    for obj in ordered:
        if considered >= cap:
            break
        considered += 1
        label = _monster_skip_label(obj)
        guid = _guid_key(getattr(obj, "memory_guid", None))
        if claimed and guid is not None and guid in claimed:
            buckets["contested"].append(label)
            continue
        if screen_only and not object_on_screen(obj):
            buckets["off_screen"].append(label)
            continue
        if mage and not in_mage_spell_range(obj.position.x, obj.position.y):
            buckets["mage_range"].append(label)
            continue
        if check_path and origin is not None:
            if not can_engage_target(obj, origin):
                buckets["path"].append(label)
                continue
            apply_cap, steps = dungeon_engage_path_measure(obj, origin)
            if apply_cap and (
                steps is None or steps > int(pm.DUNGEON_ENGAGE_MAX_PATH_TILES)
            ):
                why = path_cap_skip_reason(steps)
                buckets["path_cap"].append(f"{label}({why})")
                continue
        passed += 1

    parts = [f"{k}={','.join(v)}" for k, v in buckets.items() if v]
    if not parts:
        return ""
    return f"base={len(base)} near={considered} pass={passed} " + " ".join(parts)


def list_attackable(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
    screen_only: bool = False,
) -> list[WorldObject]:
    """Reachable monsters for combat selection.

    A clear straight line inside click range. A blocked tile between the
    character and the monster rejects the shot on every map. The client
    walk polyline is not an attack gate. Mage candidates must still be in
    spell range. Species allow/deny is the only attack eligibility gate
    (no level compare).

    ``screen_only`` drops off-screen monsters before the path search. The
    nearest on-screen monster is unchanged; far monsters are not searched.

    Dungeon new picks also drop monsters whose A* route exceeds
    ``DUNGEON_ENGAGE_MAX_PATH_TILES`` (sticky locks do not use this list).

    Monsters claimed by a visible other player's AttackAction
    (``contested_mobs`` guid == ``memory_guid``) are skipped for *new*
    engages. A missing guid is not a claim. Sticky /
    ``nearest_attacks_me_force`` do not use this list.

    Bait/dormant monsters (``WorldObject.bait``) are always skipped, including
    ``force_attacks_me`` synthetics.
    """
    candidates = _attack_candidates(game_state, exclude=exclude)
    claimed = contested_mob_guids(game_state)
    if claimed:
        kept: list[WorldObject] = []
        dropped: list[WorldObject] = []
        for obj in candidates:
            guid = _guid_key(getattr(obj, "memory_guid", None))
            if guid is not None and guid in claimed:
                dropped.append(obj)
                continue
            kept.append(obj)
        candidates = kept
        _note_contested_guid_filter(claimed, dropped)
    if screen_only:
        candidates = [o for o in candidates if object_on_screen(o)]
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
        candidates = _filter_dungeon_path_cap(
            candidates, origin, kind="monster"
        )
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


def _named_adena(obj: WorldObject) -> bool:
    """True only when a label actually says adena.

    Empty names stay false. ``_is_adena`` still treats those piles as adena
    for the weight gate and adena priority.
    """
    detail = (obj.detail_classification or "").strip().lower()
    species = (obj.species_name or "").strip().lower()
    name = ""
    if obj.identity is not None and getattr(obj.identity, "name", None):
        name = str(obj.identity.name).strip().lower()
    blob = f"{detail} {species} {name}"
    return (
        "adena" in blob
        or "아데나" in blob
        or "金幣" in blob
        or "金币" in blob
    )


def small_adena_ignored(obj: WorldObject) -> bool:
    """True when a named adena pile is at or below the UI qty.

    Unnamed piles are not subject to this gate. Feet F4 does not call it.
    """
    if not pm.IGNORE_SMALL_ADENA:
        return False
    if not _named_adena(obj):
        return False
    qty = getattr(obj, "loot_qty", None)
    if qty is None:
        return False
    try:
        return int(qty) <= int(pm.IGNORE_SMALL_ADENA_QTY)
    except (TypeError, ValueError):
        return False


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
    from app._03_world.space.world_coords import memory_nav_tile

    cell = memory_nav_tile(obj)
    if cell is not None:
        return cell
    rel = content_to_world(obj.position.x, obj.position.y)
    return relative_to_absolute(rel.x, rel.y, origin)


_PATH_OK_CACHE: "OrderedDict[tuple, bool]" = OrderedDict()
_PATH_OK_CACHE_MAX = 512


def _path_ok_key(terrain: object, start: tuple[int, int], goal: tuple[int, int], slack: int) -> tuple:
    return (id(terrain), start, goal, int(slack))


def _path_ok_cached(
    terrain: object,
    start: tuple[int, int],
    goal: tuple[int, int],
    slack: int,
) -> bool | None:
    key = _path_ok_key(terrain, start, goal, slack)
    if key not in _PATH_OK_CACHE:
        return None
    _PATH_OK_CACHE.move_to_end(key)
    return _PATH_OK_CACHE[key]


def _path_ok_store(
    terrain: object,
    start: tuple[int, int],
    goal: tuple[int, int],
    slack: int,
    ok: bool,
) -> None:
    key = _path_ok_key(terrain, start, goal, slack)
    _PATH_OK_CACHE[key] = bool(ok)
    _PATH_OK_CACHE.move_to_end(key)
    while len(_PATH_OK_CACHE) > _PATH_OK_CACHE_MAX:
        _PATH_OK_CACHE.popitem(last=False)


def _path_within_slack(
    obj: WorldObject,
    origin: WorldOrigin,
    terrain: Optional["TerrainMap"],
    *,
    slack: int,
) -> bool:
    """True when a ground click toward ``obj`` follows a clear client walk.

    Uses the same client-polyline walkability gate as travel hops (A* slack
    is only a no-terrain fallback). If ``terrain`` is ``None``, tries
    ``get_terrain_map()`` and returns True when none is loaded (tests / boot).
    Explicit empty path (blocked) → False.
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
    cached = _path_ok_cached(terrain, start, goal, slack)
    if cached is not None:
        return cached
    path = find_path(terrain, start, goal)
    if len(path) < 2:
        # Same tile: already on it (or start==goal); clicking is fine.
        ok = len(path) == 1 and path[0] == start
    else:
        ok = is_click_valid(path, len(path) - 1, slack=slack, terrain=terrain)
    _path_ok_store(terrain, start, goal, slack, ok)
    return ok


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
    ownership_filter: bool = True,
) -> list[WorldObject]:
    """Reachable ground items, optionally filtered to adena and/or farm rect.

    When ``farm`` and ``origin`` are set (farming), items whose absolute tile
    lies outside the active farm are ignored so the bot does not leave the
    farm chasing edge loot.

    ``check_path`` (default True): dungeon new picks also drop piles whose
    A* route exceeds ``DUNGEON_LOOT_MAX_PATH_TILES``. Sticky loot already
    locked is not filtered here. Island / non-dungeon ignores path length.

    ``ownership_filter`` (default True): main-intent loot keeps only FREE
    piles or contrib > 50. Side-intent F4 passes False to skip this gate.
    The same main-only path drops named adena at or below
    ``IGNORE_SMALL_ADENA_QTY`` when that checkbox is on. Feet F4 keeps them.
    """
    skip = exclude or set()
    # Live memory entities are the loot list. Drop GameState ghosts the same
    # way combat does: print_state already omitted the pile.
    candidates = [
        obj
        for obj in game_state.items()
        if obj.track_id not in skip and not memory_target_gone(game_state, obj)
    ]
    # Cap engage range even when the pile is still on-screen / in memory.
    candidates = [o for o in candidates if loot_within_engage_tiles(o)]
    if screen_only:
        candidates = [o for o in candidates if loot_in_view(o)]
    if loot_mode == LOOT_MODE_ADENA:
        candidates = [o for o in candidates if _is_adena(o)]
    else:
        from app._04_decision.ground_loot import ground_item_allowed

        candidates = [o for o in candidates if ground_item_allowed(o)]
    if ownership_filter:
        from app._04_decision.ground_loot import loot_ownership_allowed

        candidates = [o for o in candidates if loot_ownership_allowed(o)]
        # Feet F4 passes ownership_filter=False and must still pick small adena.
        candidates = [o for o in candidates if not small_adena_ignored(o)]
    if farm is not None and origin is not None:
        candidates = [
            o
            for o in candidates
            if _loot_in_farm(o, farm, origin)
        ]
    if check_path and origin is not None:
        candidates = _filter_dungeon_path_cap(
            candidates,
            origin,
            kind="item",
            limit=int(pm.DUNGEON_LOOT_MAX_PATH_TILES),
        )
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


def player_attacking_me(game_state: GameState) -> dict | None:
    """Another Player whose print_state AttackAction target is MyPlayer.

    Force-engage uses monsters only. This row is the PK escape signal.
    """
    from app._03_world.merge.memory_entities import player_targeting_me

    return player_targeting_me(getattr(game_state, "last_print_state", None))


# Reserved track_id band for attacks_me synthetics (avoid print_state TrackIds).
_FORCE_TRACK_BASE = 0x70000000


def _attacks_me_cell(row: dict) -> tuple[int, int] | None:
    world = row.get("world") if isinstance(row.get("world"), dict) else None
    if world is not None:
        try:
            return int(world["cx"]), int(world["cy"])
        except (KeyError, TypeError, ValueError):
            pass
    return None


def _force_track_id(ent: str) -> int:
    text = str(ent or "").strip().lower().replace("0x", "")
    try:
        n = int(text, 16)
    except ValueError:
        n = abs(hash(text)) & 0x0FFFFFFF
    tid = _FORCE_TRACK_BASE | (n & 0x0FFFFFFF)
    if tid == 0 or tid == _FORCE_TRACK_BASE:
        tid = _FORCE_TRACK_BASE | 1
    return int(tid)


def _player_world_xy(game_state: GameState) -> tuple[int, int] | None:
    snap = getattr(game_state, "last_print_state", None)
    if not isinstance(snap, dict):
        return None
    player = snap.get("player") if isinstance(snap.get("player"), dict) else None
    if player is None:
        return None
    try:
        return int(player["x"]), int(player["y"])
    except (KeyError, TypeError, ValueError):
        return None


_attacks_me_cell_logged: dict[str, tuple] = {}


def _note_attacks_me_cell(
    ent: str,
    cell: tuple[int, int] | None,
    *,
    screen_id: int | None = None,
    synthetic_id: int | None = None,
) -> None:
    """Record the cell attacks_me read, and whether it bound the screen monster.

    Does not change matching. Repeats of the same ent/cell/id are skipped.
    """
    from app.bot_log import get_logger

    key = (cell, screen_id, synthetic_id)
    if _attacks_me_cell_logged.get(ent) == key:
        return
    _attacks_me_cell_logged[ent] = key
    if len(_attacks_me_cell_logged) > 64:
        _attacks_me_cell_logged.pop(next(iter(_attacks_me_cell_logged)))
    log = get_logger("combat")
    if cell is None:
        log.info("attacks_me actor id=%s cell=absent", ent)
    else:
        log.info("attacks_me actor id=%s cell=(%s,%s)", ent, int(cell[0]), int(cell[1]))
    if screen_id is not None:
        log.info("matched screen monster id=%s attacked_me=true", int(screen_id))
    elif synthetic_id is not None and cell is not None:
        log.info(
            "attacks_me synthetic id=%s cell=(%s,%s)",
            int(synthetic_id),
            int(cell[0]),
            int(cell[1]),
        )


def sync_attacks_me_force_targets(game_state: GameState) -> list[WorldObject]:
    """Mark print_state attackers in GameState; mark dropped synthetics dead.

    A Monster or SummonedMonster whose AttackAction tgt is MyPlayer matches
    the live object with the same guid. A missing cell does not drop that
    row. A synthetic is created only when that same row is not already in
    GameState, and it uses that row's own world cell.
    """
    from app._03_world.merge.memory_entities import attacks_targeting_me
    from app._02_state.objects import Identity, ObjectStatus, Position, Relationship
    from app._03_world.space.world_coords import world_to_content

    rows = attacks_targeting_me(getattr(game_state, "last_print_state", None))
    live_ents: set[str] = set()
    screen_bound: set[str] = set()
    out: list[WorldObject] = []

    by_guid: dict[int, list[WorldObject]] = {}
    for obj in game_state.monsters():
        if getattr(obj, "force_attacks_me", False):
            continue
        key = _guid_key(getattr(obj, "memory_guid", None))
        if key is None:
            continue
        if not _reachable(game_state, obj):
            continue
        by_guid.setdefault(key, []).append(obj)

    for row in rows:
        if not isinstance(row, dict):
            continue
        ent = str(row.get("ent") or "").strip()
        if not ent:
            continue
        live_ents.add(ent.lower())
        guid_text = str(row.get("guid") or "").strip()
        name = str(row.get("name") or "").strip()
        cell = _attacks_me_cell(row)
        matches = by_guid.get(_guid_key(guid_text) or -1) or []
        if matches:
            matched = min(matches, key=lambda o: int(o.track_id))
            if bool(getattr(matched, "bait", False)):
                matched.bait = True
                matched.attacked_me = False
                continue
            matched.attacked_me = True
            game_state.touch_object(matched.track_id)
            screen_bound.add(ent.lower())
            if cell is None:
                cx = getattr(matched, "world_cx", None)
                cy = getattr(matched, "world_cy", None)
                if cx is not None and cy is not None:
                    cell = (int(cx), int(cy))
            _note_attacks_me_cell(ent, cell, screen_id=int(matched.track_id))
            out.append(matched)
            continue
        if cell is None:
            _note_attacks_me_cell(ent, None)
            continue

        tid = _force_track_id(ent)
        cx, cy = cell
        px_py = _player_world_xy(game_state)
        if px_py is not None:
            rx, ry = cx - px_py[0], cy - px_py[1]
        else:
            rx = ry = 0
        content = world_to_content(float(rx), float(ry))
        is_bait = bool(row.get("bait", False))
        existing = game_state.get_object(tid)
        if existing is not None:
            existing.object_type = ObjectType.MONSTER
            existing.status = ObjectStatus.ALIVE
            existing.position = Position(x=float(content.x), y=float(content.y))
            existing.world_cx = cx
            existing.world_cy = cy
            existing.world_rx = rx
            existing.world_ry = ry
            existing.species_name = name or existing.species_name or "attacks_me"
            existing.label = name or existing.label or "attacks_me"
            existing.force_attacks_me = True
            existing.memory_ent = ent
            if guid_text:
                existing.memory_guid = guid_text
            existing.occluded = False
            existing.bait = is_bait
            existing.attacked_me = not is_bait
            game_state.upsert_object(existing)
            if not is_bait:
                _note_attacks_me_cell(ent, cell, synthetic_id=int(existing.track_id))
                out.append(existing)
            continue
        obj = WorldObject(
            track_id=tid,
            object_type=ObjectType.MONSTER,
            identity=Identity(name=name or "attacks_me", confidence=1.0),
            position=Position(x=float(content.x), y=float(content.y)),
            status=ObjectStatus.ALIVE,
            relationship=Relationship.ENEMY,
            label=name or "attacks_me",
            species_name=name or "attacks_me",
            species_confidence=1.0,
            world_cx=cx,
            world_cy=cy,
            world_rx=rx,
            world_ry=ry,
            force_attacks_me=True,
            memory_ent=ent,
            memory_guid=guid_text or None,
            bait=is_bait,
            attacked_me=not is_bait,
        )
        game_state.upsert_object(obj)
        if not is_bait:
            _note_attacks_me_cell(ent, cell, synthetic_id=int(obj.track_id))
            out.append(obj)

    # Force synthetics no longer attacking me, or bait → dead (finish_kill
    # must not keep swinging a corpse / dormant bait).
    for obj in list(game_state.monsters()):
        if not getattr(obj, "force_attacks_me", False):
            continue
        if bool(getattr(obj, "bait", False)):
            obj.status = ObjectStatus.DEAD
            obj.attacked_me = False
            continue
        ent = str(getattr(obj, "memory_ent", None) or "").strip().lower()
        if ent and ent in screen_bound:
            obj.status = ObjectStatus.DEAD
            obj.attacked_me = False
            continue
        if ent and ent in live_ents:
            game_state.touch_object(obj.track_id)
            continue
        obj.status = ObjectStatus.DEAD
        obj.attacked_me = False
    for obj in game_state.monsters():
        if getattr(obj, "status", None) is ObjectStatus.DEAD or bool(
            getattr(obj, "bait", False)
        ):
            obj.attacked_me = False
    return out


def monster_hitting_me(game_state: GameState) -> bool:
    """True when a monster or summon is attacking me this tick.

    Uses the AttackAction row only. A blocked path still counts. A dungeon
    blacklisted species does not.
    """
    try:
        attackers = sync_attacks_me_force_targets(game_state)
    except Exception:
        return False
    return any(not _dungeon_ignores_blacklisted_attacker(obj) for obj in attackers)


def _dungeon_ignores_blacklisted_attacker(obj: WorldObject) -> bool:
    """True when a dungeon must not fight this species even if it attacks us."""
    from app._04_decision.dungeon import is_dungeon_map

    if not is_dungeon_map():
        return False
    return is_blacklisted_object(obj)


def list_attacked_me_targets(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
) -> list[WorldObject]:
    """Living monsters latched as having attacked me, ready to engage.

    The latch survives a missing ``attacks_me`` row. Dead, bait, and a mob
    already dropped by this sweep are omitted. Species blacklist is bypassed
    outside dungeons. In a dungeon a blacklisted species that attacks us is
    ignored. Unknown catalog level is not treated as level 0; callers sort
    with ``attacked_me_rank``.
    """
    skip = set(exclude or ())
    living: list[WorldObject] = []
    for obj in game_state.monsters():
        if not getattr(obj, "attacked_me", False):
            continue
        if obj.status is ObjectStatus.DEAD or bool(getattr(obj, "bait", False)):
            continue
        if memory_target_gone(game_state, obj):
            continue
        if not _reachable(game_state, obj):
            continue
        try:
            tid = int(obj.track_id)
        except (TypeError, ValueError):
            continue
        if tid in skip:
            continue
        if _dungeon_ignores_blacklisted_attacker(obj):
            continue
        living.append(obj)
    if not living:
        return []
    player = getattr(game_state, "player", None)
    if (
        player is not None
        and getattr(player, "character_type", None) is CharacterType.MAGE
    ):
        living = [
            obj
            for obj in living
            if in_mage_spell_range(obj.position.x, obj.position.y)
        ]
    if check_path and origin is not None and living:
        kept: list[WorldObject] = []
        for obj in living:
            if getattr(obj, "force_attacks_me", False):
                from app._04_decision.dungeon import is_dungeon_map

                if is_dungeon_map() and not attack_line_clear(obj, origin):
                    continue
                kept.append(obj)
                continue
            if can_engage_target(obj, origin):
                kept.append(obj)
        living = _filter_dungeon_path_cap(kept, origin, kind="attacked_me")
    return living


def nearest_attacks_me_force(
    game_state: GameState,
    *,
    exclude: set[int] | None = None,
    origin: Optional[WorldOrigin] = None,
    check_path: bool = True,
) -> Optional[WorldObject]:
    """Nearest living monster/summon whose AttackAction targets MyPlayer.

    Bypasses species blacklist outside dungeons and does not require the mob
    to already be in the print_state monster list — missing entries are
    synthesized and tracked until their AttackAction ends. A dungeon ignores
    a blacklisted species. Honors give-up / session ``exclude`` so finish_kill
    priority cannot re-stick a just-abandoned id. Mage range / LOS / dungeon
    path-cap still apply when ``check_path`` is set.
    """
    forced = sync_attacks_me_force_targets(game_state)
    if not forced:
        return None
    skip = set(exclude or ())
    living = [
        o
        for o in forced
        if o.status is not ObjectStatus.DEAD
        and not bool(getattr(o, "bait", False))
        and _reachable(game_state, o)
        and int(getattr(o, "track_id", 0) or 0) not in skip
        and not _dungeon_ignores_blacklisted_attacker(o)
    ]
    if not living:
        return None
    if _is_mage(game_state):
        living = [
            o
            for o in living
            if in_mage_spell_range(o.position.x, o.position.y)
        ]
    if check_path and origin is not None:
        # Force synthetics: allow engage when path tools would hide them;
        # still require dungeon LOS when on a dungeon map.
        kept: list[WorldObject] = []
        for o in living:
            if getattr(o, "force_attacks_me", False):
                from app._04_decision.dungeon import is_dungeon_map

                if is_dungeon_map() and not attack_line_clear(o, origin):
                    continue
                kept.append(o)
                continue
            if can_engage_target(o, origin):
                kept.append(o)
        living = _filter_dungeon_path_cap(kept, origin, kind="attacks_me")
    if not living:
        return None
    return min(
        living,
        key=lambda o: (
            tile_distance_from_player(o),
            int(getattr(o, "track_id", 0)),
        ),
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
        game_state,
        exclude=exclude,
        origin=origin,
        check_path=check_path,
        screen_only=screen_only,
    )
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
    ownership_filter: bool = True,
) -> Optional[WorldObject]:
    """Closest lootable pile; adena (아데나) wins over non-adena at any range.

    Among adena (or among non-adena when none), prefer nearer track_id tiebreak.
    Combat sticky / attacks_me still outrank loot in ``farm_loot_or_combat``.
    """
    cands = list_lootable(
        game_state,
        loot_mode=loot_mode,
        farm=farm,
        origin=origin,
        check_path=check_path,
        exclude=exclude,
        screen_only=screen_only,
        ownership_filter=ownership_filter,
    )
    if not cands:
        return None
    return min(
        cands,
        key=lambda o: (
            0 if _is_adena(o) else 1,
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
    "dungeon_engage_path_measure",
    "dungeon_new_engage_path_ok",
    "path_cap_skip_reason",
    "path_cap_skips",
    "count_attackable",
    "count_monsters_within_tiles",
    "list_attackable",
    "list_lootable",
    "loot_path_clickable",
    "nearest_attackable",
    "list_attacked_me_targets",
    "nearest_attacks_me_force",
    "player_attacking_me",
    "sync_attacks_me_force_targets",
    "monster_hitting_me",
    "nearest_lootable",
    "contested_mob_guids",
    "is_contested_monster",
    "prefer_loot_over_combat",
    "describe_attackable_filter_skips",
    "tile_distance_from_player",
    "relative_tile_xy",
    "in_near_monster_box",
    "in_loot_approach_threat",
    "in_attack_click_range",
    "sticky_holds_loot",
    "loot_within_engage_tiles",
    "loot_in_view",
    "object_on_screen",
    "object_absolute_tile",
    "is_adena",
    "small_adena_ignored",
]

from app._04_decision.decide_spans import traced

can_engage_target = traced(can_engage_target)
dungeon_new_engage_path_ok = traced(dungeon_new_engage_path_ok)
attack_path_clickable = traced(attack_path_clickable)
list_attackable = traced(list_attackable)
nearest_attackable = traced(nearest_attackable)
list_lootable = traced(list_lootable)
nearest_lootable = traced(nearest_lootable)
loot_path_clickable = traced(loot_path_clickable)
