"""Resolve the monster the member should help kill (leader's fight)."""
from __future__ import annotations

from typing import Any, Optional

from .config import PartyMemberConfig
from .follow import guid_key

_STRIKE_CLASSES = frozenset({"Monster", "SummonedMonster"})


def _strike_hits_guid(row: object, wanted: set[int]) -> bool:
    if not isinstance(row, dict) or not wanted:
        return False
    if str(row.get("class") or "") not in _STRIKE_CLASSES:
        return False
    key = guid_key(row.get("tgt"))
    return key is not None and key in wanted


def _monster_for_strike(game_state: Any, row: dict[str, Any]) -> Any:
    ent = str(row.get("ent") or "").strip().lower()
    monsters = list(game_state.monsters()) if hasattr(game_state, "monsters") else []
    if ent:
        for obj in monsters:
            got = str(getattr(obj, "memory_ent", None) or "").strip().lower()
            if got and got == ent:
                return obj
    world = row.get("world") if isinstance(row.get("world"), dict) else None
    if not isinstance(world, dict):
        return None
    try:
        cx, cy = int(world["cx"]), int(world["cy"])
    except (KeyError, TypeError, ValueError):
        return None
    matches = [
        obj
        for obj in monsters
        if getattr(obj, "world_cx", None) is not None
        and getattr(obj, "world_cy", None) is not None
        and int(obj.world_cx) == cx
        and int(obj.world_cy) == cy
    ]
    if not matches:
        return None
    return min(matches, key=lambda o: int(getattr(o, "track_id", 0) or 0))


def resolve_external_target(game_state: Any, config: PartyMemberConfig) -> Any:
    """Operator / WS sticky target if still alive locally."""
    if game_state is None:
        return None
    monsters = list(game_state.monsters()) if hasattr(game_state, "monsters") else []
    ent = str(config.external_target_ent or "").strip().lower()
    if ent:
        for obj in monsters:
            got = str(getattr(obj, "memory_ent", None) or "").strip().lower()
            if got and got == ent:
                return obj
    tid = config.external_target_id
    if tid is not None:
        for obj in monsters:
            if int(getattr(obj, "track_id", -1) or -1) == int(tid):
                return obj
        get = getattr(game_state, "get_object", None)
        if callable(get):
            obj = get(int(tid))
            if obj is not None and str(getattr(getattr(obj, "object_type", None), "value", "")).lower() in (
                "monster",
                "",
            ):
                # Prefer monsters(); accept get_object if it looks alive.
                if getattr(obj, "object_type", None) is not None:
                    from app._02_state.objects import ObjectType

                    if getattr(obj, "object_type", None) is ObjectType.MONSTER:
                        return obj
    return None


def resolve_leader_strike_target(
    game_state: Any,
    leader: Any,
    *,
    origin: Any = None,
) -> Any:
    """Nearest monster whose AttackAction target guid is the leader.

    This is the best local proxy for 'leader is fighting that mob' when the
    game does not expose the leader's selected target directly.
    """
    if game_state is None or leader is None:
        return None
    wanted: set[int] = set()
    ally = guid_key(getattr(leader, "memory_guid", None))
    if ally is not None:
        wanted.add(ally)
    snap = getattr(game_state, "last_attacks_me", None)
    rows: list[Any] = []
    if isinstance(snap, dict):
        rows = list(snap.get("strikes") or [])
        if not rows:
            rows = list(snap.get("attacks_me") or [])
    found: list[Any] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict) or not _strike_hits_guid(row, wanted):
            continue
        obj = _monster_for_strike(game_state, row)
        if obj is None:
            continue
        tid = int(getattr(obj, "track_id", 0) or 0)
        if tid in seen:
            continue
        seen.add(tid)
        found.append(obj)
    if not found:
        return None

    def dist_key(obj: Any) -> tuple[int, int]:
        try:
            from app._03_world.space.world_coords import tile_chebyshev
            from app._04_decision.combat_query import object_absolute_tile

            if origin is None:
                return (0, int(getattr(obj, "track_id", 0) or 0))
            tile = object_absolute_tile(obj, origin)
            d = tile_chebyshev(
                int(origin.x), int(origin.y), int(tile[0]), int(tile[1])
            )
            return (d, int(getattr(obj, "track_id", 0) or 0))
        except Exception:
            return (999, int(getattr(obj, "track_id", 0) or 0))

    return min(found, key=dist_key)


def resolve_self_defender(game_state: Any, *, origin: Any = None) -> Any:
    """Monster currently attacking the local player (optional self-defense)."""
    if game_state is None:
        return None
    try:
        from app._04_decision.combat_query import nearest_attacks_me_force

        return nearest_attacks_me_force(
            game_state, origin=origin, check_path=True
        )
    except Exception:
        return None


def pick_assist_target(
    game_state: Any,
    leader: Any,
    config: PartyMemberConfig,
    *,
    origin: Any = None,
) -> tuple[Optional[Any], str]:
    """Return (monster, source) for ASSIST; source is external|leader_strike|none."""
    ext = resolve_external_target(game_state, config)
    if ext is not None:
        return ext, "external"
    if config.assist_leader_strikes:
        hit = resolve_leader_strike_target(game_state, leader, origin=origin)
        if hit is not None:
            return hit, "leader_strike"
    return None, "none"


__all__ = [
    "pick_assist_target",
    "resolve_external_target",
    "resolve_leader_strike_target",
    "resolve_self_defender",
]
