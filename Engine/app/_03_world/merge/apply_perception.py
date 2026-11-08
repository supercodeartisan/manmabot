"""Apply a :class:`PerceptionBuffer` into ``GameState`` / ``_02_state`` types.

Perception owns the buffer. World merge is the only place that turns those
raw snapshots into ``PlayerState``, ``WorldObject`` rows, bag counts, hotbar.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app._01_perception.buffer import PerceptionBuffer
    from app._02_state.gamestate import GameState
    from app._04_decision.blackboard import Blackboard

_TRACK_IDS = None
_SPECIES_TABLE: Optional[dict[int, dict[str, Any]]] = None
_SPECIES_ALIASES: Optional[dict[str, str]] = None


def _entity_maps():
    """Stable track ids + species tables across ticks (world-side, not buffer)."""
    global _TRACK_IDS, _SPECIES_TABLE, _SPECIES_ALIASES
    from app._03_world.merge.memory_entities import (
        TrackIds,
        load_species_aliases,
        load_species_ids,
    )

    if _TRACK_IDS is None:
        _TRACK_IDS = TrackIds()
    if _SPECIES_TABLE is None:
        _SPECIES_TABLE = load_species_ids()
    if _SPECIES_ALIASES is None:
        _SPECIES_ALIASES = load_species_aliases()
    return _TRACK_IDS, _SPECIES_TABLE, _SPECIES_ALIASES


@dataclass
class PerceptionApplyResult:
    entity_rows: list[dict[str, Any]] = field(default_factory=list)
    live_map_id: Optional[int] = None
    live_map_snap: Optional[dict[str, Any]] = None
    origin_ready: bool = False
    map_id_ready: bool = False
    inventory_changed: bool = False


def apply_perception_buffer(
    world: "GameState",
    blackboard: Optional["Blackboard"],
    buffer: "PerceptionBuffer",
    *,
    content: Any = None,
    previous_inventory: Optional[dict[str, Any]] = None,
) -> PerceptionApplyResult:
    """Copy perception buffer fields into ``world`` / ``blackboard``."""
    from app._03_world.merge.memory_entities import align_memory_rows, entities_to_handoff
    from app._03_world.merge.memory_sync import (
        apply_print_state_vitals,
        apply_snapshot,
        apply_buff_snapshot,
        player_map_id_from_snapshot,
        world_origin_from_snapshot,
    )

    result = PerceptionApplyResult()
    world.last_perception_buffer = buffer

    if buffer.player_ok and isinstance(buffer.player, dict):
        if apply_snapshot(world, blackboard, buffer.player):
            mid = player_map_id_from_snapshot(buffer.player)
            if mid is not None:
                result.map_id_ready = True
                result.live_map_id = int(mid)
                result.live_map_snap = buffer.player
                from app._03_world.merge.track import note_attacked_me_map

                note_attacked_me_map(world, int(mid))
            if world_origin_from_snapshot(buffer.player) is not None:
                result.origin_ready = True

    world.last_attacks_me = buffer.attacks_me
    world.last_contested_mobs = buffer.contested_mobs

    if buffer.print_state_ok and isinstance(buffer.print_state, dict):
        world.last_print_state = buffer.print_state
        apply_print_state_vitals(world, buffer.print_state)
        print_origin = world_origin_from_snapshot(buffer.print_state)
        if print_origin is not None and blackboard is not None:
            blackboard.world_origin = print_origin
            result.origin_ready = True
        if isinstance(buffer.print_state.get("player"), dict):
            result.live_map_snap = buffer.print_state
        tracks, species, aliases = _entity_maps()
        rows = entities_to_handoff(
            buffer.print_state,
            id_map=tracks,
            species=species,
            aliases=aliases,
        )
        rows = align_memory_rows(rows, buffer.print_state, content)
        result.entity_rows = rows
        world.last_print_entities = list(rows)
        from app._03_world.merge.track import apply_entity_handoff

        apply_entity_handoff(world, rows)
    else:
        world.last_print_state = None
        world.last_print_entities = []
        from app._03_world.merge.track import apply_entity_handoff

        apply_entity_handoff(world, [])

    if buffer.inventory_ok and isinstance(buffer.inventory, dict):
        if buffer.inventory is not previous_inventory:
            from app._03_world.merge.memory_inventory import (
                apply_inventory_snapshot,
                refresh_shop_needs_from_inventory,
            )

            apply_inventory_snapshot(world, buffer.inventory)
            if blackboard is not None:
                refresh_shop_needs_from_inventory(world, blackboard)
            result.inventory_changed = True

    if buffer.hotbar_ok and isinstance(buffer.hotbar, dict):
        world.last_hotbar = buffer.hotbar

    if buffer.buff_ok and isinstance(buffer.buff, dict):
        apply_buff_snapshot(world, buffer.buff)

    if buffer.uidialog_ok and isinstance(buffer.uidialog, dict):
        world.last_uidialog = buffer.uidialog

    party_ok = bool(
        buffer.party_ok
        and isinstance(buffer.party, dict)
        and buffer.party.get("subs_ok") is not False
    )
    world.party_read_ok = party_ok
    if party_ok:
        world.last_party = buffer.party
        world.party_pose_seq = int(getattr(world, "party_pose_seq", 0) or 0) + 1
        world.party_pose_at = time.monotonic()

    return result


__all__ = ["PerceptionApplyResult", "apply_perception_buffer"]
