"""Resolve the monster the member should help kill (leader's fight).

Mirrors etview AttackAction monitoring: player hasAtk → owner/tgt.
``last_contested_mobs`` is the same ActionComponent read (attacker → monster).
"""
from __future__ import annotations

from typing import Any, Optional

from .config import PartyMemberConfig
from .follow import guid_key
from .leader import player_name

_STRIKE_CLASSES = frozenset({"Monster", "SummonedMonster"})
# Party-assist synthetics — sit above attacks_me force band (0x70000000).
_ASSIST_TRACK_BASE = 0x71000000


def _strike_hits_guid(row: object, wanted: set[int]) -> bool:
    if not isinstance(row, dict) or not wanted:
        return False
    if str(row.get("class") or "") not in _STRIKE_CLASSES:
        return False
    key = guid_key(row.get("tgt"))
    return key is not None and key in wanted


def _norm_ent(value: object) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    return text


def _name_fold(value: object) -> str:
    return "".join(str(value or "").split()).lower()


def _names_close(a: object, b: object) -> bool:
    x, y = _name_fold(a), _name_fold(b)
    if not x or not y:
        return False
    return x == y or x.startswith(y) or y.startswith(x)


def _row_world(row: dict[str, Any]) -> Optional[tuple[int, int]]:
    world = row.get("world") if isinstance(row.get("world"), dict) else None
    if not isinstance(world, dict):
        return None
    try:
        return int(world["cx"]), int(world["cy"])
    except (KeyError, TypeError, ValueError):
        return None


def _assist_track_id(key: str) -> int:
    text = _norm_ent(key) or str(key or "assist")
    try:
        n = int(text, 16)
    except ValueError:
        n = abs(hash(text)) & 0x0FFFFFFF
    tid = _ASSIST_TRACK_BASE | (n & 0x0FFFFFFF)
    if tid == 0 or tid == _ASSIST_TRACK_BASE:
        tid = _ASSIST_TRACK_BASE | 1
    return int(tid)


def _assist_target_live(game_state: Any, obj: Any) -> bool:
    """True when the monster is a real local entity safe to ATTACK/skill."""
    if obj is None:
        return False
    tid = int(getattr(obj, "track_id", 0) or 0)
    if tid <= 0 or tid >= _ASSIST_TRACK_BASE:
        return False
    try:
        from app._04_decision.combat_query import memory_target_gone

        if memory_target_gone(game_state, obj):
            return False
    except Exception:
        pass
    return True


def _monster_for_row(game_state: Any, row: dict[str, Any]) -> Any:
    """Map a contested/strike row onto a local monster WorldObject."""
    monsters = list(game_state.monsters()) if hasattr(game_state, "monsters") else []
    want_ent = _norm_ent(row.get("ent"))
    if want_ent:
        for obj in monsters:
            got = _norm_ent(getattr(obj, "memory_ent", None))
            if got and got == want_ent:
                return obj
    mob_guid = guid_key(row.get("guid") or row.get("tgt"))
    if mob_guid is not None:
        for obj in monsters:
            got = guid_key(getattr(obj, "memory_guid", None))
            if got is not None and got == mob_guid:
                return obj
    cell = _row_world(row)
    want_name = str(row.get("name") or "").strip()
    if cell is not None:
        cx, cy = cell
        matches: list[Any] = []
        for obj in monsters:
            if getattr(obj, "world_cx", None) is None or getattr(obj, "world_cy", None) is None:
                continue
            try:
                ox, oy = int(obj.world_cx), int(obj.world_cy)
            except (TypeError, ValueError):
                continue
            dist = max(abs(ox - cx), abs(oy - cy))
            if dist > 1:
                continue
            if want_name:
                label = (
                    getattr(obj, "species_name", None)
                    or getattr(getattr(obj, "identity", None), "name", None)
                    or getattr(obj, "label", None)
                )
                if not _names_close(label, want_name):
                    continue
            matches.append((dist, obj))
        if matches:
            matches.sort(key=lambda t: (t[0], int(getattr(t[1], "track_id", 0) or 0)))
            return matches[0][1]
        # Exact cell without name (legacy path).
        exact = [
            obj
            for obj in monsters
            if getattr(obj, "world_cx", None) is not None
            and getattr(obj, "world_cy", None) is not None
            and int(obj.world_cx) == cx
            and int(obj.world_cy) == cy
        ]
        if exact:
            return min(exact, key=lambda o: int(getattr(o, "track_id", 0) or 0))
    if want_name:
        named = [
            obj
            for obj in monsters
            if _names_close(
                getattr(obj, "species_name", None)
                or getattr(getattr(obj, "identity", None), "name", None),
                want_name,
            )
        ]
        if len(named) == 1:
            return named[0]
    return None


