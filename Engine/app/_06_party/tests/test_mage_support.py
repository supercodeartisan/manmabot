"""Checked party-support spells: heal order, heal all, and buff remain."""
import numpy as np

from app._06_party.config import PartyMemberConfig
from app._06_party.mage_support import (
    choose_party_support,
    empty_ledger,
    remember_cast,
)

_HERE = (100, 100, 4)


def _member(name, guid, hp, y, map_id=4):
    return {
        "name": name,
        "guid": guid,
        "hp_pct": hp,
        "x": 100,
        "y": y,
        "map_id": map_id,
    }


def _slots(*guids):
    return [
        {"guid": guid, "row": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}}
        for guid in guids
    ]


def _bar(*names):
    return {"slots": [{"name": name, "slot": index} for index, name in enumerate(names)]}


def _choose(**kwargs):
    base = dict(
        self_name="mage",
        self_guid="0x1",
        here=_HERE,
        now=1_000.0,
        below=80,
        ledger=empty_ledger(),
    )
    base.update(kwargs)
    return choose_party_support(
        base.pop("members"),
        base.pop("slots"),
        **base,
    )


def test_empty_save_uses_heal_not_a_stronger_bar_spell() -> None:
    choice, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 40, 104)],
        slots=_slots("0x2"),
        checked={0},
        hotbar=_bar("힐", "풀 힐"),
    )
    assert choice is not None
    assert choice["spell"] == "heal"
    assert choice["skill_id"] == 0
    assert choice["name"] == "knight"
    assert choice["click_x"] == 5


def test_full_heal_wins_when_it_is_checked_and_on_the_bar() -> None:
    choice, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 40, 104)],
        slots=_slots("0x2"),
        checked={0, 56},
        hotbar=_bar("힐", "풀 힐"),
    )
    assert choice["skill_id"] == 56


def test_heal_all_when_two_are_in_range_and_single_when_one_is() -> None:
    both, _note = _choose(
        members=[
            _member("mage", "0x1", 100, 100),
            _member("knight", "0x2", 40, 104),
            _member("elf", "0x3", 50, 106),
        ],
        slots=_slots("0x2", "0x3"),
        checked={0, 48},
        hotbar=_bar("힐", "힐 올"),
    )
    assert both["spell"] == "heal_all"
    assert both["click_x"] is None
    one, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 40, 104)],
        slots=_slots("0x2"),
        checked={48},
        hotbar=_bar("힐 올"),
    )
    assert one is None


def test_weapon_group_keeps_the_strongest_checked_spell() -> None:
    choice, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)],
        slots=_slots("0x2"),
        checked={7, 47},
        hotbar=_bar("홀리 웨폰", "블레스 웨폰"),
    )
    assert choice["spell"] == "buff"
    assert choice["skill_id"] == 47


def test_a_fresh_report_holds_the_buff_until_ten_seconds_remain() -> None:
    members = [_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)]
    slots = _slots("0x2")
    held, _note = _choose(
        members=members,
        slots=slots,
        checked={42},
        hotbar=_bar("헤이스트"),
        reports=[{"from": "knight", "noted_at": 1_000.0, "buffs": [{"name": "헤이스트", "skill": 42, "duration": 100}]}],
    )
    assert held is None
    due, _note = _choose(
        members=members,
        slots=slots,
        checked={42},
        hotbar=_bar("헤이스트"),
        reports=[{"from": "knight", "noted_at": 1_000.0, "buffs": [{"name": "헤이스트", "skill": 42, "duration": 5}]}],
    )
    assert due["skill_id"] == 42


def test_a_cast_is_remembered_until_its_duration_runs_down() -> None:
    ledger = empty_ledger()
    members = [_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)]
    slots = _slots("0x2")
    first, _note = _choose(
        members=members,
        slots=slots,
        checked={42},
        hotbar=_bar("헤이스트"),
        ledger=ledger,
    )
    assert first["skill_id"] == 42
    remember_cast(ledger, int(first["guid"]), 42, 1_000.0)
    again, _note = _choose(
        members=members,
        slots=slots,
        checked={42},
        hotbar=_bar("헤이스트"),
        ledger=ledger,
        now=1_010.0,
    )
    assert again is None


def test_three_missed_reports_park_the_spell() -> None:
    ledger = empty_ledger()
    remember_cast(ledger, 2, 42, 900.0)
    members = [_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)]
    slots = _slots("0x2")
    for index in range(3):
        choice, _note = _choose(
            members=members,
            slots=slots,
            checked={42},
            hotbar=_bar("헤이스트"),
            reports=[{"from": "knight", "noted_at": 1_000.0 + index, "buffs": []}],
            ledger=ledger,
            now=1_000.0 + index,
        )
    assert choice is None


def test_death_clears_the_clock_and_resurrection_can_target_the_row() -> None:
    ledger = empty_ledger()
    remember_cast(ledger, 2, 2, 1_000.0)
    choice, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 0, 104)],
        slots=_slots("0x2"),
        checked={60},
        hotbar=_bar("리절렉션"),
        ledger=ledger,
    )
    assert choice["spell"] == "resurrect"
    assert ledger["spells"] == {}


