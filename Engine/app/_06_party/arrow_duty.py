"""Shopkeeper arrow buy / ground drop, and the short member's pickup.

Solo shop, sell, potions, and post-shop hunt return stay on their own flags.
This module sets ``party_pin_shop_behavior`` and ``party_shopkeeper_arrow``
only on the shopkeeper blackboard.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .arrow_policy import (
    DUTY_FOLLOW,
    DUTY_SHOP,
    DUTY_SUPPLY,
    bag_supply_counts,
    choose_supply_duty,
    mage_seat_names,
    mp_recipient_names,
    next_supply_buy,
    remember_delivered,
    report_supply_count,
    rows_with_expected,
    supply_fill_qty,
    supply_pile_matches,
    supply_pile_qty_ok,
)
from .party_log import get_logger as _party_logger

_log = _party_logger("member")

_JOIN = "party_join_leader"
_PIN = "party_pin_shop_behavior"
_FLAG = "party_shopkeeper_arrow"
_NEAR = 3
# Keep the join route while the leader stays inside this many tiles.
_JOIN_REPLAN = 24
# Recipient keeps hunting until the shopkeeper is this close, then stands.
SUPPLY_HOLD_TILES = 12
# How long a close shopkeeper waits for this attempt's stop tile.
STAND_WAIT_S = 8.0
# After a timeout or a failed drop search, leave that member alone this long.
SUPPLY_PAUSE_S = 6.0
# The stop tile is real only after the body has stayed there this long.
HOLD_SETTLE_S = 0.5
# Esc again only while the body is still walking, and only this often.
HOLD_HALT_GAP_S = 0.5
HOLD_HALT_MAX = 3
# Moves to a neighboring tile when the stand has no empty drop tile.
DROP_SHIFT_MAX = 4
_SEEN = "party_supply_seen"
_ATTEMPT = "party_supply_attempt"
_PAUSE = "party_supply_pause"
_CARE_POSE = "party_care_pose"
# Neighbors tried for the empty drop tile, beside the standing recipient.
_DROP_NEIGHBORS = ((1, 1), (-1, 1), (1, -1), (1, 0), (0, 1), (0, -1), (-1, 0))
_SHIFT_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


def supply_hold_for(duty: dict) -> dict[str, Any]:
    """Hold id for one recipient, one item, and one delivery attempt.

    Attempt 0 keeps the original id. A later attempt adds the attempt number
    so a stop tile from the previous try cannot open the drop.
    """
    item = str(duty.get("item") or "arrow")
    name = str(duty.get("name") or "")
    try:
        attempt = int(duty.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    ident = f"hold:{item}:{name}" if attempt <= 0 else f"hold:{item}:{name}:{attempt}"
    hold = {
        "id": ident,
        "for": name,
        "item": item,
        "qty": int(duty.get("qty") or 0),
        "min": int(duty.get("min") or 0),
    }
    guid = str(duty.get("guid") or "").strip()
    if guid:
        hold["guid"] = guid
    return hold


def _hold_with_phase(board: Any, duty: dict) -> dict[str, Any]:
    """The hold for this attempt. ``dropping`` is set once the gesture is announced."""
    hold = supply_hold_for(duty)
    if _attempt(board).get("dropping"):
        hold["dropping"] = True
    return hold


def _hold_confirmed(board: Any, hold: Any) -> bool:
    """True after this hold's body has stopped on one tile."""
    scratch = getattr(board, "scratch", None) if board is not None else None
    prev = scratch.get("party_leader_hold_pose") if isinstance(scratch, dict) else None
    if not isinstance(prev, dict) or not isinstance(hold, dict):
        return False
    return bool(prev.get("confirmed")) and str(prev.get("id") or "") == str(hold.get("id") or "")


def _stop_ground_move(board: Any) -> None:
    """Drop the planned search or travel hop. The click already sent needs Esc."""
    if board is None:
        return
    try:
        from app._04_decision.behaviors.search_hop import clear_search_hop

        clear_search_hop(board)
    except Exception:
        pass
    try:
        from app._04_decision.behaviors.travel import clear_travel

        clear_travel(board)
    except Exception:
        pass


def _hold_pose(board: Any, hold: Any) -> Optional[dict]:
    """Pose row for this hold id. A different attempt does not share it."""
    scratch = getattr(board, "scratch", None) if board is not None else None
    prev = scratch.get("party_leader_hold_pose") if isinstance(scratch, dict) else None
    if not isinstance(prev, dict) or not isinstance(hold, dict):
        return None
    if str(prev.get("id") or "") != str(hold.get("id") or ""):
        return None
    return prev


def _halt_walk_again(prev: Optional[dict]) -> bool:
    """True when another Esc is still allowed.

    The press is skipped once the retry count is used or the last press was
    a moment ago. The caller has already checked that the body is walking
    and that no survival action took this tick.
    """
    if not isinstance(prev, dict):
        return False
    try:
        sent = int(prev.get("halt_n") or 0)
    except (TypeError, ValueError):
        sent = 0
    if sent >= HOLD_HALT_MAX:
        if not prev.get("halt_gave_up"):
            prev["halt_gave_up"] = True
            _log.info("supply hold halt still moving n=%s", sent)
        return False
    now = time.time()
    try:
        last = float(prev.get("halt_at") or 0.0)
    except (TypeError, ValueError):
        last = 0.0
    if sent > 0 and now - last < HOLD_HALT_GAP_S:
        return False
    prev["halt_n"] = sent + 1
    prev["halt_at"] = now
    _log.info("supply hold halt esc n=%s moving=1", sent + 1)
    return True


def recipient_hold_intent(
    state: Any,
    blackboard: Any,
    hold: Any,
    *,
    tracked: bool = False,
) -> Any:
    """Stop the current walk, then hunt in place until the drop starts.

    Esc is sent only while the body is still walking, at a short interval,
    and only a few times. A stop or a survival action sends no further Esc.
    The stand is not confirmed while the body is still walking, so this does
    not start a new search or chase. Once the shopkeeper has announced the
    drop, combat is cleared so the recipient can take the pile.
    """
    if not tracked and leader_hold_displaced(blackboard, state, hold):
        return None
    if isinstance(hold, dict) and hold.get("dropping"):
        if blackboard is not None:
            try:
                from app._04_decision.behaviors.search_hop import clear_search_hop

                clear_search_hop(blackboard)
            except Exception:
                pass
        _drop_combat_lock(blackboard)
        from .intents import idle

        return idle("supply receive")
    if isinstance(hold, dict) and not _hold_confirmed(blackboard, hold):
        _stop_ground_move(blackboard)
        prev = _hold_pose(blackboard, hold)
        moving = not _leader_body_stopped()
        if moving:
            if _halt_walk_again(prev):
                from .intents import supply_halt

                return supply_halt()
            from .intents import idle

            return idle("supply hold")
        if (
            isinstance(prev, dict)
            and int(prev.get("halt_n") or 0) > 0
            and not prev.get("halt_seen_stop")
        ):
            prev["halt_seen_stop"] = True
            _log.info(
                "supply hold halt stopped n=%s",
                int(prev.get("halt_n") or 0),
            )
        from .intents import idle

        return idle("supply hold")
    return supply_wait_intent(state, blackboard)


def supply_rows(rows: Any) -> list:
    """Reports the shopkeeper may supply. An explicit ``supply_ok`` false is away."""
    kept: list = []
    for row in rows or []:
        if isinstance(row, dict) and row.get("supply_ok") is False:
            continue
        kept.append(row)
    return kept


def claim_names_me(claim: Any, self_name: str, self_guid: str = "") -> bool:
    """True when this claim is for the local character.

    When both sides carry a guid, the guid decides. A name match is used
    only when a guid was not published.
    """
    if not isinstance(claim, dict) or bool(claim.get("clear")):
        return False
    from .follow import guid_key
    from .leader import _guids_match

    claim_guid = str(claim.get("guid") or "").strip()
    mine = str(self_guid or "").strip()
    if guid_key(claim_guid) is not None and guid_key(mine) is not None:
        return _guids_match(claim_guid, mine)
    who = str(claim.get("for") or "").strip()
    me = str(self_name or "").strip()
    return bool(who and me and who.casefold() == me.casefold())


def _ring_offsets(ring: int) -> tuple:
    """Chebyshev ring around the recipient. Ring 0 is the original neighbor list."""
    dist = int(ring) + 1
    if dist <= 1:
        return _DROP_NEIGHBORS
    spots = []
    for ox in range(-dist, dist + 1):
        for oy in range(-dist, dist + 1):
            if max(abs(ox), abs(oy)) != dist:
                continue
            spots.append((ox, oy))
    return tuple(spots)


def choose_drop_stand(
    member_x: int,
    member_y: int,
    walkable: Any = None,
    ring: int = 0,
) -> Optional[dict[str, int]]:
    """Empty neighbor of the stand tile, and where the shopkeeper must stand.

    The ground drag always lands one tile at ``(-1, -1)`` from the shopkeeper.
    The shopkeeper stand is that drop tile shifted back by the same offset, and
    it is never the recipient's tile. A blocked ring returns nothing so the
    shopkeeper can step aside and try the next ring.
    """
    from .supply_drop import _DROP_TILES

    dx, dy = int(_DROP_TILES[0][0]), int(_DROP_TILES[0][1])
    member = (int(member_x), int(member_y))
    for ox, oy in _ring_offsets(ring):
        drop = (member[0] + int(ox), member[1] + int(oy))
        stand = (drop[0] - dx, drop[1] - dy)
        if drop == member or stand == member:
            continue
        if walkable is not None and (
            not walkable(drop) or not walkable(stand)
        ):
            continue
        return {
            "stand_x": stand[0],
            "stand_y": stand[1],
            "drop_x": drop[0],
            "drop_y": drop[1],
        }
    return None


def _stand_ready(duty: dict, stand: Any) -> bool:
    """True when this attempt's stop tile has been confirmed."""
    if not isinstance(stand, dict) or stand.get("confirmed") is not True:
        return False
    if str(stand.get("id") or "") != supply_hold_for(duty)["id"]:
        return False
    if str(stand.get("for") or "").strip().casefold() != str(
        duty.get("name") or ""
    ).strip().casefold():
        return False
    try:
        int(stand["x"])
        int(stand["y"])
        int(stand["map_id"])
    except (TypeError, ValueError, KeyError):
        return False
    return True


_NAV_FRAME: dict[int, Optional[tuple[int, int, int, int]]] = {}


