"""Build ActionIntent values for the member brain (reuses action executor)."""
from __future__ import annotations

import random
from typing import Any, Iterable, Optional

from .config import PartyMemberConfig
from .follow import (
    ARRIVAL_TOLERANCE,
    FOLLOW_CLICK_TILES,
    choose_approach_tile,
    choose_settle_stand,
    follow_extend_hop,
    follow_hop_still_closes,
)
from .policy import MemberKind


def _body_moving() -> bool:
    try:
        from app._05_action.body_pose import body_is_moving

        return body_is_moving() is True
    except Exception:
        return False


def _follow_hop_clickable(origin: Any, hop: tuple[int, int]) -> bool:
    from app._03_world.space.world_coords import absolute_to_relative, in_battle_click_region
    from app._04_decision.nav_config import get_terrain_map

    terrain = get_terrain_map()
    if terrain is None or not terrain.is_walkable(int(hop[0]), int(hop[1])):
        return False
    rx, ry = absolute_to_relative(int(hop[0]), int(hop[1]), origin)
    return bool(in_battle_click_region(rx, ry))


def _emit_follow_hop(
    origin: Any,
    hop: tuple[int, int],
    goal: tuple[int, int],
    kind: str,
) -> tuple[Any, tuple[int, int], str, tuple[int, int]]:
    from app._04_decision.pathfinding import waypoint_to_content

    from .types import ActionIntent, ActionType

    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=waypoint_to_content(hop, origin),
        priority=0.55,
        reason=f"party_member:{kind} {goal[0]},{goal[1]}",
    )
    detail = f"{kind} hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail, hop


def idle(reason: str, *, priority: float = 0.0) -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.IDLE,
        priority=priority,
        reason=f"party_member:{reason}",
    )


def potion(reason: str = "self_potion") -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.USE_HP_POTION,
        priority=0.9,
        reason=f"party_member:{reason}",
    )


def list_heal(
    name: str,
    click_x: int,
    click_y: int,
    *,
    hp_pct: int,
    dist: Optional[int] = None,
    hotbar_box: Optional[int] = None,
    hotbar_key: Optional[str] = None,
) -> Any:
    """Heal by clicking that member's party-list row, not their body."""
    from .types import ActionIntent, ActionType

    dist_bit = f" dist={int(dist)}" if dist is not None else ""
    return ActionIntent(
        action=ActionType.HEAL,
        priority=0.88,
        reason=f"party_member:list heal {name} hp={int(hp_pct)}{dist_bit}",
        hotbar_box=hotbar_box,
        hotbar_key=hotbar_key,
        click_x=int(click_x),
        click_y=int(click_y),
    )


def attack(track_id: int, reason: str, *, mid_act: bool = False) -> Any:
    from .types import ActionIntent, ActionType

    return ActionIntent(
        action=ActionType.ATTACK,
        target_id=int(track_id),
        priority=0.85,
        reason=f"party_member:{reason}",
        mid_act=bool(mid_act),
    )


def _occupied_tiles(game_state: Any, origin: Any) -> list[tuple[int, int]]:
    from app._02_state.objects import ObjectType
    from app._04_decision.combat_query import object_absolute_tile

    occupied: list[tuple[int, int]] = []
    for kind in (ObjectType.PLAYER, ObjectType.MONSTER, ObjectType.NPC):
        for obj in game_state.objects(kind):
            try:
                occupied.append(object_absolute_tile(obj, origin))
            except Exception:
                continue
    return occupied