def test_cure_follows_a_poison_report_only() -> None:
    members = [_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)]
    slots = _slots("0x2")
    quiet, _note = _choose(
        members=members,
        slots=slots,
        checked={8},
        hotbar=_bar("큐어 포이즌"),
        reports=[{"from": "knight", "noted_at": 1_000.0, "buffs": [], "poisoned": False}],
    )
    assert quiet is None
    poisoned, _note = _choose(
        members=members,
        slots=slots,
        checked={8},
        hotbar=_bar("큐어 포이즌"),
        reports=[{"from": "knight", "noted_at": 1_000.0, "buffs": [], "poisoned": True}],
    )
    assert poisoned["spell"] == "cure"


def test_self_only_spells_are_not_offered_to_another_member() -> None:
    members = [_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)]
    slots = _slots("0x2")
    skipped, _note = _choose(
        members=members,
        slots=slots,
        checked={2, 13, 53},
        hotbar=_bar("실드", "디크리즈 웨이트", "그레이터 헤이스트"),
    )
    assert skipped is None
    haste, _note = _choose(
        members=members,
        slots=slots,
        checked={2, 13, 53, 42},
        hotbar=_bar("실드", "디크리즈 웨이트", "그레이터 헤이스트", "헤이스트"),
    )
    assert haste["skill_id"] == 42


def test_catch_up_heal_stays_in_range_and_leaves_the_buff() -> None:
    low_far = [
        _member("mage", "0x1", 100, 100),
        _member("knight", "0x2", 40, 120),
    ]
    walked, note = _choose(
        members=low_far,
        slots=_slots("0x2"),
        checked={0, 7},
        hotbar=_bar("힐", "홀리 웨폰"),
        cast_only=True,
        heals_only=True,
    )
    assert walked is None
    assert "step" not in note
    low_near = [
        _member("mage", "0x1", 100, 100),
        _member("knight", "0x2", 40, 104),
    ]
    choice, _note = _choose(
        members=low_near,
        slots=_slots("0x2"),
        checked={0, 7},
        hotbar=_bar("힐", "홀리 웨폰"),
        cast_only=True,
        heals_only=True,
    )
    assert choice["spell"] == "heal"
    assert choice["skill_id"] == 0
    seated, _note = _choose(
        members=low_near,
        slots=_slots("0x2"),
        checked={0, 7},
        hotbar=_bar("힐", "홀리 웨폰"),
    )
    assert seated["spell"] == "heal"


class _Fence:
    """Open cells with one north fence between y=101 and y=102 at x=100."""

    has_edge_fences = True

    def __init__(self) -> None:
        self.block_n = np.zeros((120, 120), dtype=bool)
        self.block_e = np.zeros((120, 120), dtype=bool)
        self.block_n[102, 100] = True

    def is_walkable(self, x: int, y: int) -> bool:
        return True


def _use_fence(monkeypatch) -> None:
    fence = _Fence()
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map",
        lambda: fence,
    )


def test_a_fence_holds_the_heal_and_the_buff(monkeypatch) -> None:
    _use_fence(monkeypatch)
    held, note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 40, 104)],
        slots=_slots("0x2"),
        checked={0, 7},
        hotbar=_bar("힐", "홀리 웨폰"),
    )
    assert held is None
    assert note == "skip line blocked"
    buff, buff_note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)],
        slots=_slots("0x2"),
        checked={7},
        hotbar=_bar("홀리 웨폰"),
    )
    assert buff is None
    assert buff_note == "skip line blocked"


def test_a_clear_side_of_the_fence_still_gets_the_heal(monkeypatch) -> None:
    _use_fence(monkeypatch)
    choice, _note = _choose(
        members=[
            _member("mage", "0x1", 100, 100),
            _member("knight", "0x2", 40, 101),
            _member("elf", "0x3", 30, 104),
        ],
        slots=_slots("0x2", "0x3"),
        checked={0, 48},
        hotbar=_bar("힐", "힐 올"),
    )
    assert choice["spell"] == "heal"
    assert choice["name"] == "knight"


def test_cure_still_casts_across_the_fence(monkeypatch) -> None:
    _use_fence(monkeypatch)
    choice, _note = _choose(
        members=[_member("mage", "0x1", 100, 100), _member("knight", "0x2", 100, 104)],
        slots=_slots("0x2"),
        checked={8},
        hotbar=_bar("큐어 포이즌"),
        reports=[{"from": "knight", "noted_at": 1_000.0, "buffs": [], "poisoned": True}],
    )
    assert choice["spell"] == "cure"


def test_leader_policy_keeps_the_mages_own_checks() -> None:
    cfg = PartyMemberConfig(mage_support_skills={"mage_2": True, "mage_0": False})
    merged = cfg.merge_leader_policy({"leader_mode": "moving", "roster": [], "mage_heal_pct": 65})
    assert merged.mage_heal_pct == 65
    assert merged.mage_support_skills == {"mage_2": True, "mage_0": False}
