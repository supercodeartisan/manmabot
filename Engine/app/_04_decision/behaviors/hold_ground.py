"""Hold-ground step: stand still and hit back only at monsters attacking me.

Used while the party leader waits for members on a rally tile. Survival steps
run before this one, so potions and heal keep working. Only attackers already
within reach of the current tile are clicked; no chase, no wall detour, no
unstick, no loot, no new non-attacker targets.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app._03_world import ActionType, CharacterType
from app._04_decision import player_mode as pm
from app._04_decision.attack_feedback import excluded_target_ids
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.combat import (
    begin_engage,
    clear_engage_state,
    note_attack_attempt,
)
from app._04_decision.behaviors.loot_hop import clear_loot_hop
from app._04_decision.combat_query import (
    can_engage_target,
    nearest_attacks_me_force,
    tile_distance_from_player,
)
from app._04_decision.mode_control import is_hp_zero

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard

SCRATCH_PARTY_HOLD = "party_hold_ground"

# Melee: farther clicks walk the character. Elf uses solo ``ATTACK_CLICK_TILES``.
MELEE_REACH_TILES = 1


def set_party_hold(blackboard: "Blackboard", on: bool) -> None:
    if on:
        blackboard.scratch[SCRATCH_PARTY_HOLD] = True
    else:
        blackboard.scratch.pop(SCRATCH_PARTY_HOLD, None)


def party_hold_active(blackboard: "Blackboard") -> bool:
    return bool(blackboard.scratch.get(SCRATCH_PARTY_HOLD))


def hold_ground_reach(state: "GameState") -> int:
    """Tiles this character hits without stepping."""
    player = getattr(state, "player", None)
    kind = getattr(player, "character_type", None)
    if kind is CharacterType.MAGE and pm.uses_spell_aim():
        from app._03_world import constants as world_constants

        return int(world_constants.MAGE_SPELL_RANGE)
    if kind is CharacterType.ELF:
        return int(pm.ATTACK_CLICK_TILES)
    return MELEE_REACH_TILES


def _release_target(blackboard: "Blackboard") -> None:
    if blackboard.current_target_id is None:
        return
    blackboard.current_target_id = None
    clear_engage_state(blackboard)


def hold_ground_counterattack(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """ATTACK the nearest in-reach attacker of this character, else None."""
    if is_hp_zero(state):
        return None
    origin = blackboard.world_origin
    attacker = nearest_attacks_me_force(
        state, exclude=excluded_target_ids(blackboard), origin=origin
    )
    if (
        attacker is None
        or tile_distance_from_player(attacker) > hold_ground_reach(state)
        or (origin is not None and not can_engage_target(attacker, origin))
    ):
        _release_target(blackboard)
        return None
    tid = int(attacker.track_id)
    mid_act = blackboard.current_target_id == tid
    if mid_act:
        note_attack_attempt(blackboard, attacker)
    else:
        begin_engage(state, blackboard, tid, finish_kill=True)
    clear_loot_hop(blackboard)
    blackboard.current_item_id = None
    blackboard.current_goal = "combat"
    blackboard.emit(
        ActionType.ATTACK,
        target_id=tid,
        priority=0.5,
        reason="party hold: hit back",
        mid_act=mid_act,
    )
    return Status.SUCCESS


def step_party_hold_ground(
    state: "GameState", blackboard: "Blackboard"
) -> Status | None:
    """Column step ``party.hold_ground``: no-op unless the leader is holding."""
    if not party_hold_active(blackboard):
        return None
    fought = hold_ground_counterattack(state, blackboard)
    if fought is not None:
        return fought
    blackboard.current_goal = "party_hold"
    blackboard.emit(
        ActionType.IDLE, priority=0.4, reason="party rally wait members"
    )
    return Status.SUCCESS


__all__ = [
    "SCRATCH_PARTY_HOLD",
    "MELEE_REACH_TILES",
    "set_party_hold",
    "party_hold_active",
    "hold_ground_reach",
    "hold_ground_counterattack",
    "step_party_hold_ground",
]
