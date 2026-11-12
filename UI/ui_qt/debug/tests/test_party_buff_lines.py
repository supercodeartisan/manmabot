"""Received party-buff rows format without dropping a member."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
for _path in (_ROOT / "UI", _ROOT / "Engine"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from ui_qt.debug.party_buff_lines import party_buff_lines


def test_each_member_keeps_name_skill_and_remaining_time() -> None:
    lines = party_buff_lines(
        [
            {
                "from": "blackprince",
                "buffs": [],
                "poisoned": False,
                "noted_at": 1_000.0,
            },
            {
                "from": "매력여기사",
                "buffs": [{"name": "홀리 웨폰", "skill": 7, "duration": 1180}],
                "poisoned": True,
                "noted_at": 990.0,
            },
        ],
        now=1_004.2,
    )
    assert lines == [
        ("blackprince", "—", "4s"),
        ("매력여기사", "홀리 웨폰 7 1180s, poison", "14s"),
    ]


def test_a_missing_list_is_empty() -> None:
    assert party_buff_lines(None, now=1.0) == []
    assert party_buff_lines(["nope", {"from": ""}], now=1.0) == [("—", "—", "—")]