def _map_nav_frame(map_id: int) -> Optional[tuple[int, int, int, int]]:
    """``(origin_x, origin_y, width, height)`` for this map's nav grid.

    The loaded terrain is that grid when it is this map. Otherwise the pack
    image and its origin are the grid. The result is not a magnitude guess.
    """
    from app._04_decision.nav_config import get_terrain_map
    from app._04_decision.world_nav.pack_ids import map_id_to_pack_id, pack_for_map_id

    pack_id = map_id_to_pack_id(int(map_id))
    terrain = get_terrain_map()
    if (
        terrain is not None
        and pack_id
        and str(getattr(terrain, "pack_id", "") or "") == str(pack_id)
    ):
        return (
            int(terrain.origin_x),
            int(terrain.origin_y),
            int(terrain.width),
            int(terrain.height),
        )
    mid = int(map_id)
    if mid in _NAV_FRAME:
        return _NAV_FRAME[mid]
    pack = pack_for_map_id(mid)
    frame = None if pack is None else _pack_nav_frame(pack)
    _NAV_FRAME[mid] = frame
    return frame


def _pack_nav_frame(pack: Any) -> Optional[tuple[int, int, int, int]]:
    """Nav tiles from the pack image size and ``pixel_scale``."""
    path = getattr(pack, "nav_path", None) or getattr(pack, "image_path", None)
    if path is None:
        return None
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    import struct

    width, height = struct.unpack(">II", head[16:24])
    scale = max(1, int(getattr(pack, "pixel_scale", 1) or 1))
    tw, th = int(width) // scale, int(height) // scale
    if tw < 1 or th < 1:
        return None
    return (int(pack.origin_x), int(pack.origin_y), tw, th)


