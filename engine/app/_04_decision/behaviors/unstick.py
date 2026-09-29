"""Blocked-path recovery: 360° nearby clicks, then teleport or talking scroll.

When a decided walk (travel, search, or loot) does not change the
memory tile for about 5 seconds, the planned path is treated as blocked.
Recovery clicks every walkable tile around the player (Chebyshev radius 3)
in compass order. If every walkable tile inside radius 2 has been tried
and the character still has not moved, use teleport; if teleport cannot
fire, use a talking scroll back to the hunt-map landing.

Combat uses a separate clock: if the monster tile does not change for
2 s while we keep attacking, walk about 2 tiles sideways from the
attack line and swing again. Still no movement → give up that target.
Combat never teleports.

Three standstills inside 20 s, or HP at/below the operator escape gate,
skip the sweep and go straight to teleport → talking scroll.
"""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Callable, Optional

from app._03_world import ActionType
from app._04_decision.behavior_tree import Status
from app._04_decision.nav_config import get_terrain_map
from app._04_decision.pathfinding import waypoint_to_content
from app._04_decision import player_mode as pm

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._03_world.terrain_map import TerrainMap
    from app._04_decision.blackboard import Blackboard

SCRATCH_TRIED = "unstick_tried"
SCRATCH_ORIGIN = "unstick_origin"
SCRATCH_CLICK_AT = "unstick_click_at"
SCRATCH_COMBAT_TILE = "unstick_combat_tile"
SCRATCH_COMBAT_AT = "unstick_combat_at"
SCRATCH_BLOCK_TID = "combat_block_tid"
SCRATCH_BLOCK_TILE = "combat_block_tile"
SCRATCH_BLOCK_AT = "combat_block_at"
SCRATCH_BLOCK_SIDESTEP = "combat_block_sidestep"
SCRATCH_ESCAPED = "unstick_escaped"
SCRATCH_EVENTS = "unstick_event_times"
SCRATCH_EVENT_NOTED = "unstick_event_noted"
SCRATCH_DETOUR_TRIED = "enter_farm_detour_tried"
SCRATCH_DETOUR_ORIGIN = "enter_farm_detour_origin"
SCRATCH_DETOUR_CLICK_AT = "enter_farm_detour_click_at"
SCRATCH_CONFINED_ORIGIN = "unstick_confined_origin"
SCRATCH_CONFINED_SINCE = "unstick_confined_since"

# Pause between sweep clicks so a successful step can clear the stuck clock.
UNSTICK_SWEEP_GAP_S = 0.5


def reset_enter_farm_detour(blackboard: "Blackboard") -> None:
    """Drop the enter-farm 5-tile ring so a new origin starts fresh."""
    blackboard.scratch.pop(SCRATCH_DETOUR_TRIED, None)
    blackboard.scratch.pop(SCRATCH_DETOUR_ORIGIN, None)
    blackboard.scratch.pop(SCRATCH_DETOUR_CLICK_AT, None)


def reset_unstick_tries(blackboard: "Blackboard") -> None:
    """Drop the current 360° sweep so a new standstill starts fresh."""
    blackboard.scratch.pop(SCRATCH_TRIED, None)
    blackboard.scratch.pop(SCRATCH_ORIGIN, None)
    blackboard.scratch.pop(SCRATCH_CLICK_AT, None)
    blackboard.scratch.pop(SCRATCH_ESCAPED, None)
    blackboard.scratch.pop(SCRATCH_EVENT_NOTED, None)
    reset_enter_farm_detour(blackboard)


def reset_confined_progress(blackboard: "Blackboard") -> None:
    """Drop the 13 s / 5-tile confined-movement clock."""
    blackboard.scratch.pop(SCRATCH_CONFINED_ORIGIN, None)
    blackboard.scratch.pop(SCRATCH_CONFINED_SINCE, None)


def _player_tile(blackboard: "Blackboard") -> tuple[int, int]:
    return (int(blackboard.world_origin.x), int(blackboard.world_origin.y))


def _tried_set(blackboard: "Blackboard") -> set[tuple[int, int]]:
    raw = blackboard.scratch.get(SCRATCH_TRIED) or []
    return {tuple(item) for item in raw}  # type: ignore[arg-type]


def _store_tried(blackboard: "Blackboard", tried: set[tuple[int, int]]) -> None:
    blackboard.scratch[SCRATCH_TRIED] = [list(item) for item in tried]