def _materialize_from_row(game_state: Any, row: dict[str, Any]) -> Any:
    """Upsert an assist-only WorldObject from a contested row (etview tgt).

    print_state drops off-screen monsters, so contested can know the leader's
    target while ``monsters()`` does not. Materialize so ATTACK has a track_id.
    """
    upsert = getattr(game_state, "upsert_object", None)
    if not callable(upsert):
        return None
    cell = _row_world(row)
    if cell is None:
        return None
    ent = str(row.get("ent") or "").strip()
    guid = str(row.get("guid") or row.get("tgt") or "").strip()
    name = str(row.get("name") or "assist").strip() or "assist"
    key = ent or guid or f"{cell[0]},{cell[1]}"
    tid = _assist_track_id(key)
    existing = None
    get = getattr(game_state, "get_object", None)
    if callable(get):
        existing = get(tid)
    try:
        from app._02_state.objects import (
            Identity,
            ObjectStatus,
            ObjectType,
            Position,
            Relationship,
            WorldObject,
        )
    except Exception:
        return None

    px = py = None
    player = getattr(game_state, "player", None)
    snap = getattr(game_state, "last_print_state", None)
    if isinstance(snap, dict):
        p = snap.get("player") if isinstance(snap.get("player"), dict) else {}
        try:
            px, py = int(p["x"]), int(p["y"])
        except (KeyError, TypeError, ValueError):
            px = py = None
    if px is None and player is not None:
        try:
            px = int(getattr(player, "world_x", None) or getattr(player, "x"))
            py = int(getattr(player, "world_y", None) or getattr(player, "y"))
        except (TypeError, ValueError):
            px = py = None
    rx = cell[0] - int(px) if px is not None else 0
    ry = cell[1] - int(py) if py is not None else 0
    try:
        from app._03_world.space.world_coords import world_to_content

        content = world_to_content(float(rx), float(ry))
        pos_x, pos_y = float(content.x), float(content.y)
    except Exception:
        # Action uses world_cx/cy; screen pose is best-effort (tests lack numpy).
        pos_x = max(0.05, min(0.95, 0.5 + float(rx) * 0.02))
        pos_y = max(0.05, min(0.95, 0.5 + float(ry) * 0.02))
    if existing is not None:
        existing.object_type = ObjectType.MONSTER
        existing.status = ObjectStatus.ALIVE
        existing.position = Position(x=pos_x, y=pos_y)
        existing.world_cx = cell[0]
        existing.world_cy = cell[1]
        existing.world_rx = rx
        existing.world_ry = ry
        existing.species_name = name
        existing.label = name
        existing.memory_ent = ent or getattr(existing, "memory_ent", None)
        existing.memory_guid = guid or getattr(existing, "memory_guid", None)
        upsert(existing)
        return existing
    obj = WorldObject(
        track_id=tid,
        object_type=ObjectType.MONSTER,
        identity=Identity(name=name, confidence=1.0),
        position=Position(x=pos_x, y=pos_y),
        status=ObjectStatus.ALIVE,
        relationship=Relationship.ENEMY,
        label=name,
        species_name=name,
        species_confidence=1.0,
        world_cx=cell[0],
        world_cy=cell[1],
        world_rx=rx,
        world_ry=ry,
        memory_ent=ent or None,
        memory_guid=guid or None,
    )
    upsert(obj)
    return obj


# Back-compat alias used by older unit tests / callers.
_monster_for_strike = _monster_for_row


def _nearest_monster(origin: Any, found: list[Any]) -> Any:
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


def _leader_identity(leader: Any) -> tuple[set[int], set[str]]:
    guids: set[int] = set()
    names: set[str] = set()
    g = guid_key(getattr(leader, "memory_guid", None))
    if g is not None:
        guids.add(g)
    name = player_name(leader).strip().lower()
    if name:
        names.add(name)
    return guids, names


def _row_matches_leader(row: dict[str, Any], guids: set[int], names: set[str]) -> bool:
    attacker = guid_key(row.get("attacker_guid"))
    if attacker is None:
        attacker = guid_key(row.get("owner"))
    attacker_name = str(row.get("attacker_name") or "").strip().lower()
    by_guid = attacker is not None and attacker in guids
    by_name = bool(attacker_name) and attacker_name in names
    return by_guid or by_name


