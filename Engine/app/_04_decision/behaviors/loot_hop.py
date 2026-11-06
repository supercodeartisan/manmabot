"""Loot as walk-onto-item from the live memory entity list."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

from app._03_world import ActionType
from app._02_state.objects import Position
from app._03_world.space.world_coords import tile_chebyshev
from app._04_decision.behaviors.combat import clear_engage_state
from app._04_decision.behaviors.unstick import (
    SCRATCH_ESCAPED,
    reset_unstick_tries,
    try_movement_unstick,
    walkable_around,
)
from app._04_decision.combat_query import object_absolute_tile, small_adena_ignored
from app._04_decision.nav_config import get_terrain_map
from app._04_decision import player_mode as pm

_SCRATCH_LOOT_CLICK_AT = "loot_approach_click_at"
_SCRATCH_LOOT_STILL_TILE = "loot_pose_still_tile"
_SCRATCH_LOOT_STILL_SINCE = "loot_pose_still_since"

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._02_state.objects import WorldObject
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
    blackboard.scratch.pop(_SCRATCH_LOOT_STILL_TILE, None)
    blackboard.scratch.pop(_SCRATCH_LOOT_STILL_SINCE, None)
    reset_unstick_tries(blackboard)


def abandon_loot_item(blackboard: "Blackboard", item_id: int) -> None:
    """Soft-skip an item briefly; prefer path/ring retries over permanent drop.

    Uses the short loot-clicked cooldown only — does **not** enter the combat
    give-up map (that looked like ``give-up sticky_was=None`` and blocked
    re-pickup for the combat give-up window).
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


def mark_loot_clicked(
    blackboard: "Blackboard",
    item_id: int,
    state: "GameState | None" = None,
) -> None:
    """Remember an F4 so the pile is held until it leaves or the bag rises."""
    blackboard.loot_clicked_ids[int(item_id)] = int(blackboard.tick_count)
    blackboard.loot_pickup_until = 0.0
    first = blackboard.loot_await_gone_id != int(item_id)
    blackboard.loot_await_gone_id = int(item_id)
    if first or not blackboard.loot_await_gone_since:
        blackboard.loot_await_gone_since = time.time()
    if blackboard.current_item_id == item_id:
        blackboard.current_item_id = None
    clear_loot_hop(blackboard)
    obj = state.get_object(int(item_id)) if state is not None else None
    qty = _bag_qty(state, obj)
    base = blackboard.scratch.get("_loot_bag_base")
    if qty is not None and (
        not isinstance(base, tuple) or len(base) != 2 or int(base[0]) != int(item_id)
    ):
        blackboard.scratch["_loot_bag_base"] = (int(item_id), int(qty))
    blackboard.scratch["_loot_f4_at"] = time.time()
    blackboard.scratch["_loot_f4_tries"] = int(
        blackboard.scratch.get("_loot_f4_tries") or 0
    ) + 1
    blackboard.scratch["_loot_f4_total"] = int(
        blackboard.scratch.get("_loot_f4_total") or 0
    ) + 1


def clear_loot_await(blackboard: "Blackboard") -> None:
    blackboard.loot_await_gone_id = None
    blackboard.loot_await_gone_since = 0.0
    blackboard.scratch.pop("_loot_f4_tries", None)
    blackboard.scratch.pop("_loot_f4_total", None)
    blackboard.scratch.pop("_loot_f4_at", None)
    blackboard.scratch.pop("_loot_bag_base", None)
    blackboard.scratch.pop("_loot_wait_log", None)
    blackboard.scratch.pop("_loot_force_reapproach", None)
    blackboard.scratch.pop("_loot_f4_match", None)