def _sync_origin(blackboard: "Blackboard", origin: tuple[int, int]) -> None:
    prev = blackboard.scratch.get(SCRATCH_ORIGIN)
    if prev is None:
        blackboard.scratch[SCRATCH_ORIGIN] = list(origin)
        return
    if tuple(prev) != origin:
        reset_unstick_tries(blackboard)
        blackboard.scratch[SCRATCH_ORIGIN] = list(origin)


def walkable_around(
    terrain: Optional["TerrainMap"],
    origin: tuple[int, int],
    radius: int,
) -> list[tuple[int, int]]:
    """Walkable tiles in Chebyshev ``radius``, 360° then near→far.

    Missing terrain treats every in-radius cell as walkable so recovery
    still runs when the nav PNG is not loaded.
    """
    ox, oy = origin
    tiles: list[tuple[int, int, float, int]] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx == 0 and dy == 0:
                continue
            dist = max(abs(dx), abs(dy))
            if dist > radius:
                continue
            x, y = ox + dx, oy + dy
            if terrain is not None and not terrain.is_walkable(x, y):
                continue
            tiles.append((x, y, math.atan2(dy, dx), dist))
    tiles.sort(key=lambda item: (item[2], item[3]))
    return [(x, y) for x, y, _angle, _dist in tiles]


def inner_ring_exhausted(
    blackboard: "Blackboard",
    terrain: Optional["TerrainMap"],
    origin: tuple[int, int],
) -> bool:
    """True when every walkable tile inside the escalate radius has been tried."""
    inner = walkable_around(terrain, origin, int(pm.TRAVEL_UNSTICK_INNER_RADIUS))
    if not inner:
        # Town / unset origin on the farm PNG has no neighbors. That is not
        # "we tried every tile" — wait for a real walkable standstill.
        if terrain is None or not terrain.is_walkable(origin[0], origin[1]):
            return False
        return True
    tried = _tried_set(blackboard)
    return all(tile in tried for tile in inner)


def next_sweep_tile(
    blackboard: "Blackboard",
    terrain: Optional["TerrainMap"],
    origin: tuple[int, int],
    *,
    radius: int | None = None,
) -> Optional[tuple[int, int]]:
    """Next unused walkable tile in the compass sweep."""
    _sync_origin(blackboard, origin)
    tried = _tried_set(blackboard)
    ring = int(pm.TRAVEL_UNSTICK_RADIUS if radius is None else radius)
    for tile in walkable_around(terrain, origin, ring):
        if tile in tried:
            continue
        tried.add(tile)
        _store_tried(blackboard, tried)
        blackboard.scratch[SCRATCH_ORIGIN] = list(origin)
        return tile
    return None


def _trim_stuck_events(blackboard: "Blackboard", now: float) -> list[float]:
    window = float(pm.UNSTICK_BURST_WINDOW_S)
    hist = [
        float(stamp)
        for stamp in (blackboard.scratch.get(SCRATCH_EVENTS) or [])
        if now - float(stamp) <= window
    ]
    blackboard.scratch[SCRATCH_EVENTS] = hist
    return hist


def _note_stuck_event(blackboard: "Blackboard") -> None:
    """Count this standstill once; later ticks on the same tile do not add."""
    if blackboard.scratch.get(SCRATCH_EVENT_NOTED):
        return
    now = time.time()
    hist = _trim_stuck_events(blackboard, now)
    hist.append(now)
    blackboard.scratch[SCRATCH_EVENTS] = hist
    blackboard.scratch[SCRATCH_EVENT_NOTED] = True


def burst_stuck(blackboard: "Blackboard") -> bool:
    """True after ``UNSTICK_BURST_COUNT`` standstills inside the window."""
    hist = _trim_stuck_events(blackboard, time.time())
    return len(hist) >= int(pm.UNSTICK_BURST_COUNT)


def _hp_escape_threshold() -> float:
    from app._04_decision.hp_actions import action_threshold, normalize_hp_actions

    actions = pm.HP_ACTIONS or normalize_hp_actions(None)
    for key in ("teleport", "safe_zone"):
        value = action_threshold(actions, key)
        if value is not None:
            return float(value)
    return float(pm.HP_CRITICAL_RATIO)


def _hp_ratio_hint(
    blackboard: "Blackboard",
    state: Optional["GameState"],
) -> Optional[float]:
    if state is not None:
        from app._04_decision.mode_control import hp_ratio

        ratio = hp_ratio(state)
        if ratio is not None:
            return float(ratio)
    hist = list(blackboard.scratch.get("hp_ratio_hist") or [])
    if not hist:
        return None
    return float(hist[-1][1])


