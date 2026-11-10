"""Leader loot policy: no priority knob, solo farm does not change who loots."""
from __future__ import annotations

from types import SimpleNamespace

from app._04_decision import player_mode as pm
from app._04_decision.behaviors.mode_actions import party_leader_pile_ok
from app._06_party.config import PartyMemberConfig
from app._06_party.loot import party_loot_ownership_filter, party_loot_radius


def _pile(rx: int, on_screen: bool):
    pos = SimpleNamespace(x=0.5, y=0.5) if on_screen else None
    return SimpleNamespace(world_rx=rx, world_ry=0, position=pos)


def _leader_board():
    return SimpleNamespace(scratch={"party_leader_no_loot": True})


def test_leader_uses_the_near_loot_radius() -> None:
    board = _leader_board()
    saved = pm.LOOT_MAX_TILES
    pm.LOOT_MAX_TILES = 4
    try:
        assert party_leader_pile_ok(board, _pile(4, True))
        assert not party_leader_pile_ok(board, _pile(5, True))
        assert not party_leader_pile_ok(board, _pile(2, False))
    finally:
        pm.LOOT_MAX_TILES = saved


def test_solo_pile_check_does_not_apply_the_leader_cap() -> None:
    board = SimpleNamespace(scratch={})
    assert party_leader_pile_ok(board, _pile(20, False))


def test_responsible_loots_party_drops_not_only_own() -> None:
    cfg = PartyMemberConfig(
        random_loot=False, loot_role="responsible", farm_mode="solo"
    )
    assert party_loot_ownership_filter(cfg) is False


def test_other_members_loot_their_own_piles() -> None:
    cfg = PartyMemberConfig(random_loot=False, loot_role="none", farm_mode="solo")
    assert party_loot_ownership_filter(cfg) is True


def test_near_radius_is_shared_and_responsible_is_wider() -> None:
    saved_near = pm.LOOT_MAX_TILES
    saved_wide = pm.LOOT_ENGAGE_MAX_TILES
    pm.LOOT_MAX_TILES = 7
    pm.LOOT_ENGAGE_MAX_TILES = 30
    try:
        own = PartyMemberConfig(random_loot=False, loot_role="none")
        wide = PartyMemberConfig(random_loot=False, loot_role="responsible")
        assert party_loot_radius(own) == 7
        assert party_loot_radius(wide) == 30
    finally:
        pm.LOOT_MAX_TILES = saved_near
        pm.LOOT_ENGAGE_MAX_TILES = saved_wide


def test_random_loot_is_party_drops_without_an_ownership_gate() -> None:
    cfg = PartyMemberConfig(random_loot=True, loot_role="none", farm_mode="party")
    assert party_loot_ownership_filter(cfg) is False


def test_leader_policy_does_not_carry_a_loot_priority() -> None:
    cfg = PartyMemberConfig(farm_mode="solo").merge_leader_policy(
        {
            "random_loot": False,
            "loot_role": "responsible",
            "loot_priority": "loot",
        },
        self_name="",
    )
    assert not hasattr(cfg, "loot_priority")
    assert cfg.loot_role == "responsible"
    assert cfg.farm_mode == "solo"
    assert cfg.random_loot is False


if __name__ == "__main__":
    test_leader_uses_the_near_loot_radius()
    test_solo_pile_check_does_not_apply_the_leader_cap()
    test_responsible_loots_party_drops_not_only_own()
    test_other_members_loot_their_own_piles()
    test_near_radius_is_shared_and_responsible_is_wider()
    test_random_loot_is_party_drops_without_an_ownership_gate()
    test_leader_policy_does_not_carry_a_loot_priority()
    print("OK")
