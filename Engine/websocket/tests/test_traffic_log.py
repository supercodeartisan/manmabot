"""Party buff lines keep every member. Other frames stay short."""
from websocket.traffic_log import clear, note, snapshot


class _Frame:
    def __init__(self, body: dict) -> None:
        self.sender = "leader"
        self.ts = 1_000.0
        self.message = body


def test_party_buffs_keep_every_member_and_buff() -> None:
    clear()
    note(
        "in",
        _Frame(
            {
                "type": "party_buffs",
                "from": "leader",
                "session": "abc",
                "rows": [
                    {
                        "from": "poorboy",
                        "buffs": [{"name": "홀리 웨폰", "skill": 7, "duration": 1180}],
                        "poisoned": False,
                    },
                    {
                        "from": "blackprince",
                        "buffs": [
                            {"name": "헤이스트", "skill": 42, "duration": 900},
                            {"name": "블레스 웨폰", "skill": 47, "duration": 400},
                        ],
                        "poisoned": True,
                    },
                    {"from": "매력여기사", "buffs": [], "poisoned": False},
                ],
            }
        ),
    )
    line = snapshot()[-1]
    assert "홀리 웨폰 7 1180s" in line
    assert "blackprince: 헤이스트 42 900s, 블레스 웨폰 47 400s, poison" in line
    assert "매력여기사: —" in line
    assert "session=abc" in line


def test_other_frames_stay_short() -> None:
    clear()
    note(
        "in",
        _Frame(
            {
                "type": "party_reports",
                "from": "leader",
                "reports": [{"from": "x", "buffs": [{"name": "홀리 웨폰", "duration": 1180}] * 4}],
            }
        ),
    )
    line = snapshot()[-1]
    assert len(line.split("reports=", 1)[-1].split(" · ")[0]) <= 40
