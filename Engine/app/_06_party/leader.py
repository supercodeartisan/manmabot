"""Resolve the selected leader: nearby entity and/or party memory stats."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .config import PartyMemberConfig


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


def _names_match(seen: str, wanted: str) -> bool:
    a = str(seen or "").strip().lower()
    b = str(wanted or "").strip().lower()
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def find_leader(game_state: Any, config: PartyMemberConfig) -> Optional[Any]:
    """Find the leader WorldObject on the local player list."""
    if game_state is None:
        return None
    players = list(game_state.players()) if hasattr(game_state, "players") else []
    ent = str(config.leader_ent or "").strip()
    if ent:
        for obj in players:
            if player_key(obj) == ent:
                return obj
    tid = config.leader_track_id
    if tid is not None:
        for obj in players:
            if int(getattr(obj, "track_id", -1) or -1) == int(tid):
                return obj
    wanted = str(config.leader_name or "").strip()
    if wanted:
        for obj in players:
            if _names_match(player_name(obj), wanted):
                return obj
    return None


def party_member_block(
    snapshot: Optional[dict[str, Any]],
    wanted_name: str,
) -> Optional[dict[str, Any]]:
    """Configured leader row from ``last_party``, or None."""
    if not isinstance(snapshot, dict):
        return None
    if not bool(snapshot.get("in_party")):
        return None
    wanted = str(wanted_name or "").strip()
    if not wanted:
        return None
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict):
            continue
        if _names_match(str(raw.get("name") or ""), wanted):
            return raw
    leader = snapshot.get("leader")
    if isinstance(leader, dict) and _names_match(str(leader.get("name") or ""), wanted):
        return leader
    return None


def _party_tile(block: dict[str, Any]) -> Optional[tuple[int, int]]:
    try:
        x = int(block.get("x"))
        y = int(block.get("y"))
    except (TypeError, ValueError):
        return None
    # Absolute cells from PartyPlayer; reject empty / sentinel zeros.
    if x == 0 and y == 0:
        return None
    return (x, y)


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
    """Prefer nearby entity; fall back to party-memory coords for follow.

    Solo path never calls this. Assist still needs ``entity`` when present.
    """
    view = LeaderView()
    wanted = str(config.leader_name or "").strip()
    party_snap = getattr(game_state, "last_party", None) if game_state else None
    party = party_member_block(party_snap if isinstance(party_snap, dict) else None, wanted)

    entity = find_leader(game_state, config)
    if entity is not None:
        view.entity = entity
        view.name = player_name(entity) or wanted
        view.source = "entity"
        if origin is not None and hasattr(origin, "x"):
            try:
                from app._04_decision.combat_query import object_absolute_tile

                view.tile = object_absolute_tile(entity, origin)
            except Exception:
                view.tile = None

    if party is not None:
        view.name = str(party.get("name") or view.name or wanted).strip()
        view.guid = str(party.get("guid") or "")
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
        if view.tile is None and party_tile is not None:
            view.tile = party_tile
            view.source = "party" if not view.source else "entity+party"
        elif view.tile is not None and party_tile is not None:
            view.source = "entity+party"
        elif view.source == "entity" and party is not None:
            view.source = "entity+party"

    if not view.name:
        view.name = wanted

    if (
        local_map_id is not None
        and view.map_id is not None
        and int(local_map_id) != int(view.map_id)
    ):
        view.same_map = False
        # Different map: do not follow stale party coords.
        if view.source.startswith("party") or view.entity is None:
            view.tile = None

    return view


def bind_leader_identity(config: PartyMemberConfig, leader: Any) -> PartyMemberConfig:
    """Remember ent/track_id once resolved by name (stable reacquire)."""
    if leader is None:
        return config
    ent = player_key(leader)
    tid = int(getattr(leader, "track_id", 0) or 0) or None
    name = player_name(leader) or config.leader_name
    if config.leader_ent == ent and config.leader_track_id == tid:
        return config
    return PartyMemberConfig(
        enabled=config.enabled,
        leader_name=name or config.leader_name,
        leader_ent=ent or config.leader_ent,
        leader_track_id=tid if tid is not None else config.leader_track_id,
        follow_start_tiles=config.follow_start_tiles,
        follow_stop_tiles=config.follow_stop_tiles,
        approach_tiles=config.approach_tiles,
        assist_leash_tiles=config.assist_leash_tiles,
        potion_hp_ratio=config.potion_hp_ratio,
        use_hp_potion=config.use_hp_potion,
        defend_self=config.defend_self,
        assist_leader_strikes=config.assist_leader_strikes,
        external_target_id=config.external_target_id,
        external_target_ent=config.external_target_ent,
    ).clamped()


__all__ = [
    "LeaderView",
    "bind_leader_identity",
    "find_leader",
    "party_member_block",
    "player_key",
    "player_name",
    "resolve_leader",
]
