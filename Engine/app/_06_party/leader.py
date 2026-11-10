"""Resolve the party leader from memory (and optional nearby entity)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .config import PartyMemberConfig
from .follow import guid_key


def player_key(obj: Any) -> str:
    ent = str(getattr(obj, "memory_ent", None) or "").strip()
    if ent:
        return ent
    return f"tid:{int(getattr(obj, 'track_id', 0) or 0)}"


def player_name(obj: Any) -> str:
    identity = getattr(obj, "identity", None)
    name = str(getattr(identity, "name", None) or "").strip()
    if not name:
        name = str(getattr(obj, "species_name", None) or "").strip()
    return name


def player_guid(obj: Any) -> str:
    raw = getattr(obj, "memory_guid", None)
    if raw is None:
        return ""
    text = str(raw).strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    return text


def _names_match(seen: str, wanted: str) -> bool:
    a = str(seen or "").strip().lower()
    b = str(wanted or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _guids_match(seen: object, wanted: object) -> bool:
    a = guid_key(seen)
    b = guid_key(wanted)
    return a is not None and b is not None and a == b


def party_member_block(
    snapshot: Optional[dict[str, Any]],
    wanted_name: str = "",
) -> Optional[dict[str, Any]]:
    """Leader (or named member) row from ``last_party``, or None.

    Empty ``wanted_name`` → game party leader from the sensor.
    """
    if not isinstance(snapshot, dict):
        return None
    if not bool(snapshot.get("in_party")):
        return None
    wanted = str(wanted_name or "").strip()
    if wanted:
        for raw in snapshot.get("members") or []:
            if not isinstance(raw, dict):
                continue
            if _names_match(str(raw.get("name") or ""), wanted):
                return raw
        leader = snapshot.get("leader")
        if isinstance(leader, dict) and _names_match(
            str(leader.get("name") or ""), wanted
        ):
            return leader
        return None

    leader = snapshot.get("leader")
    if isinstance(leader, dict) and str(leader.get("name") or "").strip():
        return leader
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict):
            continue
        if bool(raw.get("is_leader")) and str(raw.get("name") or "").strip():
            return raw
        return None


def stand_from_party_memory(
    snapshot: Optional[dict[str, Any]],
    name: str,
    hold_id: str,
) -> Optional[dict[str, Any]]:
    """Current party-memory tile for ``name``. The leader sends this with the hold."""
    row = party_member_block(snapshot, name)
    if not isinstance(row, dict) or not str(hold_id or "").strip():
        return None
    try:
        return {
            "id": str(hold_id),
            "for": str(name or "").strip(),
            "map_id": int(row["map_id"]),
            "x": int(row["x"]),
            "y": int(row["y"]),
        }
    except (TypeError, ValueError, KeyError):
        return None


def find_leader(
    game_state: Any,
    config: PartyMemberConfig,
    *,
    name_hint: str = "",
    guid_hint: str = "",
) -> Optional[Any]:
    """Find the leader WorldObject on the local player list.

    Sticky ent / guid / track_id work whether the leader is farming or idle —
    reacquire as soon as they reappear in the entity sweep.
    """
    if game_state is None:
        return None
    players = list(game_state.players()) if hasattr(game_state, "players") else []
    ent = str(config.leader_ent or "").strip()
    if ent:
        for obj in players:
            if player_key(obj) == ent:
                return obj
    guid = str(guid_hint or config.leader_guid or "").strip()
    if guid:
        for obj in players:
            if _guids_match(getattr(obj, "memory_guid", None), guid):
                return obj
            # Some sweeps put the hex guid into memory_ent.
            if _guids_match(getattr(obj, "memory_ent", None), guid):
                return obj
    tid = config.leader_track_id
    if tid is not None:
        for obj in players:
            if int(getattr(obj, "track_id", -1) or -1) == int(tid):
                return obj
    wanted = str(name_hint or config.leader_name or "").strip()
    if wanted:
        for obj in players:
            if _names_match(player_name(obj), wanted):
                return obj
    return None


def _party_game_xy(block: dict[str, Any]) -> Optional[tuple[int, int]]:
    """Raw PartySubsystem game coords (may be ~32k LC world)."""
    try:
        x = int(block.get("x"))
        y = int(block.get("y"))
    except (TypeError, ValueError):
        return None
    if x == 0 and y == 0:
        return None
    return (x, y)


def _party_tile(block: dict[str, Any]) -> Optional[tuple[int, int]]:
    """Party pose as nav.png tiles (same space as ``world_origin`` / follow A*)."""
    xy = _party_game_xy(block)
    if xy is None:
        return None
    try:
        from app._03_world.merge.memory_sync import game_to_nav

        return game_to_nav(int(xy[0]), int(xy[1]))
    except Exception:
        return xy


def _party_map_id(block: dict[str, Any]) -> Optional[int]:
    try:
        mid = int(block.get("map_id"))
    except (TypeError, ValueError):
        return None
    return mid


@dataclass
class LeaderView:
    """Leader pose for the member brain (entity optional)."""

    entity: Any = None
    name: str = ""
    tile: Optional[tuple[int, int]] = None
    map_id: Optional[int] = None
    hp: Optional[int] = None
    mp: Optional[int] = None
    guid: str = ""
    source: str = ""
    same_map: bool = True
    # Sticky ent/track for UI — filled even when entity is momentarily missing.
    ent: str = ""
    track_id: Optional[int] = None
    farming: bool = False
    # True only when ``tile`` came from this tick's memory read.
    fresh: bool = False
    # etview-style AttackAction target (contested row).
    target_name: str = ""
    target_guid: str = ""
    target_ent: str = ""

    @property
    def present(self) -> bool:
        return self.tile is not None and self.same_map


def resolve_leader(
    game_state: Any,
    config: PartyMemberConfig,
    *,
    origin: Any = None,
    local_map_id: Optional[int] = None,
) -> LeaderView:
    """Prefer party-memory leader pose; attach nearby entity when visible.

    PartySubsystem xy/mapId (``party_listen`` / realtime_party) is the follow
    tile even when an entity is listed — so the member can chase off-screen.
    Solo path never calls this. Assist still uses ``entity`` / contested sticky.
    """
    view = LeaderView()
    party_snap = getattr(game_state, "last_party", None) if game_state else None
    party = party_member_block(
        party_snap if isinstance(party_snap, dict) else None,
        str(config.leader_name or ""),
    )
    memory_name = ""
    memory_guid = ""
    if party is not None:
        memory_name = str(party.get("name") or "").strip()
        memory_guid = str(party.get("guid") or "").strip()

    entity = find_leader(
        game_state,
        config,
        name_hint=memory_name,
        guid_hint=memory_guid,
    )
    if entity is not None:
        view.entity = entity
        view.name = player_name(entity) or memory_name
        view.guid = player_guid(entity) or memory_guid
        view.ent = player_key(entity)
        tid = int(getattr(entity, "track_id", 0) or 0) or None
        view.track_id = tid
        view.source = "entity"
        if origin is not None and hasattr(origin, "x"):
            try:
                from app._04_decision.combat_query import object_absolute_tile

                view.tile = object_absolute_tile(entity, origin)
            except Exception:
                view.tile = None

    fresh_party = bool(
        game_state is not None and getattr(game_state, "party_read_ok", None) is True
    )
    if party is not None:
        view.name = memory_name or view.name
        view.guid = memory_guid or view.guid
        # Name and guid may come from the preserved row so the entity can be
        # matched. Map and xy are a pose only when this tick's read succeeded.
        if fresh_party:
            try:
                view.hp = int(party.get("hp"))
            except (TypeError, ValueError):
                view.hp = None
            try:
                view.mp = int(party.get("mp"))
            except (TypeError, ValueError):
                view.mp = None
            view.map_id = _party_map_id(party)
            party_tile = _party_tile(party)
            # PartySubsystem xy is the follow tile, including off-screen.
            # Entity remains for assist. Do not copy a preserved snapshot.
            if party_tile is not None:
                view.tile = party_tile
                view.source = "party" if view.entity is None else "entity+party"
            elif view.source == "entity":
                view.source = "entity+party"

    if not view.ent and config.leader_ent:
        view.ent = str(config.leader_ent)
    if view.track_id is None and config.leader_track_id is not None:
        view.track_id = int(config.leader_track_id)
    if not view.guid and config.leader_guid:
        view.guid = str(config.leader_guid)

    # Farming = leader AttackAction → monster (etview ATK / contested).
    _fill_leader_target(game_state, view, config)

    if (
        local_map_id is not None
        and view.map_id is not None
        and int(local_map_id) != int(view.map_id)
    ):
        # Never chase PartySubsystem coords across maps.
        view.same_map = False
        view.tile = None

    view.fresh = bool(view.tile is not None and view.same_map)
    return view


def _fill_leader_target(
    game_state: Any,
    view: LeaderView,
    config: PartyMemberConfig,
) -> None:
    """Set farming + etview-style target identity from contested AttackAction."""
    view.farming = False
    view.target_name = ""
    view.target_guid = ""
    view.target_ent = ""
    if game_state is None:
        return
    from .assist import describe_leader_target
    from types import SimpleNamespace

    proxy = SimpleNamespace(
        memory_guid=view.guid or config.leader_guid,
        identity=SimpleNamespace(name=view.name or config.leader_name),
        species_name=view.name or config.leader_name,
    )
    info = describe_leader_target(game_state, proxy)
    if not info:
        return
    view.farming = True
    view.target_name = str(info.get("name") or "")
    view.target_guid = str(info.get("guid") or "")
    view.target_ent = str(info.get("ent") or "")


def bind_leader_identity(config: PartyMemberConfig, leader: Any) -> PartyMemberConfig:
    """Remember ent/guid/track_id once resolved (stable reacquire)."""
    from dataclasses import replace

    if leader is None:
        return config
    ent = player_key(leader)
    guid = player_guid(leader) or config.leader_guid
    tid = int(getattr(leader, "track_id", 0) or 0) or None
    name = player_name(leader) or config.leader_name
    if (
        config.leader_ent == ent
        and config.leader_guid == guid
        and config.leader_track_id == tid
        and (not name or config.leader_name == name)
    ):
        return config
    return replace(
        config,
        leader_name=name or config.leader_name,
        leader_ent=ent or config.leader_ent,
        leader_guid=guid or config.leader_guid,
        leader_track_id=tid if tid is not None else config.leader_track_id,
    ).clamped()


def bind_leader_from_party(
    config: PartyMemberConfig,
    party_block: Optional[dict[str, Any]],
) -> PartyMemberConfig:
    """Sticky name/guid from party_listen even when the entity is off-screen."""
    from dataclasses import replace

    if not isinstance(party_block, dict):
        return config
    name = str(party_block.get("name") or "").strip() or config.leader_name
    guid = str(party_block.get("guid") or "").strip() or config.leader_guid
    if config.leader_name == name and config.leader_guid == guid:
        return config
    return replace(
        config,
        leader_name=name,
        leader_guid=guid,
    ).clamped()


def leader_proxy_for_assist(
    entity: Any,
    config: PartyMemberConfig,
    view: LeaderView,
) -> Any:
    """Entity when visible; otherwise a guid/name stub for contested matching."""
    if entity is not None:
        return entity
    from types import SimpleNamespace

    guid = view.guid or config.leader_guid
    name = view.name or config.leader_name
    ent = view.ent or config.leader_ent
    tid = view.track_id if view.track_id is not None else config.leader_track_id
    return SimpleNamespace(
        memory_guid=guid,
        memory_ent=ent,
        track_id=int(tid or 0),
        identity=SimpleNamespace(name=name),
        species_name=name,
    )


__all__ = [
    "LeaderView",
    "bind_leader_from_party",
    "bind_leader_identity",
    "find_leader",
    "leader_proxy_for_assist",
    "party_member_block",
    "player_guid",
    "player_key",
    "player_name",
    "resolve_leader",
]