def _print_entities(game_state: Any) -> list[dict[str, Any]]:
    snap = getattr(game_state, "last_print_state", None)
    if not isinstance(snap, dict):
        return []
    raw = snap.get("entities")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _leader_attack_rows_from_print(
    game_state: Any,
    leader: Any,
) -> list[dict[str, Any]]:
    """Leader's AttackAction from print_state Player ``atk`` / ``tgt``.

    Fallback when contested_mobs is empty (leader off contested sweep). Needs
    both the leader Player row and the monster guid in the print roster.
    """
    guids, names = _leader_identity(leader)
    if not guids and not names:
        return []
    entities = _print_entities(game_state)
    if not entities:
        return []
    monsters_by_guid: dict[int, dict[str, Any]] = {}
    for row in entities:
        if str(row.get("class") or "") != "Monster":
            continue
        key = guid_key(row.get("guid"))
        if key is not None:
            monsters_by_guid[key] = row
    out: list[dict[str, Any]] = []
    for row in entities:
        if str(row.get("class") or "") != "Player":
            continue
        if row.get("atk") not in (1, True):
            continue
        attacker = guid_key(row.get("guid"))
        attacker_name = str(row.get("name") or "").strip().lower()
        by_guid = attacker is not None and attacker in guids
        by_name = bool(attacker_name) and attacker_name in names
        if not (by_guid or by_name):
            continue
        tgt = guid_key(row.get("tgt"))
        if tgt is None:
            continue
        mon = monsters_by_guid.get(tgt)
        if mon is None:
            continue
        world = mon.get("world") if isinstance(mon.get("world"), dict) else None
        out.append(
            {
                "name": str(mon.get("name") or "").strip(),
                "guid": str(mon.get("guid") or "").strip(),
                "ent": str(mon.get("ent") or "").strip(),
                "tgt": str(mon.get("guid") or "").strip(),
                "world": world,
                "attacker_guid": str(row.get("guid") or "").strip(),
                "attacker_name": str(row.get("name") or "").strip(),
                "owner": str(row.get("guid") or "").strip(),
            }
        )
    return out


def leader_attack_rows(
    game_state: Any,
    leader: Any,
) -> list[dict[str, Any]]:
    """Rows where the party leader owns the AttackAction (etview contested first)."""
    if game_state is None or leader is None:
        return []
    guids, names = _leader_identity(leader)
    if not guids and not names:
        return []
    # Same source as etview AttackAction monitoring (contested_mobs.dll).
    snap = getattr(game_state, "last_contested_mobs", None)
    if isinstance(snap, dict):
        out: list[dict[str, Any]] = []
        for row in snap.get("contested") or []:
            if isinstance(row, dict) and _row_matches_leader(row, guids, names):
                out.append(row)
        if out:
            return out
    return _leader_attack_rows_from_print(game_state, leader)


def describe_leader_target(
    game_state: Any,
    leader: Any,
) -> Optional[dict[str, Any]]:
    """etview-style leader target summary for UI / farming banner.

    ``{name, guid, ent, world_cx, world_cy, attacker_name}`` or None.
    """
    rows = leader_attack_rows(game_state, leader)
    if not rows:
        return None
    row = rows[0]
    cell = _row_world(row)
    return {
        "name": str(row.get("name") or "").strip(),
        "guid": str(row.get("guid") or row.get("tgt") or "").strip(),
        "ent": str(row.get("ent") or "").strip(),
        "world_cx": cell[0] if cell else None,
        "world_cy": cell[1] if cell else None,
        "attacker_name": str(row.get("attacker_name") or "").strip(),
        "attacker_guid": str(row.get("attacker_guid") or row.get("owner") or "").strip(),
    }


def resolve_external_target(game_state: Any, config: PartyMemberConfig) -> Any:
    """Operator / WS sticky target if still alive locally."""
    if game_state is None:
        return None
    monsters = list(game_state.monsters()) if hasattr(game_state, "monsters") else []
    ent = str(config.external_target_ent or "").strip().lower()
    if ent:
        want = _norm_ent(ent)
        for obj in monsters:
            got = _norm_ent(getattr(obj, "memory_ent", None))
            if got and got == want:
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
                if getattr(obj, "object_type", None) is not None:
                    from app._02_state.objects import ObjectType

                    if getattr(obj, "object_type", None) is ObjectType.MONSTER:
                        return obj
    return None