def _on_grid(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= int(x) < int(width) and 0 <= int(y) < int(height)


def _coord_on_map(map_id: int, x: int, y: int) -> Optional[tuple[int, int]]:
    """Nav tile for a point whose source is this map's pack.

    A point on the nav grid is a nav tile. A point that lands on that grid
    only after subtracting the pack origin is a game tile. Both at once, and
    neither, stay unread.
    """
    frame = _map_nav_frame(int(map_id))
    if frame is None:
        return None
    ox, oy, width, height = frame
    as_nav = _on_grid(x, y, width, height)
    gx, gy = int(x) - int(ox), int(y) - int(oy)
    as_game = _on_grid(gx, gy, width, height)
    if as_nav and as_game and (gx, gy) != (int(x), int(y)):
        return None
    if as_nav:
        return (int(x), int(y))
    if as_game:
        return (gx, gy)
    return None


def _tile_gap(left: tuple[int, int], right: tuple[int, int]) -> int:
    return max(abs(int(left[0]) - int(right[0])), abs(int(left[1]) - int(right[1])))


def plan_supply_drop(
    duty: dict,
    stand: Any,
    walkable: Any = None,
    ring: int = 0,
) -> Optional[dict]:
    """Shopkeeper travel duty once the recipient has reported a stop tile.

    ``stand`` x,y stay on the duty as received. The walk and the drop use the
    nav tile that map's pack assigns to those coordinates.
    """
    if not _stand_ready(duty, stand):
        return None
    try:
        mx = int(stand["x"])
        my = int(stand["y"])
        mid = int(stand["map_id"])
    except (TypeError, ValueError, KeyError):
        return None
    nav = _coord_on_map(mid, mx, my)
    if nav is None:
        return None
    spot = choose_drop_stand(nav[0], nav[1], walkable, ring=ring)
    if spot is None:
        return None
    planned = dict(duty)
    planned["map_id"] = mid
    planned["x"] = spot["stand_x"]
    planned["y"] = spot["stand_y"]
    planned["exact"] = True
    planned["drop_x"] = spot["drop_x"]
    planned["drop_y"] = spot["drop_y"]
    planned["member_map"] = mid
    planned["member_x"] = mx
    planned["member_y"] = my
    return planned


def remember_supply_stand(runtime: Any, hold: dict, origin: Any, map_id: Any) -> None:
    """The recipient's current tile is the stand. The drop is beside it."""
    if runtime is None or origin is None or not hasattr(origin, "x"):
        return
    try:
        runtime.supply_stand = {
            "id": hold.get("id"),
            "for": hold.get("for"),
            "map_id": None if map_id is None else int(map_id),
            "x": int(origin.x),
            "y": int(origin.y),
            "confirmed": True,
        }
    except (TypeError, ValueError):
        return


def _tile_open(tile: tuple[int, int]) -> bool:
    try:
        from app._04_decision.nav_config import get_terrain_map

        terrain = get_terrain_map()
    except Exception:
        return True
    if terrain is None:
        return True
    try:
        return bool(terrain.is_walkable(int(tile[0]), int(tile[1])))
    except Exception:
        return True


def _claim_key(claim: dict) -> tuple:
    return (
        str(claim.get("id") or ""),
        str(claim.get("item") or ""),
        claim.get("x"),
        claim.get("y"),
    )


def _supply_seen(blackboard: Any, claim: dict) -> bool:
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return False
    return scratch.get(_SEEN) == _claim_key(claim)


def _mark_supply_seen(blackboard: Any, claim: dict) -> None:
    scratch = getattr(blackboard, "scratch", None)
    if isinstance(scratch, dict):
        scratch[_SEEN] = _claim_key(claim)


def _drop_combat_lock(blackboard: Any) -> None:
    """Stop the swing that was in progress so pickup or the stand can own the tick."""
    if blackboard is None:
        return
    if getattr(blackboard, "current_target_id", None) is not None:
        blackboard.current_target_id = None
    try:
        from app._04_decision.behaviors.combat import clear_engage_state

        clear_engage_state(blackboard)
    except Exception:
        return


def supply_wait_intent(state: Any, blackboard: Any) -> Any:
    """Stand still. Attack only a monster already inside reach."""
    from .intents import attack, idle

    if blackboard is not None:
        try:
            from app._04_decision.behaviors.search_hop import clear_search_hop

            clear_search_hop(blackboard)
        except Exception:
            pass
    monster = None
    reach = 1
    if state is not None and blackboard is not None:
        try:
            from app._04_decision.behaviors.hold_ground import hold_ground_reach
            from app._04_decision.combat_query import (
                can_engage_target,
                nearest_attackable,
                tile_distance_from_player,
            )

            reach = int(hold_ground_reach(state))
            origin = getattr(blackboard, "world_origin", None)
            monster = nearest_attackable(
                state,
                origin=origin,
                check_path=False,
                near_tiles=reach,
                screen_only=False,
            )
            if monster is not None and (
                tile_distance_from_player(monster) > reach
                or (origin is not None and not can_engage_target(monster, origin))
            ):
                monster = None
        except Exception:
            monster = None
    if monster is not None:
        tid = int(getattr(monster, "track_id", 0))
        mid = getattr(blackboard, "current_target_id", None) == tid
        try:
            from app._04_decision.behaviors.combat import begin_engage, note_attack_attempt

            if mid:
                note_attack_attempt(blackboard, monster)
            else:
                begin_engage(state, blackboard, tid, finish_kill=True)
        except Exception:
            pass
        if hasattr(blackboard, "emit"):
            from app._02_state.enums import ActionType

            blackboard.current_goal = "combat"
            blackboard.emit(
                ActionType.ATTACK,
                target_id=tid,
                priority=0.5,
                reason="supply hold: in range",
                mid_act=mid,
            )
            intent = getattr(blackboard, "intent", None)
            if intent is not None:
                return intent
        return attack(tid, "supply hold", mid_act=mid)
    _drop_combat_lock(blackboard)
    return idle("supply hold")


def _pair_key(duty: dict) -> tuple[str, str]:
    return (
        str(duty.get("name") or "").strip().casefold(),
        str(duty.get("item") or "arrow").strip(),
    )


def _attempt(board: Any) -> dict:
    raw = board.scratch.get(_ATTEMPT) if board is not None else None
    return dict(raw) if isinstance(raw, dict) else {}


def _bind_attempt(board: Any, duty: dict) -> dict:
    """Keep the attempt counter for this recipient and item."""
    key = _pair_key(duty)
    st = _attempt(board)
    if st.get("key") != key:
        st = {"key": key, "n": 0, "since": 0.0, "shifts": 0}
    duty = dict(duty)
    duty["attempt"] = int(st.get("n") or 0)
    board.scratch[_ATTEMPT] = st
    return duty


def _rows_without_pause(board: Any, rows: list) -> list:
    """Drop members a failed delivery is leaving alone for a few seconds."""
    pauses = board.scratch.get(_PAUSE) if board is not None else None
    if not isinstance(pauses, dict) or not pauses:
        return rows
    now = time.time()
    held: set[str] = set()
    for key, until in pauses.items():
        try:
            if float(until) <= now or not isinstance(key, tuple) or not key:
                continue
        except (TypeError, ValueError):
            continue
        held.add(str(key[0]))
    if not held:
        return rows
    kept = []
    for row in rows:
        who = str(row.get("from") or "").strip().casefold() if isinstance(row, dict) else ""
        if who and who in held:
            continue
        kept.append(row)
    return kept


def cancel_supply_delivery(
    board: Any,
    runtime: Any,
    duty: dict,
    *,
    now: float | None = None,
    reason: str = "supply cancel",
    pause: bool = True,
) -> None:
    """Clear the hold and start a new attempt that ignores the old stop tile.

    ``runtime.supply_hold`` going empty is the existing clear: the leader
    publishes ``supply_hold`` and ``supply_stand`` with ``clear``.
    """
    if runtime is not None:
        runtime.supply_hold = None
        runtime.duty_phase = DUTY_FOLLOW
    if board is None:
        return
    key = _pair_key(duty)
    st = _attempt(board)
    st["key"] = key
    st["n"] = int(st.get("n") or 0) + 1
    st["since"] = 0.0
    st["shifts"] = 0
    st["blocks"] = 0
    st.pop("stand_at", None)
    st.pop("stand_matched_id", None)
    st.pop("defer_since", None)
    st.pop("walk_idle_since", None)
    st.pop("drop_aim", None)
    board.scratch[_ATTEMPT] = st
    if pause:
        pauses = dict(board.scratch.get(_PAUSE) or {})
        pauses[key] = float(time.time() if now is None else now) + SUPPLY_PAUSE_S
        board.scratch[_PAUSE] = pauses
    board.scratch.pop("party_supply_drop", None)
    _log.info(
        "supply cancel reason=%s for=%s item=%s next_attempt=%s",
        reason,
        key[0] or "—",
        key[1],
        st["n"],
    )


def _wait_for_stand(manager: Any, duty: dict) -> Any:
    """Hold until this attempt's stop tile arrives, then cancel and step back."""
    board = manager._nav_blackboard
    runtime = manager.runtime
    st = _attempt(board)
    now = time.time()
    since = float(st.get("since") or 0.0)
    if since > 0.0 and now - since >= STAND_WAIT_S:
        cancel_supply_delivery(board, runtime, duty, now=now, reason="stand timeout")
        runtime.last_kind = "supply"
        runtime.last_reason = "stand timeout"
        return None
    if since <= 0.0:
        st["since"] = now
        board.scratch[_ATTEMPT] = st
    runtime.supply_hold = _hold_with_phase(board, duty)
    runtime.duty_phase = DUTY_SUPPLY
    runtime.last_kind = "supply"
    runtime.last_reason = "wait for stand"
    from .intents import idle

    return idle("supply hold")


def expire_supply_hold(manager: Any) -> bool:
    """Run the stand timeout while this tick is already spent on survival.

    The survival intent still owns the tick. A due hold is cleared on the
    existing cancel path so the leader tells the recipient to move again.
    """
    runtime = getattr(manager, "runtime", None)
    board = getattr(manager, "_nav_blackboard", None)
    if runtime is None or board is None:
        return False
    hold = getattr(runtime, "supply_hold", None)
    if not isinstance(hold, dict) or not str(hold.get("id") or "").strip():
        return False
    scratch = getattr(board, "scratch", None)
    if not isinstance(scratch, dict):
        return False
    st = _attempt(board)
    try:
        since = float(st.get("since") or 0.0)
    except (TypeError, ValueError):
        since = 0.0
    if since <= 0.0 or time.time() - since < STAND_WAIT_S:
        return False
    cancel_supply_delivery(
        board,
        runtime,
        {"name": hold.get("for") or "", "item": hold.get("item") or "arrow"},
        reason="stand timeout",
    )
    return True


def _shift_goal(origin: Any, stand: dict) -> Optional[tuple[int, int]]:
    """One walkable tile beside the shopkeeper, never the recipient's tile."""
    try:
        ox = int(origin.x)
        oy = int(origin.y)
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        from app._03_world.merge.memory_sync import game_to_nav

        rx, ry = game_to_nav(int(stand["x"]), int(stand["y"]))
        recipient = (int(rx), int(ry))
    except (TypeError, ValueError, KeyError):
        recipient = None
    for dx, dy in _SHIFT_STEPS:
        tile = (ox + int(dx), oy + int(dy))
        if recipient is not None and tile == recipient:
            continue
        if not _tile_open(tile):
            continue
        return tile
    return None


def _shift_drop_search(manager: Any, state: Any, duty: dict, stand: dict) -> Any:
    """Step to a safe neighbor and let the next tick measure the drop again."""
    board = manager._nav_blackboard
    runtime = manager.runtime
    st = _attempt(board)
    shifts = int(st.get("shifts") or 0)
    if shifts >= DROP_SHIFT_MAX:
        cancel_supply_delivery(board, runtime, duty, reason="no drop tile")
        runtime.last_kind = "supply"
        runtime.last_reason = "no drop tile"
        return None
    st["shifts"] = shifts + 1
    board.scratch[_ATTEMPT] = st
    runtime.supply_hold = _hold_with_phase(board, duty)
    runtime.duty_phase = DUTY_SUPPLY
    runtime.last_kind = "supply"
    runtime.last_reason = "shift for drop"
    origin = getattr(board, "world_origin", None)
    goal = None if origin is None else _shift_goal(origin, stand)
    if goal is None:
        if int(st["shifts"]) >= DROP_SHIFT_MAX:
            cancel_supply_delivery(board, runtime, duty, reason="no drop tile")
            runtime.last_kind = "supply"
            runtime.last_reason = "no drop tile"
        return None
    _log.info(
        "supply shift for=%s to=%s,%s try=%s",
        str(duty.get("name") or ""),
        goal[0],
        goal[1],
        st["shifts"],
    )
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    if getattr(board, "nav_goal", None) != goal:
        start_travel(board, goal, reason="party supply shift")
    if emit_travel_hop(board, reason="party supply shift", priority=0.6, state=state):
        intent = getattr(board, "intent", None)
        if intent is not None:
            return intent
    return None


def note_care_pose(board: Any, state: Any) -> None:
    """Remember the tile a survival action started from."""
    scratch = getattr(board, "scratch", None)
    if not isinstance(scratch, dict):
        return
    from app._04_decision.world_nav.session import live_pose_from_state

    try:
        pose = live_pose_from_state(state)
    except Exception:
        return
    if pose is None:
        return
    try:
        scratch[_CARE_POSE] = (int(pose.map_id), int(pose.x), int(pose.y))
    except (TypeError, ValueError):
        return


def release_care_pose(board: Any, state: Any) -> None:
    """After survival, re-check shop and drop tiles only if the body moved."""
    scratch = getattr(board, "scratch", None)
    if not isinstance(scratch, dict):
        return
    prev = scratch.pop(_CARE_POSE, None)
    if prev is None:
        return
    from app._04_decision.world_nav.session import live_pose_from_state

    try:
        pose = live_pose_from_state(state)
    except Exception:
        return
    if pose is None:
        return
    try:
        key = (int(pose.map_id), int(pose.x), int(pose.y))
    except (TypeError, ValueError):
        return
    anchored = bool(
        scratch.get("shop_trip")
        or scratch.get(_FLAG)
        or scratch.get("party_supply_drop")
    )
    if not isinstance(prev, tuple) or len(prev) != 3:
        if key != prev and anchored:
            _invalidate_anchored_steps(board)
        return
    if key == prev:
        if anchored:
            _log.info(
                "care in place, shop trip kept at %s,%s map=%s",
                key[1],
                key[2],
                key[0],
            )
        return
    if anchored:
        _log.info(
            "care moved %s,%s map=%s -> %s,%s map=%s, shop approach reset",
            prev[1],
            prev[2],
            prev[0],
            key[1],
            key[2],
            key[0],
        )
    _invalidate_anchored_steps(board)


def _invalidate_anchored_steps(board: Any) -> None:
    """Drop NPC-approach and drop-tile progress. The shop trip itself stays."""
    scratch = getattr(board, "scratch", None)
    if not isinstance(scratch, dict):
        return
    from app._04_decision.shop_trip import (
        PURPOSE_SHOP,
        SCRATCH_SHOP_HALTED,
        SCRATCH_SHOP_SCROLLED,
        SCRATCH_SHOP_SCROLLED_AT,
        SCRATCH_SHOP_TRIP,
    )

    if not (
        scratch.get(SCRATCH_SHOP_TRIP)
        or scratch.get(_FLAG)
        or scratch.get("party_supply_drop")
    ):
        return
    scratch.pop(SCRATCH_SHOP_SCROLLED, None)
    scratch.pop(SCRATCH_SHOP_SCROLLED_AT, None)
    scratch.pop(SCRATCH_SHOP_HALTED, None)
    scratch.pop("party_supply_drop", None)
    if getattr(board, "travel_purpose", None) != PURPOSE_SHOP:
        return
    try:
        from app._04_decision.behaviors.travel import clear_travel

        clear_travel(board)
    except Exception:
        try:
            board.nav_goal = None
        except Exception:
            pass
        board.travel_purpose = None


def _tile_space(x: int, y: int) -> str:
    """Game coordinates sit near 32k. Nav tiles do not."""
    return "game" if max(abs(int(x)), abs(int(y))) >= 20000 else "nav"


def _pose_moved(old: tuple, here: tuple) -> bool:
    """True when the body left the anchored tile.

    A map change counts. The same map in a different coordinate encoding does
    not: party memory and the local pose sometimes use different scales.
    """
    if int(old[0]) != int(here[0]):
        return True
    if _tile_space(old[1], old[2]) != _tile_space(here[1], here[2]):
        return False
    return max(abs(int(old[1]) - int(here[1])), abs(int(old[2]) - int(here[2]))) >= 2


def _stand_left(board: Any, stand: dict) -> bool:
    """True once a confirmed stand tile has moved. The first confirmed tile is the anchor.

    A stand that is not confirmed only refreshes the latest coordinate.
    A different attempt id does not inherit the previous anchor.
    """
    try:
        here = (int(stand["map_id"]), int(stand["x"]), int(stand["y"]))
    except (TypeError, ValueError, KeyError):
        return False
    st = _attempt(board)
    stand_id = str(stand.get("id") or "")
    if stand_id and str(st.get("stand_id") or "") != stand_id:
        st["stand_id"] = stand_id
        st["stand_confirmed"] = False
        st.pop("stand_at", None)
        board.scratch[_ATTEMPT] = st
    if stand.get("confirmed") is not True:
        st["stand_at"] = [here[0], here[1], here[2]]
        board.scratch[_ATTEMPT] = st
        return False
    if not st.get("stand_confirmed"):
        st["stand_confirmed"] = True
        st["stand_at"] = [here[0], here[1], here[2]]
        board.scratch[_ATTEMPT] = st
        return False
    prev = st.get("stand_at")
    if not isinstance(prev, (list, tuple)) or len(prev) != 3:
        st["stand_at"] = [here[0], here[1], here[2]]
        board.scratch[_ATTEMPT] = st
        return False
    try:
        old = (int(prev[0]), int(prev[1]), int(prev[2]))
    except (TypeError, ValueError):
        st["stand_at"] = [here[0], here[1], here[2]]
        board.scratch[_ATTEMPT] = st
        return False
    if _tile_space(old[1], old[2]) != _tile_space(here[1], here[2]) and old[0] == here[0]:
        st["stand_at"] = [here[0], here[1], here[2]]
        board.scratch[_ATTEMPT] = st
        return False
    if not _pose_moved(old, here):
        return False
    return True


def tick_shopkeeper_duty(
    manager: Any,
    state: Any,
    *,
    self_name: str,
) -> Any:
    """One shopkeeper tick. None lets follow and combat run."""
    runtime = manager.runtime
    board = manager._nav_blackboard
    cfg = manager.config
    if board is None:
        runtime.duty_phase = DUTY_FOLLOW
        return None
    from .comms.orders import member_orders
    from app._04_decision.shop_trip import SCRATCH_SHOP_TRIP

    supply_open = bool(getattr(member_orders, "supply_open", False))
    in_progress = bool(
        board.scratch.get(SCRATCH_SHOP_TRIP)
        and board.scratch.get(_FLAG)
        and board.scratch.get("party_supply_item")
    )
    if in_progress and supply_open:
        return _tick_buy(manager, state, _current_buy_duty(board))

    if board.scratch.get(_JOIN):
        release_finished_party_shop(board)
        runtime.duty_phase = DUTY_SHOP
        return _tick_join(manager, state)

    if not supply_open:
        runtime.supply_hold = None
        runtime.duty_phase = DUTY_FOLLOW
        return None

    release_finished_party_shop(board)

    chain = board.scratch.get("party_supply_chain")
    if board.scratch.get(_FLAG) and isinstance(chain, list) and chain:
        _expire_notice(runtime, member_orders.party_reports)
        policy = getattr(manager, "leader_policy", None)
        roster = policy.get("roster") if isinstance(policy, dict) else None
        report_rows = bind_supply_identity(
            _supply_report_rows(board, runtime, member_orders.party_reports),
            getattr(state, "last_party", None),
        )
        nxt = next_supply_buy(
            bag_supply_counts(state),
            _supply_specs(cfg, _mp_names(board, roster, state)),
            after_item=str(chain[-1]),
            skip_buys=_unaffordable_items(board, state),
            rows=report_rows,
            self_name=self_name,
        )
        if nxt is None:
            board.scratch[_JOIN] = True
            runtime.duty_phase = DUTY_SHOP
            return _tick_join(manager, state)
        return _tick_buy(manager, state, nxt)

    if _party_join_active(manager):
        runtime.supply_hold = None
        runtime.duty_phase = DUTY_FOLLOW
        return None

    _expire_notice(runtime, member_orders.party_reports)
    policy = getattr(manager, "leader_policy", None)
    roster = policy.get("roster") if isinstance(policy, dict) else None
    notice = getattr(runtime, "supply_notice", None)
    held = None
    if isinstance(notice, dict):
        held = (notice.get("for"), notice.get("item") or "arrow")
    duty = choose_supply_duty(
        bag_supply_counts(state),
        bind_supply_identity(
            _supply_report_rows(board, runtime, member_orders.party_reports),
            getattr(state, "last_party", None),
        ),
        _supply_specs(cfg, _mp_names(board, roster, state)),
        self_name=self_name,
        held=held,
        skip_buys=_unaffordable_items(board, state),
    )
    if duty is None:
        runtime.supply_hold = None
        _clear_shop_flags(board)
        runtime.duty_phase = DUTY_FOLLOW
        return None
    if duty["kind"] == "buy":
        runtime.supply_hold = None
        return _tick_buy(manager, state, duty)
    duty = _bind_attempt(board, duty)
    stand = getattr(member_orders, "supply_stand", None)
    if (
        isinstance(stand, dict)
        and str(stand.get("id") or "") == supply_hold_for(duty)["id"]
        and _stand_left(board, stand)
    ):
        cancel_supply_delivery(
            board, runtime, duty, reason="stand moved"
        )
        runtime.last_kind = "supply"
        runtime.last_reason = "stand moved"
        return None
    shifts = int(_attempt(board).get("shifts") or 0)
    planned = plan_supply_drop(duty, stand, _tile_open, ring=shifts)
    if planned is not None:
        st = _attempt(board)
        st["shifts"] = 0
        st["since"] = 0.0
        st["latched"] = True
        board.scratch[_ATTEMPT] = st
        runtime.supply_hold = _hold_with_phase(board, duty)
        return _tick_drop(manager, state, planned)
    close = _approach_until_close(manager, state, duty)
    if close is True:
        st = _attempt(board)
        st["latched"] = True
        board.scratch[_ATTEMPT] = st
    if close is not True:
        st = _attempt(board)
        if st.get("latched"):
            now = time.time()
            since = float(st.get("since") or 0.0)
            if since <= 0.0:
                st["since"] = now
            elif now - since >= STAND_WAIT_S:
                cancel_supply_delivery(
                    board, runtime, duty, now=now, reason="stand timeout"
                )
                runtime.last_kind = "supply"
                runtime.last_reason = "stand timeout"
                return None
            board.scratch[_ATTEMPT] = st
            runtime.supply_hold = _hold_with_phase(board, duty)
            return close
        st["since"] = 0.0
        board.scratch[_ATTEMPT] = st
        runtime.supply_hold = None
        return close
    if _stand_ready(duty, stand):
        return _shift_drop_search(manager, state, duty, stand)
    return _wait_for_stand(manager, duty)


def tick_supply_pickup(
    manager: Any,
    state: Any,
    *,
    self_name: str,
    self_guid: str = "",
) -> Any:
    """The named member walks to the dropped arrows and picks them up."""
    from .comms.orders import member_orders

    claim = member_orders.supply_drop
    if not claim_names_me(claim, self_name, self_guid):
        return None
    return _pickup_claim(state, manager._nav_blackboard, claim, manager.runtime)


def leader_supply_pickup(state: Any, blackboard: Any, claim: Optional[dict]) -> Any:
    """Same pickup when the short character is the leader."""
    if not isinstance(claim, dict):
        return None
    return _pickup_claim(state, blackboard, claim, None)


def _bag_adena(state: Any) -> Optional[int]:
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None)
    if inv is None or not bool(getattr(inv, "bag_ready", False)):
        return None
    try:
        return max(0, int(getattr(inv, "adena", 0) or 0))
    except (TypeError, ValueError):
        return None


