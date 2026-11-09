"""Party HUD row parse and the 80% heal order."""
from app._01_perception.lc_view import parse_party_hud_text
from app._06_party.hud_heal import heal_targets, list_heal_click, next_heal_target

_SAMPLE = """\
# partyhud t=16ms
WIN x=26.0 y=281.0 w=192.0 h=387.0 vis=1  px=[16,183,136,424]
SLOT 0 guid=0x8947B1F hp=100.0 mp=100.0 active=1
  W +0x060 Layout@ui@cocos2d@@ abs=(26.0, 621.0) size=(189.0 x 47.0) px=[16,183,134,212] scale=1.00,1.00
  W +0x078 LoadingBar@ui@cocos2d@@ abs=(79.0, 634.0) size=(127.0 x 6.0) px=[49,200,129,204] scale=1.00,1.00
  W +0x0D0 Button@ui@cocos2d@@ abs=(26.0, 621.0) size=(189.0 x 47.0) px=[16,183,134,212] scale=1.00,1.00
SLOT 1 guid=0x8C6D8A3 hp=56.0 mp=100.0 active=1
  W +0x060 Layout@ui@cocos2d@@ abs=(26.0, 573.0) size=(189.0 x 47.0) px=[16,213,134,242] scale=1.00,1.00
  W +0x0A8 ImageView@ui@cocos2d@@ abs=(14.0, 598.0) size=(30.0 x 30.0) px=[9,208,28,226] scale=1.00,1.00
  W +0x0D0 Button@ui@cocos2d@@ abs=(26.0, 573.0) size=(189.0 x 47.0) px=[16,213,134,242] scale=1.00,1.00
SLOTS active=2/8
"""

_MEMBERS = [
    {"name": "poorboy", "guid": "0x08947B1F", "hp_pct": 100, "is_leader": False},
    {"name": "매력여기사", "guid": "0x08C6D8A3", "hp_pct": 56, "is_leader": True},
    {"name": "mage", "guid": "0x01111111", "hp_pct": 40, "is_leader": False},
]


def test_row_box_is_the_button():
    snap = parse_party_hud_text(_SAMPLE)
    assert snap is not None and snap["open"] is True
    assert snap["slots"][0]["row"]["off"] == "0x0D0"
    assert snap["slots"][0]["row"]["y0"] == 183
    assert snap["slots"][1]["row"]["y0"] == 213


def test_lowest_under_80_and_skip_self():
    slots = parse_party_hud_text(_SAMPLE)["slots"]
    # mage has no HUD row, so the leader at 56% is the only candidate.
    one = next_heal_target( _MEMBERS, slots, self_name="mage")
    assert one["name"] == "매력여기사"
    assert one["hp_pct"] == 56
    assert one["row"]["x0"] == 16
    # 100% is not due. Self at 40% with a row is still skipped.
    slots.append(
        {
            "guid": "0x1111111",
            "row": {"off": "0x0D0", "x0": 1, "y0": 2, "x1": 3, "y1": 4},
        }
    )
    rows = heal_targets(_MEMBERS, slots, self_guid="0x01111111")
    assert [row["name"] for row in rows] == ["매력여기사"]


def test_click_is_the_row_center():
    slots = parse_party_hud_text(_SAMPLE)["slots"]
    click = list_heal_click(_MEMBERS, slots, self_name="mage")
    assert click["name"] == "매력여기사"
    assert click["click_x"] == (16 + 134) // 2
    assert click["click_y"] == (213 + 242) // 2


def test_dead_other_map_and_past_9_are_skipped():
    slots = parse_party_hud_text(_SAMPLE)["slots"]
    here = (32700, 32800, 4)
    dead = {
        "name": "매력여기사",
        "guid": "0x08C6D8A3",
        "hp_pct": 0,
        "map_id": 4,
        "x": 32700,
        "y": 32800,
    }
    near = {
        "name": "poorboy",
        "guid": "0x08947B1F",
        "hp_pct": 50,
        "map_id": 4,
        "x": 32700,
        "y": 32809,
    }
    far = dict(near, y=32810)
    other_map = dict(near, map_id=7, y=32800)
    assert next_heal_target([dead, near], slots, here=here)["name"] == "poorboy"
    assert next_heal_target([near], slots, here=here)["name"] == "poorboy"
    assert next_heal_target([far], slots, here=here) is None
    assert next_heal_target([other_map], slots, here=here) is None
    assert next_heal_target([dead], slots, here=here) is None


def test_raw_party_pos_reaches_nav_here():
    from app._03_world.merge.memory_sync import get_map_origin

    ox, oy = get_map_origin()
    here = (700, 1200, 4)
    slots = parse_party_hud_text(_SAMPLE)["slots"]
    near = {
        "name": "매력여기사",
        "guid": "0x08C6D8A3",
        "hp_pct": 56,
        "map_id": 4,
        "x": ox + 700,
        "y": oy + 1200 + 4,
    }
    far = dict(near, y=oy + 1200 + 20)
    assert next_heal_target([near], slots, here=here, self_name="poorboy")["name"] == "매력여기사"
    assert next_heal_target([far], slots, here=here, self_name="poorboy") is None


def test_closed_bar_has_no_rows():
    snap = parse_party_hud_text("# partyhud t=1ms  창 없음 ioctl=3\n")
    assert snap is not None
    assert snap["open"] is False
    assert snap["slots"] == []
    assert next_heal_target(_MEMBERS, snap["slots"]) is None


if __name__ == "__main__":
    test_row_box_is_the_button()
    test_lowest_under_80_and_skip_self()
    test_click_is_the_row_center()
    test_dead_other_map_and_past_9_are_skipped()
    test_raw_party_pos_reaches_nav_here()
    test_closed_bar_has_no_rows()
    print("ok")