def _plan_approach_hop(
    game_state: Any,
    origin: Any,
    target_tile: tuple[int, int],
    *,
    radius: int,
    previous_goal: Optional[tuple[int, int]],
    rng: random.Random,
    reason_prefix: str,
    max_hop: Optional[int] = None,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """Shared TRAVELING hop toward a stand tile near ``target_tile``."""
    from app._04_decision.nav_config import get_terrain_map

    terrain = get_terrain_map()
    if terrain is None:
        return idle("no_terrain"), None, "no_terrain"
    ox, oy = int(origin.x), int(origin.y)
    occupied = _occupied_tiles(game_state, origin)
    prev = previous_goal
    if prev == (ox, oy):
        prev = None
    goal = choose_approach_tile(
        terrain.is_walkable,
        target_tile,
        radius,
        occupied,
        rng,
        prev,
        prefer_near=(ox, oy),
    )
    if goal is None:
        return idle("no_approach_tile"), None, "no_approach_tile"
    return _plan_hop_to_goal(
        terrain,
        origin,
        goal,
        previous_goal=previous_goal,
        reason_prefix=reason_prefix,
        max_hop=max_hop,
        retry=lambda bad: choose_approach_tile(
            terrain.is_walkable,
            target_tile,
            radius,
            occupied,
            rng,
            None,
            exclude=(bad,),
            prefer_near=(ox, oy),
        ),
    )


def _plan_hop_to_goal(
    terrain: Any,
    origin: Any,
    goal: tuple[int, int],
    *,
    previous_goal: Optional[tuple[int, int]],
    reason_prefix: str,
    retry: Optional[Any] = None,
    max_hop: Optional[int] = None,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """TRAVELING click toward ``goal``; ``retry(bad_goal)`` picks another on no path."""
    from app._04_decision.pathfinding import plan_travel_click

    from .types import ActionIntent, ActionType

    ox, oy = int(origin.x), int(origin.y)
    if goal == (ox, oy):
        return idle("at_approach"), goal, "at_approach"
    if previous_goal == goal:
        try:
            from app._05_action.body_pose import body_is_moving

            if body_is_moving():
                return idle("follow_in_transit"), goal, "follow_in_transit"
        except Exception:
            pass
    dest, _path, waypoint = plan_travel_click(
        terrain, origin, goal, max_hop=max_hop
    )
    if dest is None:
        if retry is None:
            return idle("no_path"), None, "no_path"
        goal = retry(goal)
        if goal is None:
            return idle("no_path"), None, "no_path"
        if goal == (ox, oy):
            return idle("at_approach"), goal, "at_approach"
        dest, _path, waypoint = plan_travel_click(
            terrain, origin, goal, max_hop=max_hop
        )
        if dest is None:
            return idle("no_path"), None, "no_path"
    hop = waypoint if waypoint is not None else goal
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=dest,
        priority=0.55,
        reason=f"party_member:{reason_prefix} {goal[0]},{goal[1]}",
    )
    detail = f"hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail


def plan_follow_intent(
    game_state: Any,
    origin: Any,
    leader_tile: tuple[int, int],
    config: PartyMemberConfig,
    *,
    previous_goal: Optional[tuple[int, int]],
    rng: random.Random,
    settle_stand: Optional[tuple[int, int]] = None,
    stand_reason: str = "follow_settle",
) -> tuple[Any, Optional[tuple[int, int]], str]:
    """TRAVELING hop toward the leader; exact ``settle_stand`` tile when set."""
    if settle_stand is not None:
        from app._04_decision.nav_config import get_terrain_map

        terrain = get_terrain_map()
        if terrain is None:
            return idle("no_terrain"), None, "no_terrain"
        return _plan_hop_to_goal(
            terrain,
            origin,
            (int(settle_stand[0]), int(settle_stand[1])),
            previous_goal=previous_goal,
            reason_prefix=stand_reason,
            max_hop=FOLLOW_CLICK_TILES,
        )
    return _plan_approach_hop(
        game_state,
        origin,
        leader_tile,
        radius=int(config.approach_tiles),
        previous_goal=previous_goal,
        rng=rng,
        reason_prefix="follow",
        max_hop=FOLLOW_CLICK_TILES,
    )


def _travel_max_hop() -> int:
    from app._04_decision import player_mode as pm
    from app._04_decision.dungeon import dungeon_max_hop_tiles, is_dungeon_map

    if is_dungeon_map():
        return int(dungeon_max_hop_tiles())
    return int(pm.TRAVEL_MAX_HOP_TILES)


def plan_field_follow(
    field: Any,
    origin: Any,
    *,
    stop_steps: int,
    previous_goal: Optional[tuple[int, int]],
    previous_hop: Optional[tuple[int, int]],
) -> Optional[tuple[Any, Optional[tuple[int, int]], str, Optional[tuple[int, int]]]]:
    """TRAVELING click down the leader walk field (no A*).

    Returns ``(intent, goal, detail, hop)`` or ``None`` when the member is
    outside the field and the caller should fall back to A*.
    """
    from app._04_decision.pathfinding import select_click_waypoint, waypoint_to_content

    from .types import ActionIntent, ActionType

    ox, oy = int(origin.x), int(origin.y)
    path = field.descent((ox, oy), stop_steps=stop_steps)
    if not path:
        return None
    goal = path[-1]
    if goal == (ox, oy):
        return idle("at_approach"), goal, "at_approach", None
    # Keep the click while it still aims at the goal and is not about to end.
    # A straight open line chains one tile farther before that click finishes.
    if (
        previous_hop is not None
        and _body_moving()
        and max(abs(previous_hop[0] - ox), abs(previous_hop[1] - oy)) > 1
        and follow_hop_still_closes((ox, oy), goal, previous_hop)
    ):
        extended = follow_extend_hop((ox, oy), previous_hop, goal, kind="field")
        if extended is not None and _follow_hop_clickable(origin, extended):
            return _emit_follow_hop(origin, extended, goal, "field")
        return (
            idle("follow_in_transit"),
            goal,
            "follow_in_transit",
            previous_hop,
        )
    hop = select_click_waypoint(
        path,
        origin,
        terrain=field.terrain,
        max_hop=min(_travel_max_hop(), FOLLOW_CLICK_TILES),
    )
    if hop is None:
        return None
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=waypoint_to_content(hop, origin),
        priority=0.55,
        reason=f"party_member:follow_walk {goal[0]},{goal[1]}",
    )
    detail = f"walk {len(path) - 1} hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail, hop