def _unaffordable_items(board: Any, state: Any) -> set[str]:
    """Items whose last shop price is more than the Adena on hand."""
    prices = board.scratch.get("party_supply_prices")
    if not isinstance(prices, dict):
        return set()
    adena = _bag_adena(state)
    if adena is None:
        return set()
    blocked: set[str] = set()
    for item, price in prices.items():
        try:
            if int(price) > 0 and adena < int(price):
                blocked.add(str(item))
        except (TypeError, ValueError):
            continue
    return blocked


def _expected_book(runtime: Any) -> dict:
    book = getattr(runtime, "supply_expected", None)
    if isinstance(book, dict):
        return book
    book = {}
    try:
        runtime.supply_expected = book
    except Exception:
        return {}
    return book


def _mp_names(board: Any, roster: Any, state: Any) -> set[str]:
    """Roster mage seats plus class mages. Log only when the set changes."""
    seats = mage_seat_names(roster)
    party = getattr(state, "last_party", None)
    names = mp_recipient_names(roster, party)
    scratch = getattr(board, "scratch", None)
    if isinstance(scratch, dict):
        key = (tuple(sorted(seats)), tuple(sorted(names)))
        if scratch.get("_mp_name_key") != key:
            scratch["_mp_name_key"] = key
            _log.info(
                "supply roles mp_seat=%s mp_class_added=%s",
                ",".join(sorted(seats)) or "—",
                ",".join(sorted(names - seats)) or "—",
            )
    return names


