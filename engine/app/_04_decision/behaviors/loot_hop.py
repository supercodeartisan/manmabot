"""Loot as walk-onto-item from the live memory entity list."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._03_world.objects import Position
from app._03_world.world_coords import tile_chebyshev
from app._04_decision.behaviors.combat import clear_engage_state
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_movement_unstick,
    walkable_around,
)
from app._04_decision.combat_query import object_absolute_tile
from app._04_decision.nav_config import get_terrain_map
from app._04_decision.pathfinding import plan_travel_click
from app._04_decision import player_mode as pm

_SCRATCH_LOOT_CLICK_AT = "loot_approach_click_at"

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._03_world.objects import WorldObject
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behavior_tree import Status


def clear_loot_hop(blackboard: "Blackboard") -> None:
    """Clear approach / stuck state for sticky loot."""
    blackboard.loot_approach_destination = None
    blackboard.loot_approach_waypoint = None
    blackboard.loot_approach_active = False
    blackboard.loot_stuck_tile = None
    blackboard.loot_stuck_since_tick = 0
    blackboard.loot_stuck_since_time = 0.0
    blackboard.loot_pickup_since_time = 0.0  # unused; kept for blackboard compat
    blackboard.scratch.pop(_SCRATCH_LOOT_CLICK_AT, None)
    reset_unstick_tries(blackboard)


def abandon_loot_item(blackboard: "Blackboard", item_id: int) -> None:
    """Soft-skip an item briefly; prefer path/ring retries over permanent drop.

    Uses the short loot-clicked cooldown only — does **not** enter the combat
    give-up map (that looked like ``give-up sticky_was=None`` and blocked
    re-pickup for 160 ticks).
    """
    from app.bot_log import get_logger

    get_logger("loot").info(
        "abandon item id=%s (path/cursor exhausted) — short loot cooldown only",
        item_id,
    )
    blackboard.loot_clicked_ids[int(item_id)] = int(blackboard.tick_count)
    blackboard.cursor_verify_fail_streak.pop(int(item_id), None)
    if blackboard.current_item_id == item_id:
        blackboard.current_item_id = None
    if blackboard.loot_await_gone_id == int(item_id):
        clear_loot_await(blackboard)
    clear_loot_hop(blackboard)


def mark_loot_clicked(blackboard: "Blackboard", item_id: int) -> None:
    """Remember a successful pickup click so the empty tile is not re-clicked."""
    blackboard.loot_clicked_ids[int(item_id)] = int(blackboard.tick_count)
    blackboard.loot_pickup_until = 0.0
    blackboard.loot_await_gone_id = int(item_id)
    blackboard.loot_await_gone_since = time.time()
    if blackboard.current_item_id == item_id:
        blackboard.current_item_id = None
    clear_loot_hop(blackboard)


def clear_loot_await(blackboard: "Blackboard") -> None:
    blackboard.loot_await_gone_id = None
    blackboard.loot_await_gone_since = 0.0


def loot_awaiting_memory_gone(
    state: "GameState | None",
    blackboard: "Blackboard",
) -> bool:
    """True while the last clicked pile is still in the memory entity list.

    Walking (search / travel / next-pile hop) waits until print_state omits
    it. A short timeout unblocks ghosts and other-player drops.
    """
    from app._04_decision.combat_query import memory_target_gone

    tid = blackboard.loot_await_gone_id
    if tid is None:
        return False
    started = float(blackboard.loot_await_gone_since or 0.0)
    if started and (time.time() - started) >= float(pm.LOOT_AWAIT_GONE_S):
        clear_loot_await(blackboard)
        return False
    obj = state.get_object(int(tid)) if state is not None else None
    if obj is None or memory_target_gone(state, obj):
        clear_loot_await(blackboard)
        return False
    return True


def emit_await_pickup_gone(blackboard: "Blackboard") -> "Status":
    from app._04_decision.behavior_tree import Status

    blackboard.current_goal = "loot"
    blackboard.emit(
        ActionType.IDLE,
        priority=0.4,
        reason="pickup memory gone",
    )
    return Status.SUCCESS


def try_finish_pending_pickup(
    state: "GameState | None",
    blackboard: "Blackboard",
) -> "Status | None":
    """While the last clicked pile is still listed: re-click or walk back.

    Stops search/other-loot from canceling an in-flight pickup. Sticky combat
    outside this helper may still preempt. Returns None when not awaiting.
    """
    from app._03_world import ObjectType
    from app._04_decision.behavior_tree import Status
    from app.bot_log import event

    if not loot_awaiting_memory_gone(state, blackboard):
        return None
    tid = blackboard.loot_await_gone_id
    if tid is None or state is None:
        return emit_await_pickup_gone(blackboard)
    obj = state.get_object(int(tid))
    if obj is None or getattr(obj, "object_type", None) is not ObjectType.ITEM:
        return emit_await_pickup_gone(blackboard)

    origin = blackboard.world_origin
    item_tile = object_absolute_tile(obj, origin)
    if _in_pickup_range(origin, obj, item_tile):
        event("loot", "pickup retry id=%s (await still listed)", tid)
        _emit_pickup(
            blackboard,
            int(tid),
            mid_act=False,
            reason="pickup retry",
        )
        return Status.SUCCESS

    # Walked off before the server dropped the pile — approach again.
    event("loot", "pickup re-approach id=%s (await still listed)", tid)
    blackboard.current_item_id = int(tid)
    blackboard.current_target_id = None
    clear_engage_state(blackboard)
    status = tick_loot_item(state, blackboard, obj, fresh=True)
    if status is Status.SUCCESS:
        return Status.SUCCESS
    return emit_await_pickup_gone(blackboard)


def loot_pickup_settling(blackboard: "Blackboard") -> bool:
    """True only when a leftover settle timer is still running (now unused)."""
    return time.time() < float(blackboard.loot_pickup_until or 0.0)


def recently_clicked_loot(
    blackboard: "Blackboard",
    item_id: int,
    *,
    ticks: int | None = None,
) -> bool:
    window = int(ticks if ticks is not None else pm.LOOT_CLICKED_COOLDOWN_TICKS)
    started = blackboard.loot_clicked_ids.get(int(item_id))
    if started is None:
        return False
    return int(blackboard.tick_count) - int(started) < window


def _near_tile(origin: tuple[int, int], tile: tuple[int, int]) -> bool:
    return tile_chebyshev(origin[0], origin[1], tile[0], tile[1]) <= int(
        pm.LOOT_HOP_ARRIVE_TILES
    )


def _should_reclick_approach(blackboard: "Blackboard") -> bool:
    last = float(blackboard.scratch.get(_SCRATCH_LOOT_CLICK_AT) or 0.0)
    if last <= 0.0:
        return True
    return (time.time() - last) >= float(pm.TRAVEL_RECLICK_SECONDS)


def _reset_stuck(blackboard: "Blackboard") -> None:
    blackboard.loot_stuck_tile = (
        blackboard.world_origin.x,
        blackboard.world_origin.y,
    )
    blackboard.loot_stuck_since_tick = blackboard.tick_count
    blackboard.loot_stuck_since_time = time.time()


def _approach_stuck(blackboard: "Blackboard") -> bool:
    """True when memory tile has not moved for the loot approach stuck window."""
    cur = (blackboard.world_origin.x, blackboard.world_origin.y)
    if blackboard.loot_stuck_tile is not None and blackboard.loot_stuck_tile != cur:
        reset_unstick_tries(blackboard)
    if blackboard.loot_stuck_tile != cur:
        _reset_stuck(blackboard)
        return False
    if blackboard.loot_stuck_since_time <= 0:
        _reset_stuck(blackboard)
        return False
    elapsed = time.time() - blackboard.loot_stuck_since_time
    return elapsed >= pm.LOOT_APPROACH_STUCK_SECONDS


def loot_stand_tile(
    origin: tuple[int, int],
    item_tile: tuple[int, int],
    terrain,
) -> tuple[int, int] | None:
    """Walkable tile on or beside the pile. None if already in pickup range."""
    ox, oy = int(origin[0]), int(origin[1])
    ix, iy = int(item_tile[0]), int(item_tile[1])
    if tile_chebyshev(ox, oy, ix, iy) <= pm.LOOT_PICKUP_TILES:
        return None
    if terrain is None or terrain.is_walkable(ix, iy):
        return (ix, iy)
    candidates: list[tuple[int, int, int]] = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            x, y = ix + dx, iy + dy
            if not terrain.is_walkable(x, y):
                continue
            candidates.append((tile_chebyshev(ox, oy, x, y), x, y))
    if not candidates:
        return None
    candidates.sort()
    return (candidates[0][1], candidates[0][2])


def _memory_player_tile(origin, item: "WorldObject") -> tuple[int, int] | None:
    rx = getattr(item, "world_rx", None)
    ry = getattr(item, "world_ry", None)
    cx = getattr(item, "world_cx", None)
    cy = getattr(item, "world_cy", None)
    if rx is None or ry is None or cx is None or cy is None:
        return None
    from app._03_world.memory_sync import game_to_nav

    return game_to_nav(int(cx) - int(rx), int(cy) - int(ry))


def _player_nav_tiles(origin, item: "WorldObject") -> list[tuple[int, int]]:
    """Origin plus memory-derived player tile when both are known."""
    tiles = [(int(origin.x), int(origin.y))]
    mem = _memory_player_tile(origin, item)
    if mem is not None and mem not in tiles:
        tiles.append(mem)
    return tiles


def _player_nav_tile(origin, item: "WorldObject") -> tuple[int, int]:
    """Player tile closer to the pile. Origin wins ties so a stale delta cannot walk away."""
    item_tile = object_absolute_tile(item, origin)
    return min(
        _player_nav_tiles(origin, item),
        key=lambda tile: tile_chebyshev(
            tile[0], tile[1], int(item_tile[0]), int(item_tile[1])
        ),
    )


def _memory_pickup_distance(item: "WorldObject") -> int | None:
    from app._03_world.world_coords import distance_tiles_from_memory

    return distance_tiles_from_memory(item)


def _in_pickup_range(origin, item: "WorldObject", item_tile: tuple[int, int]) -> bool:
    """True when memory or either player-tile estimate is within pickup range."""
    limit = int(pm.LOOT_PICKUP_TILES)
    mem = _memory_pickup_distance(item)
    if mem is not None and mem <= limit:
        return True
    ix, iy = int(item_tile[0]), int(item_tile[1])
    return any(
        tile_chebyshev(tile[0], tile[1], ix, iy) <= limit
        for tile in _player_nav_tiles(origin, item)
    )


def _standing_to_pickup(origin, item_tile: tuple[int, int]) -> bool:
    """True only when the player tile is on or next to the pile."""
    return tile_chebyshev(
        int(origin.x),
        int(origin.y),
        int(item_tile[0]),
        int(item_tile[1]),
    ) <= pm.LOOT_PICKUP_TILES


def _nudge_content_off_item(content: Position, item: "WorldObject") -> Position:
    """Keep the approach click off the pile so travel does not freeze on it."""
    pos = getattr(item, "position", None)
    if pos is None:
        return content
    ix = float(getattr(pos, "x", 0.0) or 0.0)
    iy = float(getattr(pos, "y", 0.0) or 0.0)
    dx = float(content.x) - ix
    dy = float(content.y) - iy
    dist = math.hypot(dx, dy)
    min_uv = 0.032
    if dist >= min_uv:
        return content
    if dist < 1e-6:
        dx = 0.5 - ix
        dy = 0.5 - iy
        dist = max(math.hypot(dx, dy), 1e-6)
    scale = min_uv / dist
    return Position(x=ix + dx * scale, y=iy + dy * scale)


def _emit_approach(
    blackboard: "Blackboard",
    *,
    destination,
    waypoint: tuple[int, int],
    item_id: int,
    reason: str,
    mid_act: bool,
) -> None:
    from app.bot_log import event
    from app._04_decision.behavior_tree import Status

    del Status  # imported only for type docs elsewhere
    blackboard.loot_approach_destination = destination
    blackboard.loot_approach_waypoint = waypoint
    blackboard.loot_approach_active = True
    if not mid_act:
        blackboard.scratch[_SCRATCH_LOOT_CLICK_AT] = time.time()
        event(
            "loot",
            "approach hop item=%s wp=%s reason=%s",
            item_id,
            waypoint,
            reason,
        )
    blackboard.current_goal = "loot"
    blackboard.emit(
        ActionType.SEARCHING,
        destination=destination,
        target_id=item_id,
        priority=0.3,
        reason=reason,
        mid_act=mid_act,
    )


def _emit_pickup(
    blackboard: "Blackboard",
    item_id: int,
    *,
    mid_act: bool,
    reason: str,
) -> None:
    from app.bot_log import event

    blackboard.loot_approach_active = False
    blackboard.loot_approach_destination = None
    blackboard.loot_approach_waypoint = None
    blackboard.current_goal = "loot"
    if not mid_act:
        event("loot", "pickup emit item=%s reason=%s", item_id, reason)
    blackboard.emit(
        ActionType.PICKUP,
        target_id=item_id,
        priority=0.3,
        reason=reason,
        mid_act=mid_act,
    )


def tick_loot_item(
    state: "GameState",
    blackboard: "Blackboard",
    item: "WorldObject",
    *,
    fresh: bool,
) -> "Status":
    """One tick of sticky loot: walk onto the pile, then click while it lives."""
    from app._04_decision.behavior_tree import Status

    item_id = item.track_id
    origin = blackboard.world_origin
    item_tile = object_absolute_tile(item, origin)
    player_tile = _player_nav_tile(origin, item)
    adjacent = _in_pickup_range(origin, item, item_tile)

    # Click while the live entity is still listed. Ghosts / already-taken
    # piles are dropped by continue_or_start_loot via memory_target_gone.
    if adjacent:
        _emit_pickup(
            blackboard,
            item_id,
            mid_act=not fresh,
            reason="engage item" if fresh else "loot target",
        )
        return Status.SUCCESS

    # Hold the current hop until memory reaches it. Re-planning every tick
    # issued a new ground click and canceled the walk onto the pile.
    if blackboard.loot_approach_active and blackboard.loot_approach_waypoint is not None:
        wp = blackboard.loot_approach_waypoint
        dest = blackboard.loot_approach_destination
        hop_here = any(
            _near_tile(tile, wp) for tile in _player_nav_tiles(origin, item)
        )
        if hop_here:
            blackboard.loot_approach_active = False
            blackboard.loot_approach_destination = None
            blackboard.loot_approach_waypoint = None
            if _in_pickup_range(origin, item, item_tile):
                _emit_pickup(
                    blackboard,
                    item_id,
                    mid_act=not fresh,
                    reason="loot target nearby",
                )
                return Status.SUCCESS
        elif dest is not None and not _should_reclick_approach(blackboard):
            if try_movement_unstick(
                blackboard,
                stuck=_approach_stuck(blackboard),
                action=ActionType.SEARCHING,
                reason="unstick nearby",
                priority=0.3,
                target_id=item_id,
                state=state,
                on_walk=lambda tile, hop: _emit_approach(
                    blackboard,
                    destination=hop,
                    waypoint=tile,
                    item_id=item_id,
                    reason="unstick nearby",
                    mid_act=False,
                ),
            ):
                if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
                    clear_loot_hop(blackboard)
                return Status.SUCCESS
            _emit_approach(
                blackboard,
                destination=dest,
                waypoint=wp,
                item_id=item_id,
                reason="walk onto item",
                mid_act=True,
            )
            return Status.SUCCESS
        else:
            blackboard.loot_approach_active = False
            blackboard.loot_approach_destination = None
            blackboard.loot_approach_waypoint = None

    # --- Walk to a tile next to the item. Never click the pile itself. ---
    if try_movement_unstick(
        blackboard,
        stuck=_approach_stuck(blackboard),
        action=ActionType.SEARCHING,
        reason="unstick nearby",
        priority=0.3,
        target_id=item_id,
        state=state,
        on_walk=lambda tile, dest: _emit_approach(
            blackboard,
            destination=dest,
            waypoint=tile,
            item_id=item_id,
            reason="unstick nearby",
            mid_act=False,
        ),
    ):
        if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
            clear_loot_hop(blackboard)
        return Status.SUCCESS

    terrain = get_terrain_map()
    stand = loot_stand_tile(player_tile, item_tile, terrain)
    if stand is None:
        _emit_pickup(
            blackboard,
            item_id,
            mid_act=not fresh,
            reason="loot target nearby",
        )
        return Status.SUCCESS

    from app._03_world.world_coords import WorldOrigin

    hop_origin = WorldOrigin(x=player_tile[0], y=player_tile[1])
    if terrain is None:
        from app._04_decision.pathfinding import waypoint_to_content

        dest = waypoint_to_content(stand, hop_origin)
        if tile_chebyshev(stand[0], stand[1], item_tile[0], item_tile[1]) > 2:
            dest = _nudge_content_off_item(dest, item)
        _emit_approach(
            blackboard,
            destination=dest,
            waypoint=stand,
            item_id=item_id,
            reason="walk onto item",
            mid_act=False,
        )
        return Status.SUCCESS

    content, _path, waypoint = plan_travel_click(terrain, hop_origin, stand)
    if content is None or waypoint is None:
        from app.bot_log import get_logger

        # Wall / blocked A*: keep the item — try a 2-tile ring, then unstick.
        radius = int(pm.COMBAT_BLOCKED_UNSTICK_RADIUS)
        tried = {
            tuple(item)
            for item in (blackboard.scratch.get("loot_wall_ring_tried") or [])
        }
        if int(blackboard.scratch.get("loot_wall_ring_id") or -1) != int(item_id):
            blackboard.scratch["loot_wall_ring_id"] = int(item_id)
            tried = set()
        for tile in walkable_around(terrain, player_tile, radius):
            if tile in tried:
                continue
            tried.add(tile)
            blackboard.scratch["loot_wall_ring_tried"] = [
                list(item) for item in tried
            ]
            from app._04_decision.pathfinding import waypoint_to_content

            dest = waypoint_to_content(tile, hop_origin)
            get_logger("loot").info(
                "loot A* blocked id=%s — ring click %s (r=%s)",
                item_id,
                tile,
                radius,
            )
            _emit_approach(
                blackboard,
                destination=dest,
                waypoint=tile,
                item_id=item_id,
                reason="loot wall ring",
                mid_act=False,
            )
            return Status.SUCCESS
        if try_movement_unstick(
            blackboard,
            stuck=True,
            action=ActionType.SEARCHING,
            reason="loot path blocked unstick",
            priority=0.3,
            target_id=item_id,
            state=state,
            on_walk=lambda tile, dest: _emit_approach(
                blackboard,
                destination=dest,
                waypoint=tile,
                item_id=item_id,
                reason="loot path blocked unstick",
                mid_act=False,
            ),
        ):
            get_logger("loot").info(
                "loot A* blocked id=%s — movement unstick",
                item_id,
            )
            if blackboard.scratch.pop(SCRATCH_ESCAPED, None):
                clear_loot_hop(blackboard)
            return Status.SUCCESS
        get_logger("loot").warning(
            "loot A* blocked id=%s — ring+unstick exhausted, soft skip",
            item_id,
        )
        abandon_loot_item(blackboard, item_id)
        return Status.FAILURE

    dest = content
    if tile_chebyshev(waypoint[0], waypoint[1], item_tile[0], item_tile[1]) > 2:
        dest = _nudge_content_off_item(content, item)
    _emit_approach(
        blackboard,
        destination=dest,
        waypoint=waypoint,
        item_id=item_id,
        reason="walk onto item",
        mid_act=False,
    )
    return Status.SUCCESS


def begin_loot_item(blackboard: "Blackboard", item_id: int) -> None:
    """Bind sticky loot to ``item_id`` and reset approach/stuck clocks."""
    from app.bot_log import event

    blackboard.current_item_id = item_id
    blackboard.current_target_id = None
    from app._04_decision.behaviors.combat import clear_engage_state

    clear_engage_state(blackboard)
    clear_loot_hop(blackboard)
    _reset_stuck(blackboard)
    event("loot", "begin_loot_item id=%s", item_id)


__all__ = [
    "clear_loot_hop",
    "abandon_loot_item",
    "mark_loot_clicked",
    "clear_loot_await",
    "loot_awaiting_memory_gone",
    "emit_await_pickup_gone",
    "try_finish_pending_pickup",
    "loot_pickup_settling",
    "recently_clicked_loot",
    "loot_stand_tile",
    "tick_loot_item",
    "begin_loot_item",
    "_standing_to_pickup",
    "_nudge_content_off_item",
]
