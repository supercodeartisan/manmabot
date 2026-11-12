"""Account class chooses hunt attack mode. A saved ranged value does not."""
from __future__ import annotations

from settings.profile import (
    Profile,
    apply_account_character,
    attack_mode_for_character,
    stamp_character_fields,
    stamp_settings_character,
)
from settings.schedule import ScheduleTask, profile_snapshot
from settings.task_runtime import apply_runtime_settings


def test_class_map() -> None:
    assert attack_mode_for_character("mage") == "magic"
    assert attack_mode_for_character("elf") == "ranged"
    assert attack_mode_for_character("knight") == "melee"
    assert attack_mode_for_character("royal") == "melee"
    assert attack_mode_for_character("prince") == "melee"


def test_stale_hunt_value_does_not_override_mage() -> None:
    profile = Profile(character="elf", attack_mode="ranged")
    task = ScheduleTask(
        settings={"hunt": {"attack_mode": "ranged"}, "magic": {"class": "mage"}},
        character="mage",
    )
    apply_runtime_settings(task, profile)
    assert profile.character == "mage"
    assert profile.attack_mode == "magic"


def test_elf_stays_ranged() -> None:
    profile = Profile(character="mage", attack_mode="magic")
    task = ScheduleTask(
        settings={"hunt": {"attack_mode": "magic"}},
        character="elf",
    )
    apply_runtime_settings(task, profile)
    assert profile.character == "elf"
    assert profile.attack_mode == "ranged"


def test_account_class_sets_the_profile() -> None:
    profile = Profile(character="mage", attack_mode="magic")
    account = type("A", (), {"character_type": "elf"})()
    assert apply_account_character(profile, account) == "elf"
    assert profile.character == "elf"
    assert profile.attack_mode == "ranged"
    assert apply_account_character(profile, type("A", (), {"character_type": ""})()) is None
    assert profile.character == "elf"


def test_stamp_keeps_party_seat_and_other_fields() -> None:
    task = ScheduleTask(
        account_id="acct",
        character="elf",
        settings={
            "magic": {"class": "elf", "skills": {"heal": True}},
            "hunt": {"attack_mode": "ranged", "attack_range": 16},
            "party": {"seat_role": "mage"},
        },
    )
    assert stamp_character_fields(task, "mage")
    assert task.character == "mage"
    assert task.settings["magic"]["class"] == "mage"
    assert task.settings["magic"]["skills"] == {"heal": True}
    assert task.settings["hunt"]["attack_mode"] == "magic"
    assert task.settings["hunt"]["attack_range"] == 16
    assert task.settings["party"]["seat_role"] == "mage"
    assert stamp_character_fields(task, "mage") is False
    assert stamp_character_fields(task, "") is False


def test_stamp_settings_follows_class() -> None:
    settings = {"magic": {"class": "elf"}, "hunt": {"attack_mode": "ranged"}}
    assert stamp_settings_character(settings, "knight")
    assert settings["magic"]["class"] == "knight"
    assert settings["hunt"]["attack_mode"] == "melee"
    assert stamp_settings_character(settings, "nope") is False


def test_snapshot_keeps_party_supply() -> None:
    profile = Profile(
        party_member_arrow_min=1600,
        party_member_arrow_give=200,
        party_shopkeeper_arrow_min=300,
        party_shopkeeper_arrow_buy=200,
        party_member_hp_min=3,
        party_member_hp_give=5,
        party_shopkeeper_hp_min=5,
        party_shopkeeper_hp_buy=5,
    )
    party = profile_snapshot(profile)["party"]
    assert party["member_arrow_min"] == 1600
    assert party["member_arrow_give"] == 200
    assert party["shopkeeper_arrow_min"] == 300
    assert party["shopkeeper_arrow_buy"] == 200
    assert party["member_hp_min"] == 3
    assert party["member_hp_give"] == 5
    assert party["shopkeeper_hp_min"] == 5
    assert party["shopkeeper_hp_buy"] == 5
    fresh = Profile()
    apply_runtime_settings(ScheduleTask(settings={"party": party}), fresh)
    assert fresh.party_member_arrow_min == 1600
    assert fresh.party_member_arrow_give == 200
    assert fresh.party_member_hp_min == 3
    assert fresh.party_shopkeeper_hp_buy == 5


def test_snapshot_keeps_the_rest_of_the_party_screen() -> None:
    profile = Profile(
        party_mage_heal_pct=65,
        party_member_heal_pct=55,
        party_member_potion_pct=40,
        party_retreat_pct=25,
        party_mother_tree=False,
        party_talking_scroll=False,
        party_safe_zone=False,
        party_tree_hp_to_mp=False,
        party_tree_hp_to_mp_hp=70,
        party_tree_hp_to_mp_mp=60,
        party_tree_heal=False,
        party_tree_heal_hp=35,
        party_tree_heal_mp=75,
        party_loot_pickup="adena",
        party_loot_weight_pct=45,
        party_member_mp_min=7,
        party_member_mp_give=4,
        party_shopkeeper_mp_min=12,
        party_shopkeeper_mp_buy=8,
        party_member_depoison_min=3,
        party_member_depoison_give=2,
        party_shopkeeper_depoison_min=4,
        party_shopkeeper_depoison_buy=6,
        party_routine=[
            {
                "id": "hunt-1",
                "map_id": "talking_island",
                "kind": "battle",
                "duration_minutes": 30,
            }
        ],
    )
    party = profile_snapshot(profile)["party"]
    assert party["mage_heal_pct"] == 65
    assert party["member_heal_pct"] == 55
    assert party["retreat_pct"] == 25
    assert party["mother_tree"] is False
    assert party["tree_hp_to_mp_hp"] == 70
    assert party["loot_pickup"] == "adena"
    assert party["loot_weight_pct"] == 45
    assert party["member_mp_min"] == 7
    assert party["shopkeeper_depoison_buy"] == 6
    assert party["routine"][0]["map_id"] == "talking_island"
    fresh = Profile()
    apply_runtime_settings(ScheduleTask(settings={"party": party}), fresh)
    assert fresh.party_mage_heal_pct == 65
    assert fresh.party_loot_pickup == "adena"
    assert fresh.party_loot_weight_pct == 45
    assert fresh.party_mother_tree is False
    assert fresh.party_member_mp_min == 7
    assert fresh.party_routine[0]["map_id"] == "talking_island"


def test_snapshot_follows_class() -> None:
    snap = profile_snapshot(Profile(character="mage", attack_mode="ranged"))
    assert snap["hunt"]["attack_mode"] == "magic"
    snap = profile_snapshot(Profile(character="elf", attack_mode="magic"))
    assert snap["hunt"]["attack_mode"] == "ranged"


if __name__ == "__main__":
    test_class_map()
    test_stale_hunt_value_does_not_override_mage()
    test_elf_stays_ranged()
    test_account_class_sets_the_profile()
    test_stamp_keeps_party_seat_and_other_fields()
    test_stamp_settings_follows_class()
    test_snapshot_keeps_party_supply()
    test_snapshot_keeps_the_rest_of_the_party_screen()
    test_snapshot_follows_class()
    print("attack mode tests ok")
