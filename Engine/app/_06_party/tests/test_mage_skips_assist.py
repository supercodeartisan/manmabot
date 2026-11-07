"""A mage party member does not take an assist target."""
from __future__ import annotations

from app._02_state.enums import CharacterType
from app._02_state.objects import Position
from app._02_state.player import PlayerState
from app._03_world import GameState
from app._06_party.manager import mage_skips_party_assist


def _state(kind: CharacterType) -> GameState:
    player = PlayerState(
        track_id=1,
        position=Position(x=0.5, y=0.5),
        character_type=kind,
    )
    return GameState(player=player)


def test_mage_skips_assist() -> None:
    assert mage_skips_party_assist(_state(CharacterType.MAGE)) is True


def test_other_classes_still_assist() -> None:
    for kind in (CharacterType.KNIGHT, CharacterType.ELF, CharacterType.ROYAL):
        assert mage_skips_party_assist(_state(kind)) is False


def test_missing_state_does_not_skip() -> None:
    assert mage_skips_party_assist(None) is False


if __name__ == "__main__":
    test_mage_skips_assist()
    test_other_classes_still_assist()
    test_missing_state_does_not_skip()
    print("mage skips assist ok")