def needs_hp_escape(
    blackboard: "Blackboard",
    state: Optional["GameState"] = None,
) -> bool:
    """True when known HP is at or below the operator teleport / safe gate."""
    ratio = _hp_ratio_hint(blackboard, state)
    if ratio is None:
        return False
    return ratio <= _hp_escape_threshold()


def _inside_active_farm(blackboard: "Blackboard") -> bool:
    """Unstick teleport is only for a stuck hunt, not the walk into the farm."""
    from app._04_decision.nav_config import get_active_farm

    farm = get_active_farm(int(getattr(blackboard, "farm_area_index", 0) or 0))
    if farm is None:
        return True
    return bool(farm.contains(
        int(blackboard.world_origin.x),
        int(blackboard.world_origin.y),
    ))


def try_enter_farm_detour(
    blackboard: "Blackboard",
    *,
    on_walk: Callable[[tuple[int, int], object], None],
) -> bool:
    """When enter-farm A* is empty, walk a 5-tile ring, then escape.

    Movement unstick (radius 2–3) is unchanged. Teleport / talking scroll
    run only after every walkable cell in ``ENTER_FARM_DETOUR_RADIUS`` has
    been clicked from this tile, or when that ring has no walkable cell.
    """
    origin = _player_tile(blackboard)
    terrain = get_terrain_map()
    prev = blackboard.scratch.get(SCRATCH_DETOUR_ORIGIN)
    if prev is None or tuple(prev) != origin:
        reset_enter_farm_detour(blackboard)
        blackboard.scratch[SCRATCH_DETOUR_ORIGIN] = list(origin)

    now = time.time()
    last = float(blackboard.scratch.get(SCRATCH_DETOUR_CLICK_AT) or 0.0)
    if last > 0.0 and (now - last) < UNSTICK_SWEEP_GAP_S:
        return True

    tried = {tuple(item) for item in (blackboard.scratch.get(SCRATCH_DETOUR_TRIED) or [])}
    radius = int(pm.ENTER_FARM_DETOUR_RADIUS)
    for tile in walkable_around(terrain, origin, radius):
        if tile in tried:
            continue
        tried.add(tile)
        blackboard.scratch[SCRATCH_DETOUR_TRIED] = [list(item) for item in tried]
        blackboard.scratch[SCRATCH_DETOUR_CLICK_AT] = now
        dest = waypoint_to_content(tile, blackboard.world_origin)
        on_walk(tile, dest)
        return True

    return try_unstick_escape(
        blackboard, urgent=True, allow_outside_farm=True,
    )


def try_unstick_escape(
    blackboard: "Blackboard",
    *,
    urgent: bool = False,
    allow_outside_farm: bool = False,
    reason: str = "",
    state: Optional["GameState"] = None,
) -> bool:
    """Teleport off a blocked path; talking scroll if teleport cannot fire."""
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.spells import try_unstick_teleport
    from app._04_decision.talking_scroll import (
        emit_talking_scroll,
        farm_return_scroll_spot,
        talking_scroll_available,
    )

    if not allow_outside_farm and not _inside_active_farm(blackboard):
        return False
    if shopping_blocks_teleport(blackboard):
        return False
    if try_unstick_teleport(
        blackboard,
        ignore_cooldown=urgent,
        reason=str(reason or "unstick teleport"),
        state=state,
    ):
        reset_unstick_tries(blackboard)
        reset_confined_progress(blackboard)
        blackboard.scratch[SCRATCH_ESCAPED] = True
        return True
    if not talking_scroll_available():
        return False
    spot = farm_return_scroll_spot()
    if emit_talking_scroll(
        blackboard,
        spot_id=spot,
        reason=str(reason or "unstick talking scroll"),
    ) is Status.SUCCESS:
        reset_unstick_tries(blackboard)
        reset_confined_progress(blackboard)
        blackboard.scratch[SCRATCH_ESCAPED] = True
        return True
    return False


