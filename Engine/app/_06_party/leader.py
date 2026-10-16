"""Resolve the selected leader among nearby players."""
from __future__ import annotations

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
    "bind_leader_identity",
    "find_leader",
    "player_key",
    "player_name",
]