def plan_slot_hop(
    origin: Any,
    slot: tuple[int, int],
    *,
    previous_goal: Optional[tuple[int, int]],
    previous_hop: Optional[tuple[int, int]],
    kind: str,
) -> tuple[Any, Optional[tuple[int, int]], str, Optional[tuple[int, int]]]:
    """Short hop toward an absolute formation tile. Does not aim at the leader."""
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.pathfinding import plan_travel_click

    from .types import ActionIntent, ActionType

    from .follow import STAND_ARRIVE_TILES

    ox, oy = int(origin.x), int(origin.y)
    goal = (int(slot[0]), int(slot[1]))
    arrive = STAND_ARRIVE_TILES if kind == "stand" else ARRIVAL_TOLERANCE
    if max(abs(goal[0] - ox), abs(goal[1] - oy)) <= arrive:
        return idle("at_slot"), goal, "at_slot", None
    # Keep the click while it still aims at the slot and is not about to end.
    # A turn, or a hop that would pass the slot, clicks this read's tile.
    # A straight open line chains one tile farther before the click finishes.
    if (
        previous_hop is not None
        and _body_moving()
        and max(abs(previous_hop[0] - ox), abs(previous_hop[1] - oy)) > 1
        and follow_hop_still_closes((ox, oy), goal, previous_hop)
    ):
        extended = follow_extend_hop((ox, oy), previous_hop, goal, kind=kind)
        if extended is not None and _follow_hop_clickable(origin, extended):
            return _emit_follow_hop(origin, extended, goal, kind)
        return idle("follow_in_transit"), goal, "follow_in_transit", previous_hop
    terrain = get_terrain_map()
    if terrain is None:
        return idle("no_terrain"), goal, "no_terrain", None
    dest, _path, waypoint = plan_travel_click(
        terrain, origin, goal, max_hop=FOLLOW_CLICK_TILES
    )
    if dest is None:
        return idle("no_path"), None, "no_path", None
    hop = waypoint if waypoint is not None else goal
    intent = ActionIntent(
        action=ActionType.TRAVELING,
        destination=dest,
        priority=0.55,
        reason=f"party_member:{kind} {goal[0]},{goal[1]}",
    )
    detail = f"{kind} hop {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"
    return intent, goal, detail, hop


