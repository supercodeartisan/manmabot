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
    test_snapshot_follows_class()
    print("attack mode tests ok")
