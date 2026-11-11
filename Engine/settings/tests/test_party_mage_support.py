"""A missing party heal stays on. An explicit false turns it off."""
from __future__ import annotations

from settings.party_mage_support import checked_skill_ids


def test_missing_heal_stays_on_beside_other_spells() -> None:
    assert checked_skill_ids({"mage_7": True, "mage_2": True}) == {0, 2, 7}


def test_empty_save_is_heal_only() -> None:
    assert checked_skill_ids({}) == {0}
    assert checked_skill_ids(None) == {0}


def test_explicit_heal_off_stays_off() -> None:
    assert checked_skill_ids({"mage_0": False, "mage_7": True}) == {7}
    assert checked_skill_ids({"mage_0": False}) == set()
