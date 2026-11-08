"""Assist clicks only when the solo shot line is clear."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app._02_state.enums import ActionType
from app._06_party.assist import engage_like_solo


def _mob() -> SimpleNamespace:
    return SimpleNamespace(track_id=16, species_name="monster_흑기사_16")


def _board() -> SimpleNamespace:
    return SimpleNamespace(current_target_id=None, world_origin=object(), intent=None)


def test_fence_holds_instead_of_clicking() -> None:
    board = _board()
    seen: dict[str, object] = {}

    def _combat(state, blackboard, allow_new=True, chosen=None, reason=None):
        seen["allow_new"] = allow_new
        seen["chosen"] = chosen
        blackboard.intent = SimpleNamespace(
            action=ActionType.IDLE,
            reason="wall detour pending",
            target_id=16,
        )

    with (
        patch(
            "app._04_decision.species_rules.is_avoided_for_state",
            return_value=False,
        ),
        patch(
            "app._04_decision.combat_query.attack_line_clear",
            return_value=False,
        ),
        patch("app._04_decision.behaviors.combat.begin_engage") as begin,
        patch(
            "app._04_decision.behaviors.mode_actions.continue_or_start_combat",
            side_effect=_combat,
        ),
    ):
        intent = engage_like_solo(object(), board, _mob(), reason="assist")
    begin.assert_called_once()
    assert seen["allow_new"] is False
    assert seen["chosen"] is None
    assert intent.action is ActionType.IDLE


def test_clear_line_uses_the_chosen_monster() -> None:
    board = _board()
    mob = _mob()
    seen: dict[str, object] = {}

    def _combat(state, blackboard, allow_new=True, chosen=None, reason=None):
        seen["allow_new"] = allow_new
        seen["chosen"] = chosen
        seen["reason"] = reason
        blackboard.intent = SimpleNamespace(
            action=ActionType.ATTACK,
            reason=reason,
            target_id=16,
        )

    with (
        patch(
            "app._04_decision.species_rules.is_avoided_for_state",
            return_value=False,
        ),
        patch(
            "app._04_decision.combat_query.attack_line_clear",
            return_value=True,
        ),
        patch(
            "app._04_decision.behaviors.mode_actions.continue_or_start_combat",
            side_effect=_combat,
        ),
    ):
        intent = engage_like_solo(object(), board, mob, reason="assist dist=2")
    assert seen["allow_new"] is True
    assert seen["chosen"] is mob
    assert intent.action is ActionType.ATTACK


def test_avoided_species_does_not_engage() -> None:
    with (
        patch(
            "app._04_decision.species_rules.is_avoided_for_state",
            return_value=True,
        ),
        patch(
            "app._04_decision.behaviors.mode_actions.continue_or_start_combat"
        ) as combat,
    ):
        intent = engage_like_solo(object(), _board(), _mob(), reason="assist")
    combat.assert_not_called()
    assert intent.action is ActionType.IDLE
    assert "assist_species" in intent.reason


if __name__ == "__main__":
    test_fence_holds_instead_of_clicking()
    test_clear_line_uses_the_chosen_monster()
    test_avoided_species_does_not_engage()
    print("ok")