def resolve_leader_attack_target(
    game_state: Any,
    leader: Any,
    *,
    origin: Any = None,
) -> Any:
    """Monster the leader is currently attacking (contested_mobs / etview ATK).

    ``last_contested_mobs.contested[]`` rows are monsters targeted by another
    visible player's AttackAction. Match ``attacker_guid`` / ``attacker_name``
    to the party leader, then resolve that monster locally — materializing a
    synthetic WorldObject when print_state omitted an off-screen mob.
    """
    if game_state is None or leader is None:
        return None
    found: list[Any] = []
    seen: set[int] = set()
    for row in leader_attack_rows(game_state, leader):
        # Live local monster only — synthetics have no screen sprite, so mage
        # skill-press + aim search thrashes the cursor with no target.
        obj = _monster_for_row(game_state, row)
        if obj is None:
            continue
        if not _assist_target_live(game_state, obj):
            continue
        tid = int(getattr(obj, "track_id", 0) or 0)
        if tid in seen:
            continue
        seen.add(tid)
        found.append(obj)
    return _nearest_monster(origin, found)


def resolve_leader_strike_target(
    game_state: Any,
    leader: Any,
    *,
    origin: Any = None,
) -> Any:
    """Nearest monster whose AttackAction target guid is the leader.

    Secondary assist path: mobs currently hitting the leader. Prefer
    :func:`resolve_leader_attack_target` for 'what the leader is attacking'.
    Uses print_state ``atk``/``tgt`` (live); legacy attacks_me DLL as fallback.
    """
    if game_state is None or leader is None:
        return None
    wanted: set[int] = set()
    ally = guid_key(getattr(leader, "memory_guid", None))
    if ally is not None:
        wanted.add(ally)
    found: list[Any] = []
    seen: set[int] = set()

    # Live: monster/summon rows whose tgt is the leader.
    for row in _print_entities(game_state):
        cls = str(row.get("class") or "")
        if cls not in _STRIKE_CLASSES:
            continue
        if row.get("atk") not in (1, True):
            continue
        if guid_key(row.get("tgt")) not in wanted:
            continue
        obj = _monster_for_row(game_state, row)
        if obj is None or not _assist_target_live(game_state, obj):
            continue
        tid = int(getattr(obj, "track_id", 0) or 0)
        if tid in seen:
            continue
        seen.add(tid)
        found.append(obj)
    if found:
        return _nearest_monster(origin, found)

    snap = getattr(game_state, "last_attacks_me", None)
    rows: list[Any] = []
    if isinstance(snap, dict):
        rows = list(snap.get("strikes") or [])
        if not rows:
            rows = list(snap.get("attacks_me") or [])
    for row in rows:
        if not isinstance(row, dict) or not _strike_hits_guid(row, wanted):
            continue
        obj = _monster_for_row(game_state, row)
        if obj is None or not _assist_target_live(game_state, obj):
            continue
        tid = int(getattr(obj, "track_id", 0) or 0)
        if tid in seen:
            continue
        seen.add(tid)
        found.append(obj)
    return _nearest_monster(origin, found)


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


def _assist_excluded_ids(blackboard: Any) -> set[int]:
    if blackboard is None:
        return set()
    try:
        from app._04_decision.attack_feedback import excluded_target_ids

        return set(excluded_target_ids(blackboard))
    except Exception:
        return set()


def pick_assist_target(
    game_state: Any,
    leader: Any,
    config: PartyMemberConfig,
    *,
    origin: Any = None,
    blackboard: Any = None,
) -> tuple[Optional[Any], str]:
    """Return (monster, source): external|leader_attack|leader_strike|none.

    Skips soft give-up / blacklist ids so a failed mage cast can retarget.
    """
    skip = _assist_excluded_ids(blackboard)

    def ok(obj: Any) -> bool:
        if obj is None or not _assist_target_live(game_state, obj):
            return False
        tid = int(getattr(obj, "track_id", 0) or 0)
        return tid > 0 and tid not in skip

    ext = resolve_external_target(game_state, config)
    if ok(ext):
        return ext, "external"
    if config.assist_leader_strikes:
        # Prefer what the leader is attacking (contested / etview ATK).
        attack = resolve_leader_attack_target(game_state, leader, origin=origin)
        if ok(attack):
            return attack, "leader_attack"
        hit = resolve_leader_strike_target(game_state, leader, origin=origin)
        if ok(hit):
            return hit, "leader_strike"
    return None, "none"


