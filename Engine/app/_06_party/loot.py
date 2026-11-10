"""Party-member loot gates + side/primary pickup (reuses solo loot hop)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from .config import PartyMemberConfig

# PartySubsystem ``cls`` for the wizard (Lineage order: prince 0, knight 1,
# elf 2, wizard 3). Not confirmed against live memory yet.
PARTY_CLS_WIZARD = 3
# A party row this close to ``world_origin`` is the local character.
_SELF_ROW_TILES = 2

if TYPE_CHECKING:
    from app._02_state.objects import WorldObject
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def party_loot_ownership_filter(cfg: PartyMemberConfig) -> Optional[bool]:
    """None = this member does not loot. False = no own/contrib gate.

    Leader policy only. Random ON → party drops, no ownership gate (False);
    the closest non-leader, non-wizard member is chosen separately.
    Random OFF + responsible → every party pile, including a colleague's
    (False), out to the wide engage radius. The closest-member split is
    not applied.
    Any other member → own piles only (True), inside the near radius.
    """
    # The shopkeeper seat does not take ordinary ground loot.
    # A supply pile aimed at someone else is handled by the caller.
    if str(getattr(cfg, "seat_role", "") or "").strip().lower() == "shopkeeper":
        return None
    if bool(getattr(cfg, "random_loot", False)):
        return False
    role = str(getattr(cfg, "loot_role", "none") or "none").strip().lower()
    if role in ("responsible", "self", "looter"):
        return False
    return True


def party_loot_radius(cfg: PartyMemberConfig) -> int:
    """Tiles this member will walk to a pile.

    The near radius is ``farm.loot_max_tiles``, the same cap the leader
    uses to notice a pile and to walk to it. The responsible looter uses
    the wider ``farm.loot_engage_max_tiles``.
    """
    from app._04_decision import player_mode as pm

    role = str(getattr(cfg, "loot_role", "none") or "none").strip().lower()
    wide = (
        not bool(getattr(cfg, "random_loot", False))
        and role in ("responsible", "self", "looter")
    )
    raw = pm.LOOT_ENGAGE_MAX_TILES if wide else pm.LOOT_MAX_TILES
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def party_may_loot(cfg: PartyMemberConfig) -> bool:
    return party_loot_ownership_filter(cfg) is not None


def party_closest_looter_filter(
    state: "GameState",
    origin: Any,
    local_map_id: Optional[int],
) -> Optional[Callable[[Any], bool]]:
    """Item predicate: True when this member is the closest eligible looter.

    Eligible = party members except the leader and the wizard. None = this
    character never takes party drops (wizard, or no origin).
    """
    from app._04_decision.mode_control import is_mage

    if state is None or origin is None or not hasattr(origin, "x"):
        return None
    if is_mage(state):
        return None
    me = (int(origin.x), int(origin.y))
    snapshot = getattr(state, "last_party", None)
    self_name = _self_row_name(snapshot, me, local_map_id)
    others = _other_looter_tiles(snapshot, me, local_map_id, self_name)
    if not others:
        return lambda _item: True

    from app._04_decision.combat_query import object_absolute_tile

    def _ok(item: Any) -> bool:
        try:
            tile = object_absolute_tile(item, origin)
        except Exception:
            return False
        mine = _cheb(me, tile)
        for name, other in others:
            d = _cheb(other, tile)
            if d < mine:
                return False
            # Tie: lower name wins so every client agrees on one looter.
            if d == mine and name < self_name:
                return False
        return True

    return _ok


def _cheb(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def _party_rows(snapshot: Any) -> list[dict]:
    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
        return []
    return [r for r in (snapshot.get("members") or []) if isinstance(r, dict)]


def _row_tile_on_map(
    row: dict, local_map_id: Optional[int]
) -> Optional[tuple[int, int]]:
    from .leader import _party_map_id, _party_tile

    if local_map_id is not None:
        mid = _party_map_id(row)
        if mid is None or int(mid) != int(local_map_id):
            return None
    return _party_tile(row)


def _self_row_name(
    snapshot: Any, me: tuple[int, int], local_map_id: Optional[int]
) -> str:
    best = ""
    best_d = _SELF_ROW_TILES + 1
    for row in _party_rows(snapshot):
        tile = _row_tile_on_map(row, local_map_id)
        if tile is None:
            continue
        d = _cheb(me, tile)
        if d < best_d:
            best_d = d
            best = str(row.get("name") or "").strip()
    return best


def _identity_rows(snapshot: Any) -> list[dict]:
    """Party rows plus the leader block, without the same guid twice."""
    from .follow import guid_key

    raw: list[dict] = []
    if isinstance(snapshot, dict):
        leader = snapshot.get("leader")
        if isinstance(leader, dict):
            raw.append(leader)
        raw.extend(_party_rows(snapshot))
    seen: list[dict] = []
    keys: set[tuple] = set()
    for row in raw:
        gid = guid_key(row.get("guid"))
        name = str(row.get("name") or "").strip().casefold()
        if gid is not None:
            key: tuple = ("g", gid)
        else:
            key = ("n", name, row.get("map_id"), row.get("x"), row.get("y"))
        if key in keys:
            continue
        keys.add(key)
        seen.append(row)
    return seen


def _my_print_identity(print_state: Any) -> tuple[str, str]:
    """``(name, guid)`` from the MyPlayer row. Empty when that row is absent."""
    if not isinstance(print_state, dict):
        return "", ""
    rows = print_state.get("entities") or print_state.get("ents") or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cls = str(row.get("class") or row.get("cls") or "")
        if not (row.get("self") or cls in ("MyPlayer", "SELF")):
            continue
        name = str(row.get("name") or "").strip()
        guid = str(row.get("guid") or row.get("ent") or "").strip()
        return name, guid
    return "", ""


def stable_self_identity(
    snapshot: Any,
    me: tuple[int, int],
    local_map_id: Optional[int],
    *,
    player: Any = None,
    print_state: Any = None,
) -> tuple[str, str]:
    """``(name, guid)`` for supply claims.

    A party guid wins. A unique character name is next. Coordinates are used
    only when nothing else identifies the body, and only when exactly one row
    is close. Two close rows return no identity.
    """
    from .follow import guid_key
    from .leader import _guids_match

    rows = _identity_rows(snapshot)
    print_name, print_guid = _my_print_identity(print_state)
    player_guid = str(getattr(player, "memory_guid", None) or "").strip()
    identity = getattr(player, "identity", None)
    player_name = str(getattr(identity, "name", None) or "").strip()
    if not player_name:
        player_name = str(getattr(player, "species_name", None) or "").strip()
    guid = print_guid or player_guid
    if guid_key(guid) is not None:
        matched = [row for row in rows if _guids_match(row.get("guid"), guid)]
        if len(matched) == 1:
            name = str(matched[0].get("name") or "").strip() or print_name or player_name
            return name, guid
        if len(matched) > 1:
            return "", ""
    name = print_name or player_name
    if name:
        named = [
            row
            for row in rows
            if str(row.get("name") or "").strip().casefold() == name.casefold()
        ]
        if len(named) > 1 and guid_key(guid) is None:
            return "", ""
        if len(named) == 1:
            found = str(named[0].get("guid") or "").strip()
            return name, found or guid
        if not rows:
            return name, guid
        return name, guid
    near: list[dict] = []
    for row in rows:
        tile = _row_tile_on_map(row, local_map_id)
        if tile is None:
            continue
        if _cheb(me, tile) <= _SELF_ROW_TILES:
            near.append(row)
    if len(near) != 1:
        return "", ""
    row = near[0]
    return str(row.get("name") or "").strip(), str(row.get("guid") or "").strip()


def _other_looter_tiles(
    snapshot: Any,
    me: tuple[int, int],
    local_map_id: Optional[int],
    self_name: str,
) -> list[tuple[str, tuple[int, int]]]:
    """(name, nav tile) of eligible looters on this map, excluding self."""
    out: list[tuple[str, tuple[int, int]]] = []
    for row in _party_rows(snapshot):
        if bool(row.get("is_leader")):
            continue
        try:
            if int(row.get("cls")) == PARTY_CLS_WIZARD:
                continue
        except (TypeError, ValueError):
            pass
        name = str(row.get("name") or "").strip()
        if self_name and name == self_name:
            continue
        tile = _row_tile_on_map(row, local_map_id)
        if tile is None:
            continue
        out.append((name, tile))
    return out


def clear_party_loot_sticky(blackboard: Any) -> None:
    """Drop sticky approach loot when follow/join/defend must win."""
    if blackboard is None:
        return
    try:
        from app._04_decision.behaviors.loot_hop import clear_loot_hop

        clear_loot_hop(blackboard)
    except Exception:
        pass
    try:
        blackboard.current_item_id = None
    except Exception:
        pass


def arm_party_loot_side(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
    item_ok: Optional[Callable[[Any], bool]] = None,
) -> None:
    """Append in-range ``PICKUP`` to ``side_intents`` (does not clear)."""
    from app._03_world import ActionType
    from app._04_decision.types import ActionIntent

    if state is None or blackboard is None:
        return
    primary = getattr(blackboard, "intent", None)
    if primary is not None and getattr(primary, "action", None) is ActionType.PICKUP:
        return
    sides = getattr(blackboard, "side_intents", None) or []
    if any(getattr(s, "action", None) is ActionType.PICKUP for s in sides):
        return
    item = find_party_pickup_range_loot(
        state, blackboard, ownership_filter=ownership_filter, item_ok=item_ok
    )
    if item is None:
        return
    try:
        from app._04_decision.loot_sides import _log_side_loot_decide

        _log_side_loot_decide(blackboard, item)
    except Exception:
        pass
    blackboard.side_intents.append(
        ActionIntent(
            action=ActionType.PICKUP,
            target_id=int(item.track_id),
            priority=0.3,
            reason="party side loot in range",
            mid_act=False,
        )
    )


def find_party_pickup_range_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
    item_ok: Optional[Callable[[Any], bool]] = None,
) -> Optional["WorldObject"]:
    """Nearest lootable pile already within pickup tiles."""
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behaviors.loot_hop import recently_clicked_loot
    from app._04_decision.combat_query import (
        is_adena,
        list_lootable,
        tile_distance_from_player,
    )
    from app._04_decision.loot_sides import _item_in_pickup_range
    from app._04_decision.mode_control import is_hp_zero

    if is_hp_zero(state):
        return None

    loot_mode = _party_loot_mode(state, blackboard)
    origin = blackboard.world_origin
    skip = set(excluded_target_ids(blackboard))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )

    sticky_id = blackboard.current_item_id
    if sticky_id is not None and int(sticky_id) not in skip:
        sticky = state.get_object(int(sticky_id))
        if sticky is not None and _item_in_pickup_range(state, sticky, origin):
            if ownership_filter:
                from app._04_decision.ground_loot import loot_ownership_allowed

                if not loot_ownership_allowed(sticky):
                    sticky = None
                else:
                    return sticky
            else:
                return sticky

    candidates = list_lootable(
        state,
        loot_mode=loot_mode,
        farm=None,
        origin=origin,
        check_path=False,
        exclude=skip,
        screen_only=False,
        ownership_filter=ownership_filter,
    )
    in_range: list = []
    for item in candidates:
        if item_ok is not None and not item_ok(item):
            continue
        if _item_in_pickup_range(state, item, origin):
            in_range.append(item)
    if not in_range:
        return None

    return min(
        in_range,
        key=lambda o: (
            0 if is_adena(o) else 1,
            tile_distance_from_player(o),
            int(getattr(o, "track_id", 0)),
        ),
    )


def try_party_hold_loot(
    state: "GameState",
    blackboard: "Blackboard",
    *,
    ownership_filter: bool,
    max_tiles: int = 8,
    item_ok: Optional[Callable[[Any], bool]] = None,
) -> Any:
    """Primary walk-to-item / pickup while HOLD near the leader.

    Returns an ActionIntent when loot won this tick, else None.
    """
    from app._03_world import ObjectType
    from app._04_decision.attack_feedback import excluded_target_ids
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors.loot_hop import (
        begin_loot_item,
        clear_loot_hop,
        recently_clicked_loot,
        tick_loot_item,
        try_finish_pending_pickup,
    )
    from app._04_decision.combat_query import (
        memory_target_gone,
        nearest_lootable,
        tile_distance_from_player,
    )
    from app._04_decision.ground_loot import loot_ownership_allowed
    from app._04_decision.mode_control import is_hp_zero

    if state is None or blackboard is None or is_hp_zero(state):
        return None

    pending = try_finish_pending_pickup(state, blackboard)
    if pending is not None:
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            _tag_party_loot(intent)
            return intent

    loot_mode = _party_loot_mode(state, blackboard)
    skip = set(excluded_target_ids(blackboard))
    skip.update(
        tid
        for tid in blackboard.loot_clicked_ids
        if recently_clicked_loot(blackboard, tid)
    )

    if blackboard.current_item_id is not None:
        sticky = state.get_object(int(blackboard.current_item_id))
        drop = False
        if (
            sticky is None
            or getattr(sticky, "object_type", None) is not ObjectType.ITEM
            or memory_target_gone(state, sticky)
            or recently_clicked_loot(blackboard, sticky.track_id)
        ):
            drop = True
        elif ownership_filter and not loot_ownership_allowed(sticky):
            drop = True
        elif tile_distance_from_player(sticky) > int(max_tiles):
            drop = True
        if drop:
            clear_loot_hop(blackboard)
            blackboard.current_item_id = None
        else:
            status = tick_loot_item(state, blackboard, sticky, fresh=False)
            if status is Status.SUCCESS:
                intent = getattr(blackboard, "intent", None)
                if intent is not None:
                    _tag_party_loot(intent)
                    return intent
            return None

    if item_ok is None:
        item = nearest_lootable(
            state,
            loot_mode=loot_mode,
            farm=None,
            origin=blackboard.world_origin,
            check_path=False,
            exclude=skip,
            screen_only=False,
            ownership_filter=ownership_filter,
        )
    else:
        from app._04_decision.combat_query import list_lootable

        mine = [
            o
            for o in list_lootable(
                state,
                loot_mode=loot_mode,
                farm=None,
                origin=blackboard.world_origin,
                check_path=False,
                exclude=skip,
                screen_only=False,
                ownership_filter=ownership_filter,
            )
            if item_ok(o)
        ]
        item = (
            min(
                mine,
                key=lambda o: (
                    tile_distance_from_player(o),
                    int(getattr(o, "track_id", 0)),
                ),
            )
            if mine
            else None
        )
    if item is None:
        return None
    if tile_distance_from_player(item) > int(max_tiles):
        return None
    begin_loot_item(blackboard, int(item.track_id), item)
    status = tick_loot_item(state, blackboard, item, fresh=True)
    if status is Status.SUCCESS:
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            _tag_party_loot(intent)
            return intent
    return None


def _party_loot_mode(state: "GameState", blackboard: "Blackboard") -> str:
    """Boss pickup rule when the member tick stored it. Otherwise solo loot."""
    from app._04_decision.behaviors.mode_actions import _effective_loot_mode
    from app._04_decision.player_mode import LOOT_MODE_ADENA, LOOT_MODE_ALL

    pickup = str(blackboard.scratch.get("party_loot_pickup") or "")
    if pickup not in ("all", "adena"):
        return _effective_loot_mode(state)
    if pickup == "adena":
        return LOOT_MODE_ADENA
    from app._04_decision.shop_trip import bag_weight_ratio

    try:
        limit = float(blackboard.scratch.get("party_loot_weight") or 0.30)
    except (TypeError, ValueError):
        limit = 0.30
    if bag_weight_ratio(state) >= max(0.01, min(1.0, limit)):
        return LOOT_MODE_ADENA
    return LOOT_MODE_ALL


def _tag_party_loot(intent: Any) -> None:
    why = str(getattr(intent, "reason", "") or "")
    if why.startswith("party_member:"):
        return
    try:
        intent.reason = f"party_member:loot {why}".strip()
    except Exception:
        pass


__all__ = [
    "arm_party_loot_side",
    "clear_party_loot_sticky",
    "find_party_pickup_range_loot",
    "party_closest_looter_filter",
    "party_loot_ownership_filter",
    "party_loot_radius",
    "party_may_loot",
    "try_party_hold_loot",
]
