"""Leader loot policy: no priority knob, solo farm does not change who loots."""
from __future__ import annotations

from app._06_party.config import PartyMemberConfig
from app._06_party.loot import party_loot_ownership_filter


def test_responsible_loots_own_drops_even_in_solo_farm() -> None:
    cfg = PartyMemberConfig(
        random_loot=False, loot_role="responsible", farm_mode="solo"
    )
    assert party_loot_ownership_filter(cfg) is True


def test_none_does_not_loot_even_in_solo_farm() -> None:
    cfg = PartyMemberConfig(random_loot=False, loot_role="none", farm_mode="solo")
    assert party_loot_ownership_filter(cfg) is None


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
    test_responsible_loots_own_drops_even_in_solo_farm()
    test_none_does_not_loot_even_in_solo_farm()
    test_random_loot_is_party_drops_without_an_ownership_gate()
    test_leader_policy_does_not_carry_a_loot_priority()
    print("OK")