def note_confined_progress(blackboard: "Blackboard") -> bool:
    """Update the 5-tile bubble clock. True when it has lasted 13 s."""
    from app._03_world.world_coords import tile_chebyshev

    cur = _player_tile(blackboard)
    now = time.time()
    raw = blackboard.scratch.get(SCRATCH_CONFINED_ORIGIN)
    if raw is None:
        blackboard.scratch[SCRATCH_CONFINED_ORIGIN] = list(cur)
        blackboard.scratch[SCRATCH_CONFINED_SINCE] = now
        return False
    origin = (int(raw[0]), int(raw[1]))
    if tile_chebyshev(cur[0], cur[1], origin[0], origin[1]) > int(
        pm.UNSTICK_CONFINED_TILES
    ):
        blackboard.scratch[SCRATCH_CONFINED_ORIGIN] = list(cur)
        blackboard.scratch[SCRATCH_CONFINED_SINCE] = now
        return False
    started = float(blackboard.scratch.get(SCRATCH_CONFINED_SINCE) or 0.0)
    if started <= 0.0:
        blackboard.scratch[SCRATCH_CONFINED_SINCE] = now
        return False
    return (now - started) >= float(pm.UNSTICK_CONFINED_SECONDS)


def try_confined_escape(
    blackboard: "Blackboard",
    state: Optional["GameState"] = None,
) -> bool:
    """Leave a 5-tile / 13 s pocket: teleport if on the hotbar, else scroll."""
    if not note_confined_progress(blackboard):
        return False
    return try_unstick_escape(
        blackboard,
        urgent=True,
        allow_outside_farm=True,
        reason="unstick confined",
        state=state,
    )


def try_movement_unstick(
    blackboard: "Blackboard",
    *,
    stuck: bool,
    action: ActionType = ActionType.SEARCHING,
    reason: str = "unstick nearby",
    priority: float = 0.55,
    target_id: Optional[int] = None,
    on_walk: Optional[Callable[[tuple[int, int], object], None]] = None,
    state: Optional["GameState"] = None,
    allow_escape: bool = True,
    origin: Optional[tuple[int, int]] = None,
    radius: Optional[int] = None,
) -> bool:
    """If ``stuck``, click the next nearby walkable or escape.

    Returns True when this tick is consumed (walk click, hold between
    clicks, teleport, or talking scroll). ``allow_escape=False`` keeps
    the 360° walk only — no teleport / talking scroll.
    ``origin`` / ``radius`` override the player-centered radius-3 sweep
    (combat path clicks use the monster tile and radius 2).
    """
    if not stuck:
        return False
    origin = origin if origin is not None else _player_tile(blackboard)
    terrain = get_terrain_map()
    _sync_origin(blackboard, origin)
    if allow_escape:
        _note_stuck_event(blackboard)

    now = time.time()
    last = float(blackboard.scratch.get(SCRATCH_CLICK_AT) or 0.0)
    in_gap = last > 0.0 and (now - last) < UNSTICK_SWEEP_GAP_S
    urgent = allow_escape and (
        burst_stuck(blackboard) or needs_hp_escape(blackboard, state)
    )

    if urgent and try_unstick_escape(blackboard, urgent=True, state=state):
        return True

    if allow_escape and inner_ring_exhausted(blackboard, terrain, origin):
        if in_gap:
            return True
        if try_unstick_escape(blackboard, state=state):
            return True

    if in_gap:
        return True

    tile = next_sweep_tile(blackboard, terrain, origin, radius=radius)
    if tile is None:
        if not allow_escape:
            return False
        return try_unstick_escape(blackboard, state=state)

    dest = waypoint_to_content(tile, blackboard.world_origin)
    blackboard.scratch[SCRATCH_CLICK_AT] = now
    if on_walk is not None:
        on_walk(tile, dest)
        return True
    blackboard.emit(
        action,
        destination=dest,
        target_id=target_id,
        priority=priority,
        reason=reason,
        mid_act=False,
    )
    return True


def _combat_stuck_elapsed(blackboard: "Blackboard") -> float:
    cur = _player_tile(blackboard)
    prev = blackboard.scratch.get(SCRATCH_COMBAT_TILE)
    if prev is None or tuple(prev) != cur:
        blackboard.scratch[SCRATCH_COMBAT_TILE] = list(cur)
        blackboard.scratch[SCRATCH_COMBAT_AT] = time.time()
        reset_unstick_tries(blackboard)
        return 0.0
    started = float(blackboard.scratch.get(SCRATCH_COMBAT_AT) or 0.0)
    if started <= 0.0:
        blackboard.scratch[SCRATCH_COMBAT_AT] = time.time()
        return 0.0
    return time.time() - started


