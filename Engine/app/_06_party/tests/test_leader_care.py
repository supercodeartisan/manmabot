"""Mage list-heal stays on the leader policy. Self recovery stays on solo lines."""

from app._04_decision.behaviors.mode_actions import _hp_action_enabled
from app._04_decision.hp_actions import action_threshold, default_hp_actions
from app._06_party.config import PartyMemberConfig
from app._06_party.recovery import PartyRecovery


def test_care_lines_use_party_defaults_before_a_policy() -> None:
    cfg = PartyMemberConfig().clamped()
    assert cfg.member_heal_pct == 70
    assert cfg.member_potion_pct == 50
    assert cfg.mage_heal_pct == 80
    assert cfg.retreat_pct == 30
    assert cfg.mother_tree is True
    assert cfg.talking_scroll is True
    assert cfg.safe_zone is True


def test_care_lines_merge_from_the_leader_policy() -> None:
    cfg = PartyMemberConfig().merge_leader_policy(
        {
            "leader_mode": "moving",
            "roster": [],
            "member_heal_pct": 40,
            "member_potion_pct": 25,
            "mage_heal_pct": 65,
            "retreat_pct": 20,
            "mother_tree": False,
            "talking_scroll": False,
            "safe_zone": True,
        }
    )
    assert cfg.member_heal_pct == 40
    assert cfg.member_potion_pct == 25
    assert cfg.mage_heal_pct == 65
    assert cfg.retreat_pct == 20
    assert cfg.mother_tree is False
    assert cfg.talking_scroll is False
    assert cfg.safe_zone is True


def test_old_policy_without_care_lines_keeps_party_defaults() -> None:
    cfg = PartyMemberConfig().merge_leader_policy(
        {"leader_mode": "moving", "roster": []}
    )
    assert cfg.member_heal_pct == 70
    assert cfg.member_potion_pct == 50
    assert cfg.mage_heal_pct == 80
    assert cfg.retreat_pct == 30


def test_solo_thresholds_stay_when_party_recovery_is_absent() -> None:
    actions = default_hp_actions()
    assert action_threshold(actions, "heal") == 0.70
    assert action_threshold(actions, "hp_potion") == 0.50
    assert action_threshold(actions, "retreat") == 0.30
    disabled = [{"id": "heal", "enabled": False, "hp_below": 0.10}]
    assert action_threshold(disabled, "heal") is None
    assert _hp_action_enabled(disabled, "heal") is False


def test_a_stored_party_recovery_does_not_replace_solo_lines() -> None:
    disabled = [{"id": "heal", "enabled": False, "hp_below": 0.10}]
    PartyRecovery(
        heal_pct=40,
        potion_pct=25,
        retreat_pct=20,
        safe_zone=False,
        talking_scroll=False,
        mother_tree=False,
    )
    assert action_threshold(disabled, "heal") is None
    assert _hp_action_enabled(disabled, "heal") is False


def test_party_recovery_does_not_replace_the_solo_potion_line() -> None:
    from app._06_party.recovery import bind

    solo = [{"id": "hp_potion", "enabled": True, "hp_below": 0.35}]
    with bind(PartyRecovery(potion_pct=50)):
        assert action_threshold(solo, "hp_potion") == 0.35
        assert _hp_action_enabled(
            [{"id": "hp_potion", "enabled": False, "hp_below": 0.35}],
            "hp_potion",
        ) is False