def _remember_drop(runtime: Any, duty: dict) -> None:
    from .comms.orders import member_orders

    item = str(duty.get("item") or "arrow")
    name = str(duty.get("name") or "")
    reported = None
    for row in member_orders.party_reports or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("from") or "").strip().casefold() != name.strip().casefold():
            continue
        reported = report_supply_count(row, item)
        break
    try:
        qty = int(duty.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    expected = remember_delivered(_expected_book(runtime), name, item, reported, qty)
    if expected is None:
        return
    _log.info(
        "supply expected %s %s reported=%s qty=%s count=%s",
        name,
        item,
        reported,
        qty,
        expected,
    )


def _supply_report_rows(board: Any, runtime: Any, reports: Any) -> list:
    return _rows_without_pause(
        board,
        rows_with_expected(supply_rows(reports), _expected_book(runtime)),
    )


def _supply_specs(cfg: Any, mages: set[str]) -> list[dict[str, Any]]:
    """HP, then silver arrows. Party supply does not handle MP or depoison."""
    return [
        {
            "item": "hp",
            "member_min": int(cfg.member_hp_min),
            "keeper_min": int(cfg.shopkeeper_hp_min),
            "give": int(cfg.member_hp_give),
            "buy": int(cfg.shopkeeper_hp_buy),
            "can_buy": True,
        },
        {
            "item": "arrow",
            "member_min": int(cfg.member_arrow_min),
            "keeper_min": int(cfg.shopkeeper_arrow_min),
            "give": int(cfg.member_arrow_give),
            "buy": int(cfg.shopkeeper_arrow_buy),
            "skip_names": mages,
            "can_buy": True,
        },
    ]


def note_supply_shop_finished(board: Any) -> bool:
    """Remember the supply item just bought so the next row can be visited.

    False means this success was not a party supply buy, so the caller joins
    the leader immediately.
    """
    item = str(board.scratch.get("party_supply_item") or "").strip()
    if not item:
        return False
    chain = board.scratch.get("party_supply_chain")
    if not isinstance(chain, list):
        chain = []
    if item not in chain:
        chain.append(item)
    board.scratch["party_supply_chain"] = chain
    board.scratch.pop(_PIN, None)
    board.scratch.pop("party_supply_item", None)
    board.scratch.pop("party_supply_keep", None)
    board.scratch.pop("party_supply_configured", None)
    board.scratch.pop("party_arrow_buy_qty", None)
    return True


def _current_buy_duty(board: Any) -> dict[str, Any]:
    """The buy already in progress. Keeps a second shop from being restarted."""
    return {
        "kind": "buy",
        "item": str(board.scratch.get("party_supply_item") or "arrow"),
        "buy": board.scratch.get("party_supply_configured") or 1,
        "keeper_min": board.scratch.get("party_supply_keep") or 0,
        "own": None,
    }


def _tick_buy(manager: Any, state: Any, duty: Optional[dict] = None) -> Any:
    from app._04_decision.shop_trip import (
        SCRATCH_SHOP_BEHAVIOR,
        SCRATCH_SHOP_TRIP,
        tick_shop_trip,
    )

    board = manager._nav_blackboard
    runtime = manager.runtime
    item = str((duty or {}).get("item") or "arrow")
    try:
        buy = max(1, min(999, int((duty or {}).get("buy") or 1)))
    except (TypeError, ValueError):
        buy = 1
    try:
        keep = int((duty or {}).get("keeper_min") or 0)
    except (TypeError, ValueError):
        keep = 0
    own = (duty or {}).get("own")
    runtime.duty_phase = DUTY_SHOP
    runtime.supply_notice = None
    if str(board.scratch.get("party_supply_item") or "") not in ("", item):
        board.scratch.pop(SCRATCH_SHOP_BEHAVIOR, None)
        board.scratch.pop(_PIN, None)
    board.scratch[_FLAG] = True
    board.scratch["party_supply_item"] = item
    board.scratch["party_supply_keep"] = keep
    board.scratch["party_supply_configured"] = buy
    board.scratch["party_arrow_buy_qty"] = supply_fill_qty(own, keep, buy)
    try:
        party_need = int((duty or {}).get("party_need") or 0)
    except (TypeError, ValueError):
        party_need = 0
    if party_need > 0:
        _log.info(
            "supply buy %s qty=%s party_need=%s",
            item,
            board.scratch.get("party_arrow_buy_qty"),
            party_need,
        )
    if not str(board.scratch.get(SCRATCH_SHOP_BEHAVIOR) or "").strip():
        shop_id = supply_shop_id(item)
        if shop_id is None:
            runtime.duty_phase = DUTY_FOLLOW
            return None
        board.scratch[_PIN] = shop_id
    status = tick_shop_trip(state, board)
    if status is None and not board.scratch.get(SCRATCH_SHOP_TRIP):
        board.scratch.pop(_PIN, None)
        if board.scratch.get(_JOIN):
            return _tick_join(manager, state)
        runtime.duty_phase = DUTY_FOLLOW
        return None
    intent = getattr(board, "intent", None)
    reason = f"{item} shop"
    if intent is not None:
        runtime.last_kind = "shop"
        runtime.last_reason = reason
        return intent
    from .intents import idle

    runtime.last_kind = "shop"
    runtime.last_reason = reason
    return idle(reason)


def supply_shop_id(item: str) -> Optional[str]:
    """Existing shop behavior for one supply item. MP has none."""
    from app._04_decision.shops import resolve_shopping_behavior_id

    kind = str(item or "")
    if kind == "hp":
        return resolve_shopping_behavior_id("hp")
    if kind == "depoison":
        return resolve_shopping_behavior_id("depoison")
    if kind == "arrow":
        return shops_arrow_id()
    return None


def shops_arrow_id() -> Optional[str]:
    """Party supply buys silver arrows. Normal arrows are not a supply shop."""
    from app._04_decision.shops import resolve_shopping_behavior_id

    return resolve_shopping_behavior_id("silver_arrows")


def _is_party_leader_row(snapshot: Any, row: Any) -> bool:
    """True when this party row is the leader block."""
    if not isinstance(row, dict):
        return False
    if bool(row.get("is_leader")):
        return True
    leader = snapshot.get("leader") if isinstance(snapshot, dict) else None
    if not isinstance(leader, dict):
        return False
    if row is leader:
        return True
    from .leader import _guids_match

    if _guids_match(row.get("guid"), leader.get("guid")):
        return True
    row_name = str(row.get("name") or "").strip().casefold()
    leader_name = str(leader.get("name") or "").strip().casefold()
    return bool(row_name and row_name == leader_name)


def _remember_stand_match(board: Any, duty: dict) -> None:
    """The party row has stood on this attempt's confirmed stand."""
    duty["_stand_matched"] = True
    if board is None:
        return
    st = _attempt(board)
    st["stand_matched_id"] = str(supply_hold_for(duty).get("id") or "")
    board.scratch[_ATTEMPT] = st


def _stand_was_matched(board: Any, duty: dict) -> bool:
    """True after this attempt's party row has already landed on the stand."""
    if duty.get("_stand_matched"):
        return True
    if board is None:
        return False
    return str(_attempt(board).get("stand_matched_id") or "") == str(
        supply_hold_for(duty).get("id") or ""
    )


def _leader_drop_recheck(state: Any, duty: dict, board: Any = None) -> Any:
    """Refresh a leader drop against the party row.

    None means drop on the already confirmed stand: the recipient is not the
    leader, the leader row has no readable tile, the live nav tile still
    matches, or the row is still two or more tiles away and has not landed on
    this stand yet. ``"cancel"`` means the party row confirms a map change,
    or a move of two or more tiles after that row has already matched the
    stand. ``"defer"`` means a different map id still projects onto the stand,
    so the drop waits. A dict is a stand rebuilt on a one-tile step.
    """
    from .leader import supply_member_row

    snapshot = getattr(state, "last_party", None)
    row = supply_member_row(
        snapshot,
        str(duty.get("name") or ""),
        str(duty.get("guid") or ""),
    )
    if not _is_party_leader_row(snapshot, row):
        return None
    try:
        live = (int(row["map_id"]), int(row["x"]), int(row["y"]))
    except (TypeError, ValueError, KeyError):
        return None
    if live[1] == 0 and live[2] == 0:
        return None
    try:
        planned = (
            int(duty["member_map"]),
            int(duty["member_x"]),
            int(duty["member_y"]),
        )
    except (TypeError, ValueError, KeyError):
        return "defer"
    stand_nav = _coord_on_map(planned[0], planned[1], planned[2])
    if stand_nav is None:
        return "defer"
    on_stand = _coord_on_map(planned[0], live[1], live[2])
    if int(planned[0]) == int(live[0]):
        if on_stand is None:
            return None
        if on_stand == stand_nav:
            _remember_stand_match(board, duty)
            return None
        gap = _tile_gap(stand_nav, on_stand)
        if gap >= 2:
            if _stand_was_matched(board, duty):
                return "cancel"
            return None
        if gap == 1:
            return {
                "id": supply_hold_for(duty)["id"],
                "for": str(duty.get("name") or ""),
                "map_id": live[0],
                "x": live[1],
                "y": live[2],
                "confirmed": True,
            }
        return "defer"
    on_party = _coord_on_map(live[0], live[1], live[2])
    if on_party is not None and on_stand is None:
        return "cancel"
    if on_stand is not None and _tile_gap(stand_nav, on_stand) >= 2:
        return "cancel"
    if on_stand is None:
        return None
    return "defer"


def _clear_defer_clock(board: Any) -> None:
    """Drop the ambiguous-map wait. The walk clock in ``since`` stays."""
    st = _attempt(board)
    if "defer_since" not in st or board is None:
        return
    st.pop("defer_since", None)
    board.scratch[_ATTEMPT] = st


def _hold_ambiguous_leader_drop(manager: Any, duty: dict) -> Any:
    """Wait while a leader row on another map still looks like the stand.

    ``defer_since`` is not ``since``. A walk that already took longer than
    ``STAND_WAIT_S`` is not cancelled by this wait, and a planned drop tick
    that zeroes ``since`` does not restart it.
    """
    runtime = manager.runtime
    board = manager._nav_blackboard
    _clear_walk_idle_clock(board)
    st = _attempt(board)
    now = time.time()
    try:
        started = float(st.get("defer_since") or 0.0)
    except (TypeError, ValueError):
        started = 0.0
    if started > 0.0 and now - started >= STAND_WAIT_S:
        cancel_supply_delivery(
            board, runtime, duty, now=now, reason="stand timeout"
        )
        runtime.last_kind = "supply"
        runtime.last_reason = "stand timeout"
        return None
    if started <= 0.0:
        st["defer_since"] = now
    board.scratch[_ATTEMPT] = st
    if str(getattr(runtime, "last_reason", "") or "") != "supply drop held":
        _log.info(
            "supply drop held for=%s map=%s",
            duty.get("name"),
            duty.get("member_map"),
        )
    runtime.supply_hold = _hold_with_phase(board, duty)
    runtime.duty_phase = DUTY_SUPPLY
    runtime.last_kind = "supply"
    runtime.last_reason = "supply drop held"
    from .intents import idle

    return idle("supply drop held")


def _release_held_drop_label(manager: Any, reason: str) -> None:
    """A passed leader check must not stay labeled as a held drop."""
    runtime = getattr(manager, "runtime", None)
    if runtime is None:
        return
    if str(getattr(runtime, "last_reason", "") or "") != "supply drop held":
        return
    runtime.last_kind = "supply"
    runtime.last_reason = reason


def _clear_walk_idle_clock(board: Any) -> None:
    """Drop the no-click wait. The walk clock in ``since`` stays."""
    st = _attempt(board)
    if "walk_idle_since" not in st or board is None:
        return
    st.pop("walk_idle_since", None)
    board.scratch[_ATTEMPT] = st


def _idle_drop_walk(manager: Any, duty: dict, reason: str) -> Any:
    """Same-map drop with no hop. Eight seconds of this releases the hold.

    ``walk_idle_since`` is not ``since``. A planned tick zeroes ``since``, and
    a hop that is actually emitted clears this clock instead of expiring it.
    """
    runtime = manager.runtime
    board = manager._nav_blackboard
    st = _attempt(board)
    now = time.time()
    try:
        started = float(st.get("walk_idle_since") or 0.0)
    except (TypeError, ValueError):
        started = 0.0
    if started > 0.0 and now - started >= STAND_WAIT_S:
        cancel_supply_delivery(
            board, runtime, duty, now=now, reason="stand timeout"
        )
        runtime.last_kind = "supply"
        runtime.last_reason = "stand timeout"
        return None
    if started <= 0.0:
        st["walk_idle_since"] = now
    board.scratch[_ATTEMPT] = st
    _release_held_drop_label(manager, reason)
    from .intents import idle

    return idle(reason)


def _leader_live_xy(state: Any, duty: dict) -> Optional[tuple[int, int, int]]:
    """Leader party-row map and game tile. None when that row is not the leader."""
    from .leader import supply_member_row

    snapshot = getattr(state, "last_party", None)
    row = supply_member_row(
        snapshot,
        str(duty.get("name") or ""),
        str(duty.get("guid") or ""),
    )
    if not _is_party_leader_row(snapshot, row):
        return None
    try:
        live = (int(row["map_id"]), int(row["x"]), int(row["y"]))
    except (TypeError, ValueError, KeyError):
        return None
    if live[1] == 0 and live[2] == 0:
        return None
    return live


def _stored_drop_aim(board: Any) -> Optional[tuple[int, int, int]]:
    raw = _attempt(board).get("drop_aim")
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        return (int(raw[0]), int(raw[1]), int(raw[2]))
    except (TypeError, ValueError):
        return None


def _remember_drop_aim(board: Any, live: tuple[int, int, int]) -> None:
    if board is None:
        return
    st = _attempt(board)
    st["drop_aim"] = [int(live[0]), int(live[1]), int(live[2])]
    board.scratch[_ATTEMPT] = st


def _inside_drop_box(
    aim: tuple[int, int, int],
    live: tuple[int, int, int],
) -> Optional[bool]:
    """True when ``live`` is inside the 3×3 of ``aim``. None when nav is unknown."""
    if int(aim[0]) != int(live[0]):
        return False
    aim_nav = _coord_on_map(aim[0], aim[1], aim[2])
    live_nav = _coord_on_map(live[0], live[1], live[2])
    if aim_nav is None or live_nav is None:
        return None
    return _tile_gap(aim_nav, live_nav) <= 1


def _aim_stand(duty: dict, live: tuple[int, int, int]) -> dict:
    return {
        "id": supply_hold_for(duty)["id"],
        "for": str(duty.get("name") or ""),
        "map_id": int(live[0]),
        "x": int(live[1]),
        "y": int(live[2]),
        "confirmed": True,
    }


def _apply_leader_drop_recheck(manager: Any, state: Any, duty: dict) -> Any:
    """Aim the drop once inside the leader's 3×3. None means the hold was cleared.

    The live tile inside that box is adopted once. Later reads inside the
    same 3×3 keep that aim and leave the wait clock alone. Leaving the box
    cancels the attempt.
    """
    recheck = _leader_drop_recheck(state, duty)
    runtime = manager.runtime
    board = manager._nav_blackboard
    live = _leader_live_xy(state, duty)
    aim = _stored_drop_aim(board)
    if aim is not None and live is not None:
        inside = _inside_drop_box(aim, live)
        if inside is True:
            _clear_defer_clock(board)
            if (
                int(duty.get("member_map") or -1) == aim[0]
                and int(duty.get("member_x") or 0) == aim[1]
                and int(duty.get("member_y") or 0) == aim[2]
            ):
                return duty
            shifts = int(_attempt(board).get("shifts") or 0)
            replanned = plan_supply_drop(
                duty, _aim_stand(duty, aim), _tile_open, ring=shifts
            )
            return duty if replanned is None else replanned
        if inside is False:
            cancel_supply_delivery(board, runtime, duty, reason="stand moved")
            runtime.last_kind = "supply"
            runtime.last_reason = "stand moved"
            return None
    if recheck is None:
        if live is not None:
            _remember_drop_aim(board, live)
        _clear_defer_clock(board)
        return duty
    if recheck == "defer":
        return _hold_ambiguous_leader_drop(manager, duty)
    if recheck == "cancel":
        cancel_supply_delivery(
            board, runtime, duty, reason="stand moved"
        )
        runtime.last_kind = "supply"
        runtime.last_reason = "stand moved"
        return None
    adopted = (
        int(recheck["map_id"]),
        int(recheck["x"]),
        int(recheck["y"]),
    )
    _remember_drop_aim(board, adopted)
    _clear_defer_clock(board)
    _clear_walk_idle_clock(board)
    shifts = int(_attempt(board).get("shifts") or 0)
    replanned = plan_supply_drop(duty, recheck, _tile_open, ring=shifts)
    _log.info(
        "supply drop recheck %s,%s -> %s,%s",
        duty.get("member_x"),
        duty.get("member_y"),
        recheck.get("x"),
        recheck.get("y"),
    )
    if replanned is None:
        return _shift_drop_search(manager, state, duty, recheck)
    return replanned


def _tick_drop(manager: Any, state: Any, duty: dict) -> Any:
    checked = _apply_leader_drop_recheck(manager, state, duty)
    if checked is None or not isinstance(checked, dict):
        return checked
    duty = checked
    runtime = manager.runtime
    board = manager._nav_blackboard
    runtime.duty_phase = DUTY_SUPPLY
    board.scratch.pop(_FLAG, None)
    board.scratch.pop(_PIN, None)
    board.scratch.pop("party_supply_item", None)
    board.scratch.pop("party_arrow_buy_qty", None)
    arrived = _beside_member(manager, state, duty)
    if arrived is not True:
        job = board.scratch.get("party_supply_drop")
        if isinstance(job, dict):
            job["active"] = False
        return arrived
    st = _attempt(board)
    if not st.get("dropping"):
        st["dropping"] = True
        board.scratch[_ATTEMPT] = st
        runtime.supply_hold = _hold_with_phase(board, duty)
        runtime.last_kind = "supply"
        runtime.last_reason = "supply drop"
        from .intents import idle

        return idle("supply drop")
    from .supply_drop import step_ground_drop

    item = str(duty.get("item") or "arrow")
    result = step_ground_drop(state, board, int(duty["qty"]), kind=item)
    if result is None:
        runtime.last_kind = "supply"
        runtime.last_reason = "arrow drop"
        from .intents import idle

        return idle("arrow drop")
    if result.get("blocked") or not result.get("ok"):
        reason = str(result.get("reason") or "arrow drop blocked")
        st = _attempt(board)
        blocks = int(st.get("blocks") or 0) + 1
        st["blocks"] = blocks
        if st.get("key") is None:
            st["key"] = _pair_key(duty)
        board.scratch[_ATTEMPT] = st
        _log.info(
            "supply drop blocked for=%s try=%s reason=%s",
            str(duty.get("name") or ""),
            blocks,
            reason,
        )
        if blocks >= DROP_SHIFT_MAX:
            cancel_supply_delivery(board, runtime, duty, reason="arrow drop blocked")
            runtime.last_kind = "supply"
            runtime.last_reason = reason
            return None
        runtime.duty_phase = DUTY_SUPPLY
        runtime.last_kind = "supply"
        runtime.last_reason = reason
        from .intents import idle

        return idle(reason)
    runtime.supply_notice = {
        "id": f"{item}:{duty['name']}:{int(time.time())}",
        "for": str(duty["name"]),
        "item": item,
        "min": int(duty.get("min") or 0),
        "map_id": result.get("map_id"),
        "x": result.get("x"),
        "y": result.get("y"),
        "qty": int(duty["qty"]),
        "at": time.time(),
    }
    _remember_drop(runtime, duty)
    if board is not None:
        done = _attempt(board)
        done.pop("drop_aim", None)
        if done.get("key") is not None:
            done["blocks"] = 0
        board.scratch[_ATTEMPT] = done
    runtime.supply_hold = None
    runtime.duty_phase = DUTY_FOLLOW
    runtime.last_kind = "supply"
    runtime.last_reason = f"{item} dropped"
    return None


def _party_join_active(manager: Any) -> bool:
    """True while the member's world-nav join still owns the scroll and the walk."""
    nav = getattr(manager, "_join_nav", None)
    return bool(getattr(nav, "active", False))


def _memory_game_xy(
    state: Any,
    name: Any,
    guid: str = "",
) -> Optional[tuple[int, int, int]]:
    """Live party-memory map and game xy. None when that row has no tile.

    The row is chosen by guid, or by a unique name. Coordinates are not used
    to pick which person this is.
    """
    who = str(name or "").strip()
    if (not who and not str(guid or "").strip()) or state is None:
        return None
    from .leader import supply_member_row

    row = supply_member_row(getattr(state, "last_party", None), who, str(guid or ""))
    if not isinstance(row, dict):
        return None
    try:
        mx = int(row["x"])
        my = int(row["y"])
        mid = int(row["map_id"])
    except (TypeError, ValueError, KeyError):
        return None
    if mx == 0 and my == 0:
        return None
    return mid, mx, my


def _approach_until_close(manager: Any, state: Any, duty: dict) -> Any:
    """True when close enough for the recipient to stand. Else a same-map walk.

    Another map is left alone. The recipient keeps hunting until this is true.
    """
    board = manager._nav_blackboard
    origin = getattr(board, "world_origin", None)
    live = _memory_game_xy(state, duty.get("name"), str(duty.get("guid") or ""))
    if live is not None:
        mid, mx, my = live
    else:
        try:
            mx = int(duty.get("x"))
            my = int(duty.get("y"))
            mid = int(duty.get("map_id"))
        except (TypeError, ValueError):
            return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    if pose is None or origin is None:
        return None
    if int(pose.map_id) != mid:
        return None
    from app._03_world.merge.memory_sync import game_to_nav
    from app._03_world.space.world_coords import tile_chebyshev

    mx, my = game_to_nav(mx, my)
    dist = tile_chebyshev(int(origin.x), int(origin.y), mx, my)
    if dist <= SUPPLY_HOLD_TILES:
        return True
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    goal = (int(mx), int(my))
    source = "memory" if live is not None else "report"
    goal_key = (str(duty.get("name") or ""), source, int(mid), goal[0], goal[1])
    prev_goal = board.scratch.get("party_approach_goal")
    if prev_goal != goal_key:
        board.scratch["party_approach_goal"] = goal_key
        if (
            isinstance(prev_goal, tuple)
            and len(prev_goal) == 5
            and prev_goal[0] == goal_key[0]
            and prev_goal[2:] != goal_key[2:]
        ):
            _log.info(
                "approach retarget %s %s,%s map=%s via %s -> %s,%s map=%s via %s",
                goal_key[0],
                prev_goal[3],
                prev_goal[4],
                prev_goal[2],
                prev_goal[1],
                goal[0],
                goal[1],
                mid,
                source,
            )
    if getattr(board, "nav_goal", None) != goal:
        start_travel(board, goal, reason="party supply approach")
    if emit_travel_hop(
        board, reason="party supply approach", priority=0.6, state=state
    ):
        intent = getattr(board, "intent", None)
        if intent is not None:
            manager.runtime.last_kind = "supply"
            manager.runtime.last_reason = "walk to member"
            return intent
    return None


def _beside_member(manager: Any, state: Any, duty: dict) -> Any:
    """True when standing next to the short member. Otherwise a walk intent."""
    board = manager._nav_blackboard
    origin = getattr(board, "world_origin", None)
    try:
        mx = int(duty.get("x"))
        my = int(duty.get("y"))
        mid = int(duty.get("map_id"))
    except (TypeError, ValueError):
        manager.runtime.duty_phase = DUTY_FOLLOW
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    if pose is None or origin is None:
        return _idle_drop_walk(manager, duty, "arrow drop no pose")
    if int(pose.map_id) != mid:
        # World nav wants the report's game xy. Do not convert that branch.
        _clear_walk_idle_clock(board)
        return _tick_nav(manager, state, mid, mx, my, reason="party_supply_walk")
    from app._03_world.merge.memory_sync import game_to_nav
    from app._03_world.space.world_coords import tile_chebyshev

    # Reports carry raw game xy (~32k). start_travel and world_origin are nav tiles.
    # game_to_nav leaves an already-nav pair unchanged.
    mx, my = game_to_nav(mx, my)
    dist = tile_chebyshev(int(origin.x), int(origin.y), mx, my)
    # exact: stand on the tile that makes the drag land on the empty neighbor.
    limit = 0 if bool(duty.get("exact")) else _NEAR
    if dist <= limit:
        _clear_walk_idle_clock(board)
        return True
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    goal = (int(mx), int(my))
    if getattr(board, "nav_goal", None) != goal:
        start_travel(board, goal, reason="party arrow drop")
    if emit_travel_hop(board, reason="party arrow drop", priority=0.6, state=state):
        intent = getattr(board, "intent", None)
        if intent is not None:
            _clear_walk_idle_clock(board)
            manager.runtime.last_kind = "supply"
            manager.runtime.last_reason = "walk to member"
            return intent
    return _idle_drop_walk(manager, duty, "arrow drop walk")


def _expire_notice(runtime: Any, rows: Any) -> None:
    notice = getattr(runtime, "supply_notice", None)
    if not isinstance(notice, dict):
        return
    who = str(notice.get("for") or "").casefold()
    item = str(notice.get("item") or "arrow")
    try:
        floor = int(notice.get("min") or 0)
    except (TypeError, ValueError):
        floor = 0
    try:
        age = time.time() - float(notice.get("at") or 0.0)
    except (TypeError, ValueError):
        age = 0.0
    count = None
    for row in rows or []:
        if str(row.get("from") or "").strip().casefold() == who:
            count = report_supply_count(row, item)
            break
    if age > 90.0 or (count is not None and count >= floor):
        runtime.supply_notice = None


def _party_leader_game_pose(manager: Any, state: Any) -> Optional[tuple[int, int, int]]:
    """This tick's party-memory map and game xy for the leader.

    Empty when the read missed. A leader on another map still has a pose.
    """
    if getattr(state, "party_read_ok", None) is not True:
        return None
    from .leader import _party_game_xy, _party_map_id, party_member_block

    cfg = getattr(manager, "config", None)
    name = str(getattr(cfg, "leader_name", "") or "")
    if not name:
        name = str(getattr(getattr(manager, "runtime", None), "leader_name_seen", "") or "")
    block = party_member_block(getattr(state, "last_party", None), name)
    if not isinstance(block, dict):
        return None
    map_id = _party_map_id(block)
    xy = _party_game_xy(block)
    if map_id is None or xy is None:
        return None
    return int(map_id), int(xy[0]), int(xy[1])


def _held_join_goal(board: Any) -> Optional[tuple[int, int, int]]:
    """The join route already started, as map and game xy."""
    scratch = getattr(board, "scratch", None) if board is not None else None
    goal = scratch.get("party_nav_goal") if isinstance(scratch, dict) else None
    if not isinstance(goal, tuple) or len(goal) != 4 or goal[0] != "party_join_leader":
        return None
    try:
        return int(goal[1]), int(goal[2]), int(goal[3])
    except (TypeError, ValueError):
        return None


def _tick_join(manager: Any, state: Any) -> Any:
    """Walk back to the leader after the buy list is finished.

    The goal is the party-memory game coordinate on whatever map the leader
    is on. A same-map sticky tile is not that coordinate, and it is cleared
    while the maps differ.
    """
    from .intents import idle

    board = manager._nav_blackboard
    runtime = manager.runtime
    dist = getattr(runtime, "leader_dist", None)
    same = bool(getattr(runtime, "leader_same_map", False))
    if same and dist is not None and int(dist) <= _NEAR:
        _finish_join(manager)
        return None
    live = _party_leader_game_pose(manager, state)
    held = _held_join_goal(board)
    if live is None:
        target = held
    elif (
        held is not None
        and held[0] == live[0]
        and max(abs(held[1] - live[1]), abs(held[2] - live[2])) < _JOIN_REPLAN
    ):
        target = held
    else:
        target = live
        _log.info(
            "supply join leader map=%s xy=(%s,%s)",
            live[0],
            live[1],
            live[2],
        )
    if target is None:
        return idle("join leader no pose")
    map_id, x, y = target
    intent = _tick_nav(
        manager,
        state,
        int(map_id),
        int(x),
        int(y),
        reason="party_join_leader",
    )
    if intent is None:
        _finish_join(manager)
    return intent


def _tick_nav(
    manager: Any,
    state: Any,
    map_id: int,
    x: int,
    y: int,
    *,
    reason: str,
) -> Any:
    from app._04_decision.talking_scroll import talking_scroll_available
    from app._04_decision.world_nav.hooks import SCRATCH_WORLD_NAV
    from app._04_decision.world_nav.planner_api import Goal
    from app._04_decision.world_nav.session import WorldNavSession, live_pose_from_state

    board = manager._nav_blackboard
    pose = live_pose_from_state(state)
    if pose is None:
        from .intents import idle

        return idle("world nav no pose")
    session = board.scratch.get(SCRATCH_WORLD_NAV)
    goal_key = (reason, int(map_id), int(x), int(y))
    same_goal = (
        isinstance(session, WorldNavSession)
        and session.reason == reason
        and board.scratch.get("party_nav_goal") == goal_key
    )
    if same_goal and session.phase in ("done", "fail"):
        if int(pose.map_id) == int(map_id) or session.phase == "done":
            return None
        if time.time() < float(board.scratch.get("party_nav_retry") or 0.0):
            from .intents import idle

            return idle("world nav retry")
        same_goal = False
    if not same_goal:
        session = WorldNavSession()
        adena = None
        inv = getattr(getattr(state, "player", None), "inventory", None)
        if inv is not None:
            try:
                adena = int(getattr(inv, "adena", 0) or 0)
            except (TypeError, ValueError):
                adena = None
        try:
            ok = session.begin(
                pose,
                Goal("point", int(map_id), int(x), int(y)),
                reason=reason,
                has_talking_scroll=talking_scroll_available(),
                adena=adena,
                use_npc_teleporters=True,
            )
        except Exception:
            ok = False
        board.scratch[SCRATCH_WORLD_NAV] = session
        board.scratch["party_nav_goal"] = goal_key
        if not ok:
            board.scratch["party_nav_retry"] = time.time() + 5.0
            if int(pose.map_id) == int(map_id):
                return None
            from .intents import idle

            return idle("world nav no plan")
    try:
        session.tick(state, board)
    except Exception:
        from .intents import idle

        return idle("world nav tick")
    if session.phase in ("done", "fail") and int(pose.map_id) == int(map_id):
        return None
    intent = getattr(board, "intent", None)
    if intent is not None:
        manager.runtime.last_kind = "shop" if reason == "party_join_leader" else "supply"
        manager.runtime.last_reason = reason
        return intent
    from .intents import idle

    return idle(reason)


def _finish_join(manager: Any) -> None:
    board = manager._nav_blackboard
    if board is not None:
        _clear_shop_flags(board)
        from app._04_decision.world_nav.hooks import SCRATCH_WORLD_NAV

        session = board.scratch.get(SCRATCH_WORLD_NAV)
        if getattr(session, "reason", "") in ("party_join_leader", "party_supply_walk"):
            board.scratch.pop(SCRATCH_WORLD_NAV, None)
        board.scratch.pop("party_nav_goal", None)
    manager.runtime.duty_phase = DUTY_FOLLOW


def bind_supply_identity(rows: Any, snapshot: Any) -> list:
    """Copy a unique party guid onto each report. Skip a duplicated name.

    With no party snapshot the reports are unchanged. Coordinates never choose
    which row a name belongs to.
    """
    from .leader import supply_member_row
    from .loot import _identity_rows

    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
        return [row for row in (rows or []) if isinstance(row, dict)]
    kept: list = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        who = str(row.get("from") or "").strip()
        if not who:
            continue
        named = [
            member
            for member in _identity_rows(snapshot)
            if str(member.get("name") or "").strip().casefold() == who.casefold()
        ]
        guid = str(row.get("guid") or "").strip()
        if len(named) > 1 and not guid:
            _log.info("supply target ambiguous name=%s", who)
            continue
        if guid and supply_member_row(snapshot, who, guid) is None and named:
            _log.info("supply target ambiguous name=%s", who)
            continue
        copied = dict(row)
        if not guid and len(named) == 1:
            found = str(named[0].get("guid") or "").strip()
            if found:
                copied["guid"] = found
        kept.append(copied)
    return kept


def release_finished_party_shop(board: Any) -> None:
    """Drop a completed party shop's leftover travel so the join can start.

    An in-progress buy still has ``party_supply_item`` and is left alone.
    Solo shop trips, which never set the party flag, are left alone.
    """
    scratch = getattr(board, "scratch", None) if board is not None else None
    if not isinstance(scratch, dict):
        return
    if scratch.get("shop_trip") and scratch.get("party_supply_item"):
        return
    if not (
        scratch.get(_FLAG)
        or scratch.get("party_supply_chain")
        or scratch.get(_JOIN)
    ):
        return
    changed = False
    if scratch.get("shop_trip"):
        from app._04_decision.shop_trip import clear_shop_trip

        clear_shop_trip(board)
        changed = True
    else:
        for key in (
            "shop_scrolled",
            "shop_scrolled_at",
            "shop_halted",
            "shop_scroll_retries",
        ):
            if scratch.pop(key, None) is not None:
                changed = True
        if getattr(board, "travel_purpose", None) == "shop":
            try:
                from app._04_decision.behaviors.travel import clear_travel

                clear_travel(board)
            except Exception:
                try:
                    board.nav_goal = None
                except Exception:
                    pass
                board.travel_purpose = None
            changed = True
    if scratch.pop("post_shop_return", None) is not None:
        changed = True
    session = scratch.get("world_nav_session")
    reason = str(getattr(session, "reason", "") or "")
    need = str(scratch.get("need_world_nav") or "")
    if need == "after_shop" or reason in ("after_shop", "post_shop"):
        try:
            from app._04_decision.world_nav.hooks import clear_world_nav_run

            clear_world_nav_run(board)
        except Exception:
            scratch.pop("need_world_nav", None)
            scratch.pop("world_nav_session", None)
        try:
            from app._04_decision.mode_control import set_mode
            from app._04_decision.player_mode import PlayerMode

            if getattr(board, "player_mode", None) is PlayerMode.WORLD_NAV:
                set_mode(board, PlayerMode.FARMING)
        except Exception:
            pass
        changed = True
    if changed:
        _log.info("party shop finished; join not blocked")


def _leader_body_stopped() -> bool:
    """True only when the action slot says the body is not walking."""
    try:
        from app._05_action.body_pose import body_is_moving, body_is_standing

        if body_is_standing() is True:
            return True
        return body_is_moving() is False
    except Exception:
        return False


def leader_hold_displaced(board: Any, world: Any, hold: Any) -> bool:
    """True after a settled stop, then a two-tile step or a map change.

    Steps taken before that stop update the latest tile and do not cancel.
    The stop counts only when the body is not walking and the live map and
    tile stay put for ``HOLD_SETTLE_S``. One stopped sample is not enough.
    Map id 0 is Talking Island and is a real map. A pose that could not be
    read is not. Tile ``0,0`` is not a stop. After the stop, a two-tile step
    stays on the hold until the drop is announced. A map change cancels
    before that. Once the drop is announced, two tiles cancel as well. One
    tile does not.
    """
    scratch = getattr(board, "scratch", None) if board is not None else None
    if not isinstance(scratch, dict) or not isinstance(hold, dict) or not hold.get("id"):
        return False
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(world)
    if pose is None:
        prev = scratch.get("party_leader_hold_pose")
        return bool(
            isinstance(prev, dict)
            and prev.get("moved")
            and str(prev.get("id")) == str(hold.get("id"))
        )
    here = (int(pose.map_id), int(pose.x), int(pose.y))
    key = str(hold.get("id"))
    prev = scratch.get("party_leader_hold_pose")
    if not isinstance(prev, dict) or str(prev.get("id") or "") != key:
        scratch["party_leader_hold_pose"] = {
            "id": key,
            "map": here[0],
            "x": here[1],
            "y": here[2],
            "moved": False,
            "stopped": _leader_body_stopped(),
        }
        return False
    if prev.get("moved"):
        prev["map"], prev["x"], prev["y"] = here
        return True
    if not prev.get("confirmed"):
        prev_map = prev.get("map")
        same = (
            prev_map is not None
            and int(prev_map) == here[0]
            and int(prev.get("x") or 0) == here[1]
            and int(prev.get("y") or 0) == here[2]
        )
        prev["map"], prev["x"], prev["y"] = here
        stopped = _leader_body_stopped()
        prev["stopped"] = stopped
        if stopped and same and not (here[1] == 0 and here[2] == 0):
            try:
                since = float(prev.get("settle_at") or 0.0)
            except (TypeError, ValueError):
                since = 0.0
            now = time.time()
            if since <= 0.0:
                prev["settle_at"] = now
            elif now - since >= HOLD_SETTLE_S:
                prev["confirmed"] = True
                prev["anchor_map"], prev["anchor_x"], prev["anchor_y"] = here
                _log.info(
                    "supply hold settled id=%s map=%s xy=(%s,%s)",
                    key,
                    here[0],
                    here[1],
                    here[2],
                )
        else:
            prev["settle_at"] = 0.0
        return False
    try:
        anchor = (
            int(prev["anchor_map"]),
            int(prev["anchor_x"]),
            int(prev["anchor_y"]),
        )
    except (TypeError, ValueError, KeyError):
        anchor = (int(prev.get("map") or 0), int(prev.get("x") or 0), int(prev.get("y") or 0))
    prev["map"], prev["x"], prev["y"] = here
    if (
        _tile_space(anchor[1], anchor[2]) != _tile_space(here[1], here[2])
        and anchor[0] == here[0]
    ):
        prev["anchor_map"], prev["anchor_x"], prev["anchor_y"] = here
        return False
    if not _pose_moved(anchor, here):
        return False
    if int(anchor[0]) == int(here[0]) and not (
        isinstance(hold, dict) and hold.get("dropping")
    ):
        return False
    prev["moved"] = True
    _log.info("supply hold moved id=%s", key)
    return True


def leader_supply_stand(board: Any, snapshot: Any, hold: Any) -> Optional[dict]:
    """The confirmed stop tile, held until this drop ends.

    Party memory is not the source. Map id 0 is Talking Island and is sent.
    A missing map is not. Tile ``0,0`` is not sent. After confirmation the
    anchored stop is returned. A later live step does not publish a new tile.
    """
    del snapshot
    if not isinstance(hold, dict) or not str(hold.get("id") or "").strip():
        return None
    scratch = getattr(board, "scratch", None) if board is not None else None
    prev = scratch.get("party_leader_hold_pose") if isinstance(scratch, dict) else None
    if (
        not isinstance(prev, dict)
        or not prev.get("confirmed")
        or str(prev.get("id") or "") != str(hold.get("id"))
    ):
        return None
    try:
        mid = int(prev["anchor_map"])
        x = int(prev["anchor_x"])
        y = int(prev["anchor_y"])
    except (TypeError, ValueError, KeyError):
        try:
            mid = int(prev["map"])
            x = int(prev["x"])
            y = int(prev["y"])
        except (TypeError, ValueError, KeyError):
            return None
    if x == 0 and y == 0:
        return None
    return {
        "id": str(hold.get("id")),
        "for": str(hold.get("for") or ""),
        "map_id": mid,
        "x": x,
        "y": y,
        "confirmed": True,
    }


def leader_supply_action(
    world: Any,
    blackboard: Any,
    hold: Any,
    claim: Any,
) -> Any:
    """Leader tick before the hunt decision.

    Critical retreat, then the same urgent self care members use, then a
    supply pickup or stand. A hold only stops new attacks and chase. Steps
    before the body stops stay on the hold. After the stop, a two-tile step
    stays until the drop is announced. A map change returns None so the hunt
    decision runs again. Once the drop is announced, two tiles do too.
    """
    if world is None or blackboard is None:
        return None
    from .loot import stable_self_identity
    from .support import party_critical_escape, urgent_self_survival

    escape = party_critical_escape(world, blackboard)
    if escape is not None:
        return escape
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(world)
    origin = getattr(blackboard, "world_origin", None)
    xy = (int(pose.x), int(pose.y)) if pose is not None else (
        int(getattr(origin, "x", 0) or 0),
        int(getattr(origin, "y", 0) or 0),
    )
    map_id = int(pose.map_id) if pose is not None else None
    name, guid = stable_self_identity(
        getattr(world, "last_party", None),
        xy,
        map_id,
        player=getattr(world, "player", None),
        print_state=getattr(world, "last_print_state", None),
    )
    care = urgent_self_survival(world, blackboard, origin)
    if care is not None:
        note_care_pose(blackboard, world)
        if claim_names_me(hold, name, guid):
            leader_hold_displaced(blackboard, world, hold)
        return care
    if claim_names_me(claim, name, guid):
        pickup = leader_supply_pickup(world, blackboard, claim if isinstance(claim, dict) else None)
        if pickup is not None:
            return pickup
    if claim_names_me(hold, name, guid):
        if leader_hold_displaced(blackboard, world, hold):
            return None
        return recipient_hold_intent(world, blackboard, hold, tracked=True)
    return None


def _clear_shop_flags(board: Any) -> None:
    board.scratch.pop(_FLAG, None)
    board.scratch.pop(_PIN, None)
    board.scratch.pop(_JOIN, None)
    board.scratch.pop("party_arrow_buy_qty", None)
    board.scratch.pop("party_supply_item", None)
    board.scratch.pop("party_supply_chain", None)


def _pickup_claim(state: Any, blackboard: Any, claim: dict, runtime: Any) -> Any:
    if blackboard is None:
        return None
    try:
        tx = int(claim.get("x"))
        ty = int(claim.get("y"))
        mid = int(claim.get("map_id"))
    except (TypeError, ValueError):
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    origin = getattr(blackboard, "world_origin", None)
    if pose is None or origin is None or int(pose.map_id) != mid:
        return None
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.combat_query import is_adena, list_lootable, object_absolute_tile

    dist = tile_chebyshev(int(origin.x), int(origin.y), tx, ty)
    pile = None
    if dist <= 8:
        for item in list_lootable(
            state,
            loot_mode="all_items",
            farm=None,
            origin=origin,
            check_path=False,
            ownership_filter=False,
        ):
            try:
                tile = object_absolute_tile(item, origin)
            except Exception:
                continue
            if tile is None or is_adena(item):
                continue
            if not supply_pile_matches(item, str(claim.get("item") or "")):
                continue
            if not supply_pile_qty_ok(item, claim.get("qty")):
                continue
            if tile_chebyshev(int(tile[0]), int(tile[1]), tx, ty) <= 2:
                pile = item
                break
    if pile is not None and dist <= 2:
        from app._02_state.enums import ActionType
        from .types import ActionIntent

        _drop_combat_lock(blackboard)
        _mark_supply_seen(blackboard, claim)
        if runtime is not None:
            runtime.last_kind = "supply"
            runtime.last_reason = f"pick up {claim.get('item') or 'supply'}"
        return ActionIntent(
            action=ActionType.PICKUP,
            target_id=int(getattr(pile, "track_id", 0)),
            priority=0.7,
            reason=f"party_member:supply {claim.get('item') or 'arrows'}",
        )
    if dist <= _NEAR and pile is None:
        # Stay only until the pile appears. Once it has been picked up, hunt resumes.
        if _supply_seen(blackboard, claim):
            return None
        _drop_combat_lock(blackboard)
        from .intents import idle

        if runtime is not None:
            runtime.last_kind = "supply"
            runtime.last_reason = "supply pickup"
        return idle("supply pickup")
    _drop_combat_lock(blackboard)
    from app._04_decision.behaviors.travel import emit_travel_hop, start_travel

    goal = (tx, ty)
    if getattr(blackboard, "nav_goal", None) != goal:
        start_travel(blackboard, goal, reason="party supply pickup")
    if emit_travel_hop(
        blackboard, reason="party supply pickup", priority=0.6, state=state
    ):
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            if runtime is not None:
                runtime.last_kind = "supply"
                runtime.last_reason = "walk to arrows"
            return intent
    from .intents import idle

    if runtime is not None:
        runtime.last_kind = "supply"
        runtime.last_reason = "supply pickup"
    return idle("supply pickup")