def loot_awaiting_memory_gone(
    state: "GameState | None",
    blackboard: "Blackboard",
) -> bool:
    """True while the last F4 pile is still on the ground and not in the bag.

    Patrol may start when the entity leaves the world or the matching bag
    count rises. A listed pile is not released on the old 0.8s timer.
    ``LOOT_PICKUP_GIVEUP_S`` releases a ghost that never leaves.
    """
    from app._04_decision.combat_query import memory_target_gone
    from app.bot_log import event

    tid = blackboard.loot_await_gone_id
    if tid is None:
        return False
    obj = state.get_object(int(tid)) if state is not None else None
    gone = obj is None or memory_target_gone(state, obj)
    if gone or _bag_rose(state, blackboard, obj):
        clear_loot_await(blackboard)
        return False
    started = float(blackboard.loot_await_gone_since or 0.0)
    total = int(blackboard.scratch.get("_loot_f4_total") or 0)
    # A fight that preempts one press must not drop the pile. Give up only
    # after several real F4s still left it in the world.
    if (
        total >= int(pm.LOOT_F4_RECHECK_TRIES)
        and started
        and (time.time() - started) >= float(pm.LOOT_PICKUP_GIVEUP_S)
    ):
        event("loot", "pickup give up id=%s (still listed)", tid)
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
    """While the last F4 pile is still listed: wait, press again, or walk back.

    Does not hand the tick to patrol while the pile is still in the world.
    Sticky combat outside this helper may still preempt. Returns None when
    the pile is confirmed gone, the bag rose, or the give-up cap elapsed.
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
    in_range = _in_pickup_range(origin, obj, item_tile)
    # Named small adena is not walked back to. A pile already in range still F4s.
    if small_adena_ignored(obj) and not in_range:
        clear_loot_await(blackboard)
        return None
    if in_range:
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


def _arm_pose_still(blackboard: "Blackboard", origin) -> None:
    """Start the unread-pose stillness clock at this live tile."""
    blackboard.scratch[_SCRATCH_LOOT_STILL_TILE] = (int(origin.x), int(origin.y))
    blackboard.scratch[_SCRATCH_LOOT_STILL_SINCE] = time.time()


def _pose_unknown_as_stand(blackboard: "Blackboard", origin) -> bool:
    """True when the live tile has not changed for the unread-pose window.

    A tile change only resets the clock. The next still window can fire.
    """
    tile = (int(origin.x), int(origin.y))
    prev = blackboard.scratch.get(_SCRATCH_LOOT_STILL_TILE)
    now = time.time()
    if prev != tile:
        blackboard.scratch[_SCRATCH_LOOT_STILL_TILE] = tile
        blackboard.scratch[_SCRATCH_LOOT_STILL_SINCE] = now
        return False
    since = float(blackboard.scratch.get(_SCRATCH_LOOT_STILL_SINCE) or 0.0)
    if since <= 0.0:
        blackboard.scratch[_SCRATCH_LOOT_STILL_SINCE] = now
        return False
    return (now - since) >= float(pm.LOOT_POSE_UNKNOWN_STILL_S)


def _loot_motion(blackboard: "Blackboard", origin) -> tuple[bool | None, bool | None]:
    """(raw body_is_moving, value the loot hop should follow).

    An unread slot stays unread while the live tile is changing. Once that
    tile sits still, the hop follows the standing path and can reclick.
    A real walk or a real stand is returned unchanged.
    """
    from app._05_action.body_pose import body_is_moving

    raw = body_is_moving()
    if raw is True:
        # A live walk restarts the unread window so one missed sample
        # does not reclick over a step that is already underway.
        _arm_pose_still(blackboard, origin)
        return raw, raw
    if raw is None and _pose_unknown_as_stand(blackboard, origin):
        return raw, False
    return raw, raw


def _loot_click_still_open(
    state: "GameState",
    origin,
    click: tuple[int, int],
    *,
    terrain,
    moving: bool | None,
) -> bool:
    """True while this click should be repeated instead of replanned.

    A walking body keeps the click. An unread slot keeps it only while the
    caller still passes None (the live tile is changing). A standing body,
    including an unread slot whose tile has stayed put, replans when the
    click line is no longer clear.
    """
    if moving is True or moving is None or terrain is None:
        return True
    from app._04_decision.avoidance import click_clear, collect_body_tiles

    bodies = collect_body_tiles(state, origin)
    return click_clear(
        terrain,
        bodies,
        (int(origin.x), int(origin.y)),
        (int(click[0]), int(click[1])),
    )


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
    from app._03_world.merge.memory_sync import game_to_nav

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
    from app._03_world.space.world_coords import distance_tiles_from_memory

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
    ox, oy = _origin_xy(origin)
    return tile_chebyshev(ox, oy, int(item_tile[0]), int(item_tile[1])) <= int(
        pm.LOOT_PICKUP_TILES
    )


def _origin_xy(origin) -> tuple[int, int]:
    if isinstance(origin, tuple):
        return int(origin[0]), int(origin[1])
    return int(origin.x), int(origin.y)


def _feet_on_pickup(origin, item_tile: tuple[int, int], item: object | None = None) -> bool:
    """True when the live origin or the memory player tile is the pile tile.

    A walkable pile one tile away is not a match, including while the body
    is still walking. Beside the pile counts only for the live origin, and
    only when that tile cannot be walked.
    """
    ix, iy = int(item_tile[0]), int(item_tile[1])
    tiles = [_origin_xy(origin)]
    if item is not None:
        mem = _memory_player_tile(origin, item)
        if mem is not None and mem not in tiles:
            tiles.append(mem)
    for ox, oy in tiles:
        if ox == ix and oy == iy:
            return True
    ox, oy = tiles[0]
    terrain = get_terrain_map()
    if terrain is not None and not terrain.is_walkable(ix, iy):
        return tile_chebyshev(ox, oy, ix, iy) <= int(pm.LOOT_PICKUP_TILES)
    return False


def _body_settled_for_f4(blackboard: "Blackboard", origin) -> bool:
    """True when the body is standing. Walk and attack are not standing.

    An unread slot uses the same still-tile window as a loot hop.
    """
    from app._05_action.body_pose import BODY, read_action

    body, cmd = read_action()
    if body is None and cmd is None:
        return _pose_unknown_as_stand(blackboard, origin)
    return BODY.get(body) == "stand"


def _named_adena(item: object) -> bool:
    species = str(getattr(item, "species_name", None) or "").strip().lower()
    label = str(getattr(item, "label", None) or "").strip().lower()
    blob = f"{species} {label}"
    return "adena" in blob or "아데나" in blob or "金幣" in blob or "金币" in blob


def _bag_qty(state: "GameState | None", item: object | None) -> int | None:
    """Matching bag count, or None when the bag snapshot is not usable."""
    if state is None or item is None:
        return None
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return None
    if _named_adena(item):
        try:
            return int(getattr(inv, "adena", 0) or 0)
        except (TypeError, ValueError):
            return None
    name = str(
        getattr(item, "species_name", None) or getattr(item, "label", None) or ""
    ).strip().lower()
    if not name or name in {"item", "grounditem", "-"}:
        return None
    total = 0
    for row in getattr(inv, "items", None) or []:
        row_name = str(getattr(row, "name", "") or "").strip().lower()
        if row_name != name:
            continue
        try:
            total += max(0, int(getattr(row, "quantity", 0) or 0))
        except (TypeError, ValueError):
            continue
    return total


def _bag_rose(
    state: "GameState | None",
    blackboard: "Blackboard",
    item: object | None,
) -> bool:
    base = blackboard.scratch.get("_loot_bag_base")
    if item is None or not isinstance(base, tuple) or len(base) != 2:
        return False
    try:
        base_id = int(base[0])
        base_qty = int(base[1])
        item_id = int(getattr(item, "track_id", -1))
    except (TypeError, ValueError):
        return False
    if base_id != item_id:
        return False
    now = _bag_qty(state, item)
    return now is not None and int(now) > base_qty


def f4_allowed(blackboard, state, item_id) -> bool:
    """True within one tile of the pile. The press does not wait for stand.

    Same range as the 2026-10-19 pickup: memory distance or either player
    tile at Chebyshev ``LOOT_PICKUP_TILES``. The key is not delayed by a
    settle gap. Attack, travel, and search still own their tick elsewhere.
    """
    if blackboard is None or state is None or item_id is None:
        return False
    try:
        obj = state.get_object(int(item_id))
    except (TypeError, ValueError, AttributeError):
        return False
    if obj is None:
        return False
    origin = getattr(blackboard, "world_origin", None)
    if origin is None:
        return False
    tile = object_absolute_tile(obj, origin)
    return _in_pickup_range(origin, obj, tile)


def _emit_wait(blackboard: "Blackboard", item_id: int, reason: str) -> None:
    """Hold loot without a key or a ground click."""
    from app.bot_log import event

    key = (int(item_id), str(reason))
    if blackboard.scratch.get("_loot_wait_log") != key:
        blackboard.scratch["_loot_wait_log"] = key
        event("loot", "pickup hold id=%s reason=%s", int(item_id), reason)
    blackboard.current_goal = "loot"
    blackboard.current_item_id = int(item_id)
    blackboard.emit(
        ActionType.IDLE,
        priority=0.4,
        reason=reason,
    )


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
        _arm_pose_still(blackboard, blackboard.world_origin)
        from app._04_decision.clickgap import note_plan

        note_plan(f"loot-walk item={item_id} wp={waypoint} reason={reason}")
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
    blackboard.scratch["_loot_f4_match"] = int(item_id)
    blackboard.current_goal = "loot"
    if not mid_act:
        from app._04_decision.clickgap import note_plan

        note_plan(f"loot-pickup item={item_id} reason={reason}")
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

    # F4 inside one tile, including while the body is still walking.
    # A ground click is not emitted on this tick.
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
        elif dest is not None:
            raw, moving = _loot_motion(blackboard, origin)
            if _loot_click_still_open(
                state,
                origin,
                wp,
                terrain=get_terrain_map(),
                moving=moving,
            ):
                from app._04_decision.avoidance import classify_ground_reclick, log_ground_pause

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
                now = time.time()
                clicked_at = float(blackboard.scratch.get(_SCRATCH_LOOT_CLICK_AT) or 0.0)
                follow = classify_ground_reclick(
                    moving,
                    clicked_at,
                    now=now,
                )
                if follow == "repeat":
                    log_ground_pause(
                        "loot",
                        wp,
                        raw,
                        clicked_at,
                        now,
                        "walk onto item",
                    )
                _emit_approach(
                    blackboard,
                    destination=dest,
                    waypoint=wp,
                    item_id=item_id,
                    reason="walk onto item",
                    mid_act=follow != "repeat",
                )
                return Status.SUCCESS
            from app._04_decision.behaviors.unstick import note_confined_line_closed

            note_confined_line_closed(blackboard)
            blackboard.loot_approach_active = False
            blackboard.loot_approach_destination = None
            blackboard.loot_approach_waypoint = None
        else:
            blackboard.loot_approach_active = False
            blackboard.loot_approach_destination = None
            blackboard.loot_approach_waypoint = None

    # --- Walk onto the pile. Pickup stays a separate click once in range. ---
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
    from app._03_world.space.world_coords import WorldOrigin

    hop_origin = WorldOrigin(x=player_tile[0], y=player_tile[1])
    if terrain is None:
        from app._04_decision.pathfinding import waypoint_to_content

        dest = waypoint_to_content(item_tile, hop_origin)
        _emit_approach(
            blackboard,
            destination=dest,
            waypoint=item_tile,
            item_id=item_id,
            reason="walk onto item",
            mid_act=False,
        )
        return Status.SUCCESS

    from app._04_decision.avoidance import collect_body_tiles, plan_body_click

    bodies = collect_body_tiles(state, hop_origin)
    planned = plan_body_click(
        terrain,
        hop_origin,
        item_tile,
        bodies,
    )
    from app._04_decision.behaviors.unstick import note_confined_planned_avoid

    note_confined_planned_avoid(blackboard, planned, bodies)
    if planned.guide and planned.click is None:
        from app._04_decision.clickgap import note_hold

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
        note_hold(
            f"loot:{item_id}:no-click",
            f"loot item={item_id} note={planned.note} wp={planned.waypoint}",
        )
        blackboard.current_goal = "loot"
        blackboard.emit(
            ActionType.IDLE,
            priority=0.3,
            reason=planned.note,
        )
        return Status.SUCCESS
    if not planned.guide or planned.click is None:
        content, waypoint = None, None
    else:
        from app._04_decision.pathfinding import waypoint_to_content

        waypoint = planned.click
        content = waypoint_to_content(waypoint, hop_origin)
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


def begin_loot_item(
    blackboard: "Blackboard",
    item_id: int,
    item: object | None = None,
) -> None:
    """Bind sticky loot to ``item_id`` and reset approach/stuck clocks."""
    from app.bot_log import event

    blackboard.current_item_id = item_id
    blackboard.current_target_id = None
    from app._04_decision.behaviors.combat import clear_engage_state

    clear_engage_state(blackboard)
    clear_loot_hop(blackboard)
    _reset_stuck(blackboard)
    try:
        from app._03_world.merge.item_sight import format_item_sight_for_begin

        sight = format_item_sight_for_begin(int(item_id))
    except Exception:
        sight = "first_seen=- drop_mob=-"
    event("loot", "begin_loot_item id=%s %s", item_id, sight)
    from app._04_decision.ground_loot import format_loot_claim

    event(
        "loot",
        "loot decide via=main gate=apply id=%s %s",
        item_id,
        format_loot_claim(item),
    )


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
    "f4_allowed",
    "_standing_to_pickup",
    "_feet_on_pickup",
    "_nudge_content_off_item",
]