def _clear_combat_clock(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(SCRATCH_COMBAT_TILE, None)
    blackboard.scratch.pop(SCRATCH_COMBAT_AT, None)


def _clear_blocked_clock(blackboard: "Blackboard") -> None:
    blackboard.scratch.pop(SCRATCH_BLOCK_TID, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_TILE, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_AT, None)
    blackboard.scratch.pop(SCRATCH_BLOCK_SIDESTEP, None)


def _blocked_stuck_elapsed(
    blackboard: "Blackboard",
    tid: int,
    cell: tuple[int, int],
) -> float:
    prev_tid = blackboard.scratch.get(SCRATCH_BLOCK_TID)
    prev_tile = blackboard.scratch.get(SCRATCH_BLOCK_TILE)
    if prev_tid != tid or prev_tile is None or tuple(prev_tile) != cell:
        blackboard.scratch[SCRATCH_BLOCK_TID] = tid
        blackboard.scratch[SCRATCH_BLOCK_TILE] = list(cell)
        blackboard.scratch[SCRATCH_BLOCK_AT] = time.time()
        blackboard.scratch.pop(SCRATCH_BLOCK_SIDESTEP, None)
        reset_unstick_tries(blackboard)
        return 0.0
    started = float(blackboard.scratch.get(SCRATCH_BLOCK_AT) or 0.0)
    if started <= 0.0:
        blackboard.scratch[SCRATCH_BLOCK_AT] = time.time()
        return 0.0
    return time.time() - started


def try_combat_approach_unstick(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """Disabled: the 2.5 s / 2-tile sweep is movement-only, never combat."""
    _clear_combat_clock(blackboard)
    return False


def combat_sidestep_tiles(
    player: tuple[int, int],
    monster: tuple[int, int],
    *,
    dist: int = 2,
) -> list[tuple[int, int]]:
    """Tiles ~``dist`` off the player→monster attack line (both sides)."""
    px, py = int(player[0]), int(player[1])
    dx = int(monster[0]) - px
    dy = int(monster[1]) - py
    step = max(1, int(dist))
    if dx == 0 and dy == 0:
        offsets = [(step, 0), (-step, 0), (0, step), (0, -step)]
    else:
        def _scale(vx: int, vy: int) -> tuple[int, int]:
            span = max(abs(vx), abs(vy), 1)
            return (int(round(vx * step / span)), int(round(vy * step / span)))

        left = _scale(-dy, dx)
        right = _scale(dy, -dx)
        offsets = [left, right]
        if left == (0, 0) and right == (0, 0):
            offsets = [(step, 0), (-step, 0), (0, step), (0, -step)]
    out: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for ox, oy in offsets:
        if ox == 0 and oy == 0:
            continue
        tile = (px + ox, py + oy)
        if tile == (int(monster[0]), int(monster[1])) or tile in seen:
            continue
        seen.add(tile)
        out.append(tile)
    return out


def _tile_walkable(terrain: Optional["TerrainMap"], tile: tuple[int, int]) -> bool:
    if terrain is None:
        return True
    return bool(terrain.is_walkable(int(tile[0]), int(tile[1])))


def _give_up_blocked_target(blackboard: "Blackboard", tid: int) -> None:
    from app._04_decision.behaviors.combat import give_up_target

    give_up_target(blackboard, int(tid))
    _clear_blocked_clock(blackboard)


def try_combat_blocked_unstick(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """If attacks do not move the monster tile for 2 s, sidestep ~2 tiles.

    No teleport. One sidestep, then keep attacking. A second 2 s with no
    tile change (or no walkable side) gives up so another monster is taken.
    """
    tid = getattr(blackboard, "current_target_id", None)
    if tid is None:
        _clear_blocked_clock(blackboard)
        return False
    obj = state.get_object(int(tid))
    if obj is None:
        _clear_blocked_clock(blackboard)
        return False
    from app._04_decision.combat_query import object_absolute_tile

    click = object_absolute_tile(obj, blackboard.world_origin)
    elapsed = _blocked_stuck_elapsed(blackboard, int(tid), click)
    if elapsed < float(pm.COMBAT_BLOCKED_UNSTICK_SECONDS):
        return False

    if blackboard.scratch.get(SCRATCH_BLOCK_SIDESTEP):
        _give_up_blocked_target(blackboard, int(tid))
        return False

    player = _player_tile(blackboard)
    terrain = get_terrain_map()
    radius = int(pm.COMBAT_BLOCKED_UNSTICK_RADIUS)
    for tile in combat_sidestep_tiles(player, click, dist=radius):
        if not _tile_walkable(terrain, tile):
            continue
        dest = waypoint_to_content(tile, blackboard.world_origin)
        blackboard.scratch[SCRATCH_BLOCK_SIDESTEP] = True
        blackboard.scratch[SCRATCH_BLOCK_AT] = time.time()
        blackboard.current_goal = "combat"
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            target_id=int(tid),
            priority=0.55,
            reason="sidestep combat block",
            mid_act=False,
        )
        return True
    _give_up_blocked_target(blackboard, int(tid))
    return False


SCRATCH_WALL_DETOUR_TRIED = "combat_wall_detour_tried"
SCRATCH_WALL_DETOUR_TID = "combat_wall_detour_tid"


def try_combat_wall_detour(
    state: "GameState",
    blackboard: "Blackboard",
) -> bool:
    """When LOS is blocked, walk an A* hop or 2-tile ring toward the sticky.

    Does not give up. Caller may fall through to blocked-unstick / attack.
    """
    from app.bot_log import get_logger
    from app._04_decision.combat_query import (
        attack_line_clear,
        can_engage_target,
        object_absolute_tile,
    )
    from app._04_decision.pathfinding import plan_travel_click

    tid = getattr(blackboard, "current_target_id", None)
    if tid is None:
        return False
    obj = state.get_object(int(tid))
    if obj is None:
        return False
    origin = blackboard.world_origin
    if can_engage_target(obj, origin):
        return False
    if attack_line_clear(obj, origin):
        return False

    log = get_logger("combat")
    if int(blackboard.scratch.get(SCRATCH_WALL_DETOUR_TID) or -1) != int(tid):
        blackboard.scratch[SCRATCH_WALL_DETOUR_TID] = int(tid)
        blackboard.scratch[SCRATCH_WALL_DETOUR_TRIED] = []

    player = _player_tile(blackboard)
    terrain = get_terrain_map()
    goal = object_absolute_tile(obj, origin)
    stand: tuple[int, int] | None = (int(goal[0]), int(goal[1]))
    if terrain is not None and not terrain.is_walkable(stand[0], stand[1]):
        stand = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = int(goal[0]) + dx, int(goal[1]) + dy
                if terrain.is_walkable(nx, ny):
                    stand = (nx, ny)
                    break
            if stand is not None:
                break
    if stand is not None and terrain is not None:
        content, _path, waypoint = plan_travel_click(terrain, origin, stand)
        if content is not None and waypoint is not None:
            log.info(
                "wall/fence LOS blocked id=%s — A* detour hop to %s",
                tid,
                waypoint,
            )
            blackboard.current_goal = "combat"
            blackboard.emit(
                ActionType.SEARCHING,
                destination=content,
                target_id=int(tid),
                priority=0.55,
                reason="wall detour A*",
                mid_act=False,
            )
            return True

    tried = {
        tuple(item)
        for item in (blackboard.scratch.get(SCRATCH_WALL_DETOUR_TRIED) or [])
    }
    radius = int(pm.COMBAT_BLOCKED_UNSTICK_RADIUS)
    for tile in walkable_around(terrain, player, radius):
        if tile in tried or tile == (int(goal[0]), int(goal[1])):
            continue
        tried.add(tile)
        blackboard.scratch[SCRATCH_WALL_DETOUR_TRIED] = [
            list(item) for item in tried
        ]
        dest = waypoint_to_content(tile, origin)
        log.info(
            "wall/fence LOS blocked id=%s — ring click %s (r=%s)",
            tid,
            tile,
            radius,
        )
        blackboard.current_goal = "combat"
        blackboard.emit(
            ActionType.SEARCHING,
            destination=dest,
            target_id=int(tid),
            priority=0.55,
            reason="wall detour ring",
            mid_act=False,
        )
        return True

    log.info(
        "wall/fence LOS blocked id=%s — no A*/ring hop this tick",
        tid,
    )
    return False


__all__ = [
    "SCRATCH_ESCAPED",
    "UNSTICK_SWEEP_GAP_S",
    "reset_unstick_tries",
    "walkable_around",
    "inner_ring_exhausted",
    "next_sweep_tile",
    "try_enter_farm_detour",
    "try_unstick_escape",
    "try_confined_escape",
    "note_confined_progress",
    "reset_confined_progress",
    "try_movement_unstick",
    "try_combat_approach_unstick",
    "try_combat_blocked_unstick",
    "try_combat_wall_detour",
    "combat_sidestep_tiles",
    "SCRATCH_BLOCK_SIDESTEP",
    "burst_stuck",
    "needs_hp_escape",
]
