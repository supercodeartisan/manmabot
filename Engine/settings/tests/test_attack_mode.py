"""Account class chooses hunt attack mode. A saved ranged value does not."""
from __future__ import annotations

from settings.profile import Profile, attack_mode_for_character
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


def test_snapshot_follows_class() -> None:
    snap = profile_snapshot(Profile(character="mage", attack_mode="ranged"))
    assert snap["hunt"]["attack_mode"] == "magic"
    snap = profile_snapshot(Profile(character="elf", attack_mode="magic"))
    assert snap["hunt"]["attack_mode"] == "ranged"


if __name__ == "__main__":
    test_class_map()
    test_stale_hunt_value_does_not_override_mage()
    test_elf_stays_ranged()
    test_snapshot_follows_class()
    print("attack mode tests ok")