def pick_settle_stand(
    game_state: Any,
    origin: Any,
    leader_tile: tuple[int, int],
    config: PartyMemberConfig,
    *,
    previous: Optional[tuple[int, int]],
    rng: random.Random,
    exclude: Iterable[tuple[int, int]] = (),
    field: Any = None,
) -> Optional[tuple[int, int]]:
    """Locked random up/down/left/right tile ``stop_tiles`` from a stopped leader.

    With ``field``, a stand also needs at most ``stop_tiles`` walk steps to
    the leader (a cardinal tile behind a wall is skipped).
    """
    from app._04_decision.nav_config import get_terrain_map

    from .follow import cardinal_tiles

    terrain = get_terrain_map()
    if terrain is None or game_state is None or origin is None:
        return None
    ox, oy = int(origin.x), int(origin.y)
    radius = max(1, int(config.stop_tiles))
    # Standing on the stand must not count as "occupied" by myself.
    occupied = [t for t in _occupied_tiles(game_state, origin) if t != (ox, oy)]
    skip = {(int(x), int(y)) for x, y in exclude}
    if field is not None:
        for tile in cardinal_tiles(leader_tile[0], leader_tile[1], radius):
            steps = field.steps(tile)
            if steps is None or steps > radius:
                skip.add(tile)
    return choose_settle_stand(
        terrain.is_walkable,
        leader_tile,
        radius,
        occupied,
        rng,
        previous,
        exclude=skip,
    )


def intent_for_kind(
    kind: MemberKind,
    *,
    reason: str,
    game_state: Any = None,
    origin: Any = None,
    leader_tile: Optional[tuple[int, int]] = None,
    config: Optional[PartyMemberConfig] = None,
    previous_goal: Optional[tuple[int, int]] = None,
    rng: Optional[random.Random] = None,
    defend_id: Optional[int] = None,
    assist_id: Optional[int] = None,
    settle_stand: Optional[tuple[int, int]] = None,
    stand_reason: str = "follow_settle",
    mid_act: bool = False,
) -> tuple[Any, Optional[tuple[int, int]], str]:
    if kind is MemberKind.STOP:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.WAIT:
        return idle(reason), previous_goal, reason
    if kind is MemberKind.JOIN_MAP:
        # Manager ticks PartyJoinNav directly; this is a safe fallback.
        return idle(reason or "join_map"), None, reason or "join_map"
    if kind is MemberKind.HOLD:
        return idle(reason), None, reason
    if kind is MemberKind.HEAL:
        # Manager returns the stashed ``apply_party_support`` intent when policy
        # picks HEAL. Idle only if that stash is missing.
        return idle(reason or "heal"), previous_goal, reason or "heal"
    if kind is MemberKind.BUFF:
        return idle(reason or "buff"), previous_goal, reason or "buff"
    if kind is MemberKind.POTION:
        return potion(reason), previous_goal, reason
    if kind is MemberKind.DEFEND and defend_id is not None:
        return attack(defend_id, reason, mid_act=mid_act), previous_goal, reason
    if kind is MemberKind.ASSIST and assist_id is not None:
        # Party already chose this id. Solo's locked-target gate runs once
        # more on the current cell, and a closed line does not retarget.
        from .assist import assist_shot_gate

        allowed, blocked = assist_shot_gate(
            game_state,
            origin,
            int(assist_id),
            source=reason,
        )
        if not allowed:
            why = blocked or "assist_blocked"
            return idle(why), previous_goal, why
        return attack(assist_id, reason, mid_act=mid_act), previous_goal, reason
    if kind is MemberKind.FOLLOW:
        if (
            game_state is None
            or origin is None
            or leader_tile is None
            or config is None
        ):
            return idle("follow_incomplete"), previous_goal, "follow_incomplete"
        return plan_follow_intent(
            game_state,
            origin,
            leader_tile,
            config,
            previous_goal=previous_goal,
            rng=rng or random.Random(),
            settle_stand=settle_stand,
            stand_reason=stand_reason,
        )
    return idle(reason), previous_goal, reason


__all__ = [
    "attack",
    "idle",
    "intent_for_kind",
    "list_heal",
    "pick_settle_stand",
    "plan_field_follow",
    "plan_follow_intent",
    "potion",
]