def pick_solo_farm_target(
    game_state: Any,
    *,
    origin: Any,
    leader_tile: Optional[tuple[int, int]],
    leash_tiles: int,
    previous_id: Optional[int] = None,
    blackboard: Any = None,
) -> Optional[Any]:
    """Own target for solo-farm members: nearest attackable near the leader.

    Same gates as the solo bot (species allow/deny, contested by another
    player, line of attack, mage range). Monsters farther than
    ``leash_tiles`` from the leader are skipped so farming never drags the
    member away. The current target is kept while it is still alive in range.
    """
    if game_state is None or origin is None or leader_tile is None:
        return None
    from app._02_state.objects import ObjectType
    from app._03_world.space.world_coords import tile_chebyshev
    from app._04_decision.combat_query import (
        list_attackable,
        object_absolute_tile,
        tile_distance_from_player,
    )

    lx, ly = int(leader_tile[0]), int(leader_tile[1])
    leash = max(1, int(leash_tiles))

    def near_leader(obj: Any) -> bool:
        try:
            tx, ty = object_absolute_tile(obj, origin)
            return tile_chebyshev(int(tx), int(ty), lx, ly) <= leash
        except Exception:
            return False

    skip: set[int] = set()
    if blackboard is not None:
        try:
            from app._04_decision.attack_feedback import excluded_target_ids

            skip = set(excluded_target_ids(blackboard))
        except Exception:
            skip = set()

    if previous_id is not None and int(previous_id) not in skip:
        obj = game_state.get_object(int(previous_id))
        if (
            obj is not None
            and getattr(obj, "object_type", None) is ObjectType.MONSTER
            and _assist_target_live(game_state, obj)
            and near_leader(obj)
        ):
            try:
                from app._04_decision.species_rules import is_avoided_for_state

                if not is_avoided_for_state(game_state, obj):
                    return obj
            except Exception:
                return obj

    try:
        cands = list_attackable(
            game_state, exclude=skip, origin=origin, screen_only=True
        )
    except Exception:
        return None
    cands = [o for o in cands if _assist_target_live(game_state, o) and near_leader(o)]
    if not cands:
        return None
    return min(
        cands,
        key=lambda o: (tile_distance_from_player(o), int(getattr(o, "track_id", 0))),
    )


def assist_in_attack_range(game_state: Any, obj: Any) -> bool:
    """True when the member can cast/click the monster from here.

    Spell mages use mage spell range. Bow/melee (attack_mode ranged/melee, or
    non-mage) use a short engage distance; the click strategies own fine aim.
    """
    if obj is None or not _assist_target_live(game_state, obj):
        return False
    spell_aim = True
    try:
        from app._04_decision import player_mode as pm

        spell_aim = bool(getattr(pm, "uses_spell_aim", lambda: True)())
    except Exception:
        spell_aim = True
    if spell_aim:
        try:
            pos = getattr(obj, "position", None)
            if pos is not None:
                from app._03_world.space.world_coords import in_mage_spell_range

                if in_mage_spell_range(float(pos.x), float(pos.y)):
                    return True
        except Exception:
            pass
    try:
        from app._04_decision.combat_query import tile_distance_from_player

        d = tile_distance_from_player(obj)
        # Bow/melee: within attack click tiles (default ~6–8); mage fallback 2.
        limit = 6 if not spell_aim else 2
        try:
            from app._04_decision import player_mode as pm

            limit = int(getattr(pm, "ATTACK_CLICK_TILES", limit) or limit)
        except Exception:
            pass
        if d is not None and int(d) <= max(2, limit):
            return True
    except Exception:
        pass
    return False


def assist_monster_tile(obj: Any, origin: Any) -> Optional[tuple[int, int]]:
    """Nav tile of an assist monster for close-in hops."""
    if obj is None:
        return None
    try:
        from app._04_decision.combat_query import object_absolute_tile

        tile = object_absolute_tile(obj, origin)
        return int(tile[0]), int(tile[1])
    except Exception:
        pass
    try:
        cx = getattr(obj, "world_cx", None)
        cy = getattr(obj, "world_cy", None)
        if cx is not None and cy is not None:
            return int(cx), int(cy)
    except (TypeError, ValueError):
        pass
    return None


__all__ = [
    "assist_in_attack_range",
    "assist_monster_tile",
    "describe_leader_target",
    "leader_attack_rows",
    "pick_assist_target",
    "pick_solo_farm_target",
    "resolve_external_target",
    "resolve_leader_attack_target",
    "resolve_leader_strike_target",
    "resolve_self_defender",
]
