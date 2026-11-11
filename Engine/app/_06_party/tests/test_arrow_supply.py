"""Party arrow supply decisions. No game client."""
from __future__ import annotations

from app._04_decision.player_mode import LOOT_MODE_ADENA
from app._04_decision.shop_trip import needs_arrow_buy
from app._06_party.arrow_duty import _supply_specs, note_supply_shop_finished
from app._06_party.arrow_policy import (
    affordable_supply_qty,
    choose_supply_duty,
    next_supply_buy,
    supply_fill_qty,
    line_omit_names,
    mage_seat_names,
    mp_recipient_names,
    party_shop_buy_qty,
    remember_delivered,
    report_supply_count,
    rows_with_expected,
    pick_arrow_duty,
    shopkeeper_socket_live,
    supply_pile_matches,
    supply_pile_qty_ok,
)
from app._06_party.config import PartyMemberConfig
from app._06_party.config import PartyMemberConfig
from app._06_party.loot import _party_loot_mode, party_loot_ownership_filter


class _Board:
    def __init__(self) -> None:
        self.scratch: dict = {}
        self.needs_arrows = True


class _Inv:
    def __init__(self, weight: float) -> None:
        self.weight_ratio = weight


class _State:
    def __init__(self, weight: float) -> None:
        self.player = type("P", (), {"inventory": _Inv(weight)})()


def test_shopkeeper_does_not_take_ground_loot() -> None:
    cfg = PartyMemberConfig(random_loot=True, loot_role="responsible", seat_role="shopkeeper")
    assert party_loot_ownership_filter(cfg) is None


def test_random_loot_still_available_for_a_normal_seat() -> None:
    cfg = PartyMemberConfig(random_loot=True, loot_role="none", seat_role="member")
    assert party_loot_ownership_filter(cfg) is False


def test_short_shopkeeper_buys_before_dropping() -> None:
    duty = pick_arrow_duty(
        100,
        [{"from": "Mage", "items": {"arrows": 10}, "map_id": 4, "x": 1, "y": 2}],
        member_min=300,
        keeper_min=300,
        self_name="Keeper",
    )
    assert duty == {"kind": "buy"}


def test_drop_qty_keeps_the_shopkeeper_reserve() -> None:
    duty = pick_arrow_duty(
        400,
        [{"from": "Elf", "items": {"arrows": 900, "silver_arrows": 50}, "map_id": 4, "x": 3, "y": 4}],
        member_min=300,
        keeper_min=300,
        self_name="Keeper",
    )
    assert duty is not None
    assert duty["kind"] == "drop"
    assert duty["name"] == "Elf"
    assert duty["qty"] == 100


def test_drop_uses_the_boss_give_count() -> None:
    duty = pick_arrow_duty(
        500,
        [{"from": "Elf", "items": {"arrows": 900, "silver_arrows": 290}, "map_id": 4, "x": 3, "y": 4}],
        member_min=300,
        keeper_min=300,
        give_qty=80,
        self_name="Keeper",
    )
    assert duty is not None
    assert duty["qty"] == 80
    short = pick_arrow_duty(
        320,
        [{"from": "Elf", "items": {"arrows": 900, "silver_arrows": 10}, "map_id": 4, "x": 3, "y": 4}],
        member_min=300,
        keeper_min=300,
        give_qty=80,
        self_name="Keeper",
    )
    assert short is not None
    assert short["qty"] == 20


def test_mage_seat_is_not_an_arrow_target() -> None:
    roster = [
        {"name": "Mage", "role": "mage"},
        {"name": "Elf", "role": "member"},
    ]
    assert mage_seat_names(roster) == {"mage"}
    rows = [
        {"from": "Mage", "items": {"arrows": 900, "silver_arrows": 0}, "map_id": 4, "x": 1, "y": 1},
        {"from": "Boss", "items": {"arrows": 900, "silver_arrows": 10}, "map_id": 4, "x": 2, "y": 2},
    ]
    duty = pick_arrow_duty(
        500,
        rows,
        member_min=300,
        keeper_min=300,
        give_qty=80,
        self_name="Keeper",
        skip_names=mage_seat_names(roster),
    )
    assert duty is not None
    assert duty["name"] == "Boss"
    assert duty["qty"] == 80


def test_party_buy_qty_does_not_replace_solo() -> None:
    assert party_shop_buy_qty({}, "silver_arrows", 40) == 40
    assert party_shop_buy_qty(
        {"party_shopkeeper_arrow": True, "party_arrow_buy_qty": 250},
        "silver_arrows",
        40,
    ) == 250
    assert party_shop_buy_qty(
        {"party_shopkeeper_arrow": True, "party_arrow_buy_qty": 250},
        "hp_potion",
        10,
    ) == 10
    assert party_shop_buy_qty(
        {"party_shopkeeper_arrow": True, "party_arrow_buy_qty": 250},
        "buy_normal_arrows_talking",
        40,
    ) == 40


def _supply_rows() -> list[dict]:
    return [
        {
            "from": "Mage",
            "items": {
                "hp_potion": 1,
                "depoison": 0,
                "mp_potion": 0,
                "arrows": 0,
                "silver_arrows": 0,
            },
            "map_id": 4,
            "x": 1,
            "y": 1,
        },
        {
            "from": "Elf",
            "items": {
                "hp_potion": 1,
                "depoison": 5,
                "mp_potion": 9,
                "arrows": 10,
                "silver_arrows": 0,
            },
            "map_id": 4,
            "x": 2,
            "y": 2,
        },
        {
            "from": "Boss",
            "items": {
                "hp_potion": 50,
                "depoison": 5,
                "mp_potion": 0,
                "arrows": 10,
                "silver_arrows": 0,
            },
            "map_id": 4,
            "x": 3,
            "y": 3,
        },
    ]


def test_potions_come_before_arrows() -> None:
    specs = _supply_specs(PartyMemberConfig(), {"mage"})
    assert [row["item"] for row in specs] == ["hp", "arrow"]
    full = {"hp": 30, "depoison": 5, "mp": 20, "arrow": 500}
    duty = choose_supply_duty(full, _supply_rows(), specs, self_name="Keeper")
    assert duty is not None
    assert duty["item"] == "hp"
    assert duty["name"] == "Mage"
    buy = choose_supply_duty(
        {"hp": 5, "depoison": 5, "mp": 20, "arrow": 500},
        _supply_rows(),
        specs,
        self_name="Keeper",
    )
    assert buy["kind"] == "buy"
    assert buy["item"] == "hp"
    # Two short reports still add 18. The buy is the configured 20, not that sum.
    assert buy["party_need"] == 18
    assert buy["buy"] == 20
    assert buy["keeper_min"] == 20
    rows = _supply_rows()
    for row in rows:
        row["items"]["hp_potion"] = 40
        row["items"]["depoison"] = 5
    arrows = choose_supply_duty(full, rows, specs, self_name="Keeper")
    assert arrows is not None
    assert arrows["item"] == "arrow"
    assert arrows["name"] == "Elf"
    short_mp = choose_supply_duty(
        {"hp": 30, "depoison": 5, "mp": 2, "arrow": 400},
        rows,
        specs,
        self_name="Keeper",
    )
    assert short_mp is not None
    assert short_mp["item"] == "arrow"


class _Pile:
    def __init__(self, name: str, loot_qty: int | None = None) -> None:
        self.detail_classification = ""
        self.species_name = "item"
        self.identity = type("I", (), {"name": name})()
        self.loot_qty = loot_qty


def test_party_supply_reads_silver_arrows_only() -> None:
    from app._03_world.merge.memory_inventory import ARROW_IDS, SILVER_ARROW_IDS
    from app._06_party.arrow_duty import supply_shop_id
    from app._06_party.arrow_policy import bag_supply_counts
    from app._06_party.supply_drop import _kind_tables

    row = {"from": "Elf", "items": {"arrows": 500, "silver_arrows": 40}}
    assert report_supply_count(row, "arrow") == 40
    assert report_supply_count({"from": "Elf", "items": {"arrows": 10}}, "arrow") is None
    state = type(
        "S",
        (),
        {
            "player": type(
                "P",
                (),
                {
                    "inventory": type(
                        "I",
                        (),
                        {
                            "bag_ready": True,
                            "arrows": 500,
                            "silver_arrows": 40,
                            "hp_potion": 0,
                            "depoison": 0,
                            "mp_potion": 0,
                        },
                    )()
                },
            )()
        },
    )()
    assert bag_supply_counts(state)["arrow"] == 40
    ids, names = _kind_tables("arrow")
    assert SILVER_ARROW_IDS <= ids
    assert not (ARROW_IDS & ids)
    assert "은 화살" in names
    assert "화살" not in names
    shop = str(supply_shop_id("arrow") or "")
    assert "silver" in shop
    assert "normal" not in shop


def test_named_supply_pile_must_match_the_claim() -> None:
    assert supply_pile_matches(_Pile("빨간 물약"), "hp") is True
    assert supply_pile_matches(_Pile("빨간 물약"), "arrow") is False
    assert supply_pile_matches(_Pile("은 화살"), "arrow") is True
    assert supply_pile_matches(_Pile("화살"), "arrow") is False
    assert supply_pile_matches(_Pile("silver arrow"), "arrow") is True
    assert supply_pile_matches(_Pile("파란 물약"), "mp") is True
    assert supply_pile_matches(_Pile(""), "hp") is False
    assert supply_pile_qty_ok(_Pile("빨간 물약", loot_qty=10), 10) is True
    assert supply_pile_qty_ok(_Pile("빨간 물약", loot_qty=100), 10) is False
    assert supply_pile_qty_ok(_Pile("빨간 물약", loot_qty=None), 10) is True
    assert supply_pile_qty_ok(_Pile("빨간 물약", loot_qty=10), None) is True


def test_blue_potion_count_comes_from_the_bag() -> None:
    from app._03_world.merge.memory_inventory import inventory_state_from_snapshot

    bag = inventory_state_from_snapshot(
        {"items": [{"id": 492, "count": 4, "name": "파란 물약", "slot": 1}]}
    )
    assert bag.mp_potion == 4


def test_later_supply_rows_are_bought_before_returning() -> None:
    specs = _supply_specs(PartyMemberConfig(), set())
    short = {"hp": 5, "depoison": 0, "mp": 20, "arrow": 10}
    assert next_supply_buy(short, specs, after_item="hp")["item"] == "arrow"
    assert (
        next_supply_buy(
            {"hp": 5, "depoison": 5, "mp": 20, "arrow": 10},
            specs,
            after_item="hp",
        )["item"]
        == "arrow"
    )
    assert (
        next_supply_buy(short, specs, after_item="hp", skip_buys={"depoison"})["item"]
        == "arrow"
    )
    assert (
        next_supply_buy(
            {"hp": 5, "depoison": 5, "mp": 20, "arrow": 500},
            specs,
            after_item="hp",
        )
        is None
    )
    assert next_supply_buy(short, specs, after_item="arrow") is None
    board = type("Board", (), {"scratch": {"party_supply_item": "hp"}})()
    assert note_supply_shop_finished(board) is True
    assert board.scratch["party_supply_chain"] == ["hp"]
    assert "party_supply_item" not in board.scratch


def test_one_trip_buys_the_configured_count() -> None:
    assert supply_fill_qty(5, 20, 10) == 10
    assert supply_fill_qty(5, 20, 30) == 30
    assert supply_fill_qty(18, 20, 10) == 10
    assert supply_fill_qty(0, 1500, 10) == 10
    assert affordable_supply_qty(15, 100, 52) == 1
    assert affordable_supply_qty(15, 40, 52) == 0
    assert affordable_supply_qty(15, None, 52) == 15


def test_a_broke_item_is_skipped_for_the_next_buy() -> None:
    specs = _supply_specs(PartyMemberConfig(), set())
    duty = choose_supply_duty(
        {"hp": 0, "depoison": 0, "mp": 20, "arrow": 10},
        [],
        specs,
        self_name="Keeper",
        skip_buys={"hp"},
    )
    assert duty is not None
    assert duty["item"] == "arrow"


def test_party_hp_buy_qty_stays_off_solo_shops() -> None:
    assert party_shop_buy_qty(
        {
            "party_shopkeeper_arrow": True,
            "party_supply_item": "hp",
            "party_arrow_buy_qty": 20,
        },
        "buy_hp_potions_mainland",
        10,
    ) == 20
    assert party_shop_buy_qty({}, "buy_hp_potions_mainland", 10) == 10
    low = type(
        "S",
        (),
        {
            "player": type(
                "P",
                (),
                {
                    "inventory": type(
                        "I",
                        (),
                        {
                            "bag_ready": True,
                            "hp_potion": 5,
                            "depoison": 0,
                            "mp_potion": 0,
                            "arrows": 0,
                            "silver_arrows": 0,
                        },
                    )()
                },
            )()
        },
    )()
    assert party_shop_buy_qty(
        {
            "party_shopkeeper_arrow": True,
            "party_supply_item": "hp",
            "party_supply_configured": 20,
            "party_supply_keep": 50,
            "party_arrow_buy_qty": 45,
        },
        "buy_hp_potions_mainland",
        10,
        low,
    ) == 20


def test_leader_skips_arrow_shop_only_while_the_socket_is_live() -> None:
    peers = {"shop": "peer-1"}

    def peer_for(name: str) -> str:
        return peers.get(name, "")

    def awaiting(name: str) -> bool:
        return name == "shop" and peers.get("dead") == "1"

    assert shopkeeper_socket_live(["shop"], peer_for, lambda _n: False) is True
    assert shopkeeper_socket_live(["shop"], lambda _n: "", lambda _n: False) is False
    board = _Board()
    board.scratch["party_arrow_shop_covered"] = True
    assert needs_arrow_buy(board) is False
    board.scratch.pop("party_arrow_shop_covered")
    assert needs_arrow_buy(board) is True
    assert awaiting("other") is False


def test_line_hold_omits_only_a_live_shop_phase() -> None:
    rows = {
        "shop": {"live": {"phase": "shop"}},
        "gone": {"live": {"phase": "supply"}},
        "hunt": {"live": {"phase": "follow"}},
    }

    def peer_for(name: str) -> str:
        return "" if name == "gone" else "ok"

    def awaiting(name: str) -> bool:
        return name == "gone"

    assert line_omit_names(rows, peer_for, awaiting) == ["shop"]


def test_party_loot_uses_the_boss_weight_line() -> None:
    board = _Board()
    board.scratch["party_loot_pickup"] = "all"
    board.scratch["party_loot_weight"] = 0.30
    assert _party_loot_mode(_State(0.10), board) != LOOT_MODE_ADENA
    assert _party_loot_mode(_State(0.40), board) == LOOT_MODE_ADENA
    board.scratch["party_loot_pickup"] = "adena"
    assert _party_loot_mode(_State(0.10), board) == LOOT_MODE_ADENA


def test_policy_merge_keeps_arrow_and_pickup_knobs() -> None:
    cfg = PartyMemberConfig().merge_leader_policy(
        {
            "member_arrow_min": 120,
            "shopkeeper_arrow_min": 800,
            "member_arrow_give": 40,
            "shopkeeper_arrow_buy": 150,
            "loot_pickup": "adena",
            "loot_weight_pct": 45,
            "random_loot": True,
        }
    )
    assert cfg.member_arrow_min == 120
    assert cfg.shopkeeper_arrow_min == 800
    assert cfg.member_arrow_give == 40
    assert cfg.shopkeeper_arrow_buy == 150
    assert cfg.loot_pickup == "adena"
    assert cfg.loot_weight_pct == 45
    assert cfg.random_loot is True


def test_same_map_drop_converts_game_xy_before_travel() -> None:
    """Report xy is raw game. Same-map travel must get nav tiles."""
    from app._03_world.merge.memory_sync import configure_map_origin, get_map_origin
    from app._06_party import arrow_duty

    saved = get_map_origin()
    configure_map_origin(
        {"navigation": {"map_origin_x": 32448, "map_origin_y": 32128}}
    )
    goals: list[tuple[int, int]] = []
    other_map: list[tuple[int, int]] = []

    class _Pose:
        def __init__(self, map_id: int) -> None:
            self.map_id = map_id
            self.x = 33120
            self.y = 33370

    class _Origin:
        x = 672
        y = 1242

    class _Board:
        def __init__(self) -> None:
            self.world_origin = _Origin()
            self.nav_goal = None
            self.intent = None
            self.scratch: dict = {}

    class _Runtime:
        duty_phase = ""
        last_kind = ""
        last_reason = ""

    class _Manager:
        def __init__(self) -> None:
            self._nav_blackboard = _Board()
            self.runtime = _Runtime()

    import app._04_decision.behaviors.travel as travel
    import app._04_decision.world_nav.session as session

    real_pose = session.live_pose_from_state
    real_start = travel.start_travel
    real_emit = travel.emit_travel_hop
    real_nav = arrow_duty._tick_nav
    pose_map = {"id": 4}

    def _pose(_state, fresh=False):
        del fresh
        return _Pose(pose_map["id"])

    def _start(board, goal, reason=""):
        del reason
        goals.append((int(goal[0]), int(goal[1])))
        board.nav_goal = (int(goal[0]), int(goal[1]))

    def _emit(*_args, **_kwargs) -> bool:
        return False

    def _nav(_manager, _state, _map_id, x, y, *, reason):
        del reason
        other_map.append((int(x), int(y)))
        return None

    session.live_pose_from_state = _pose
    travel.start_travel = _start
    travel.emit_travel_hop = _emit
    arrow_duty._tick_nav = _nav
    try:
        manager = _Manager()
        # Game (33205, 33436) is nav (757, 1308) on this origin.
        walked = arrow_duty._beside_member(
            manager,
            object(),
            {"x": 33205, "y": 33436, "map_id": 4},
        )
        assert walked is not True
        assert goals == [(757, 1308)]
        # Already-nav report xy is left as-is.
        goals.clear()
        manager._nav_blackboard.nav_goal = None
        arrow_duty._beside_member(
            manager,
            object(),
            {"x": 757, "y": 1308, "map_id": 4},
        )
        assert goals == [(757, 1308)]
        # Within 3 tiles after conversion: stand and drop, no travel.
        goals.clear()
        beside = arrow_duty._beside_member(
            manager,
            object(),
            {"x": 33122, "y": 33372, "map_id": 4},
        )
        assert beside is True
        assert goals == []
        # Other map keeps game xy for world nav.
        pose_map["id"] = 0
        arrow_duty._beside_member(
            manager,
            object(),
            {"x": 33205, "y": 33436, "map_id": 4},
        )
        assert other_map == [(33205, 33436)]
    finally:
        session.live_pose_from_state = real_pose
        travel.start_travel = real_start
        travel.emit_travel_hop = real_emit
        arrow_duty._tick_nav = real_nav
        configure_map_origin(
            {
                "navigation": {
                    "map_origin_x": saved[0],
                    "map_origin_y": saved[1],
                }
            }
        )


def test_a_class_mage_is_skipped_for_arrows() -> None:
    roster = [
        {"name": "Elf", "role": "mage"},
        {"name": "Wizard", "role": "member"},
    ]
    party = {
        "in_party": True,
        "members": [
            {"name": "Wizard", "type": "마법사"},
            {"name": "Elf", "type": "요정"},
        ],
    }
    names = mp_recipient_names(roster, party)
    assert names == {"elf", "wizard"}
    specs = _supply_specs(PartyMemberConfig(), names)
    full = {"hp": 30, "depoison": 5, "mp": 20, "arrow": 500}

    def _row(name: str, mp: int, arrows: int) -> dict:
        return {
            "from": name,
            "items": {
                "hp_potion": 40,
                "depoison": 5,
                "mp_potion": mp,
                "arrows": 900,
                "silver_arrows": arrows,
            },
            "map_id": 4,
            "x": 1,
            "y": 1,
        }

    arrows = choose_supply_duty(
        full,
        [_row("Wizard", 0, 0), _row("Elf", 0, 0), _row("Boss", 0, 0)],
        specs,
        self_name="Keeper",
    )
    assert arrows is not None
    assert arrows["item"] == "arrow"
    assert arrows["name"] == "Boss"
    again = choose_supply_duty(
        full,
        [_row("Wizard", 20, 0), _row("Elf", 20, 0), _row("Boss", 20, 0)],
        specs,
        self_name="Keeper",
    )
    assert again is not None
    assert again["item"] == "arrow"
    assert again["name"] == "Boss"


def test_a_drop_updates_the_count_until_the_report_changes() -> None:
    book: dict = {}
    assert remember_delivered(book, "Elf", "arrow", 250, 100) == 350
    row = {
        "from": "Elf",
        "items": {
            "arrows": 900,
            "silver_arrows": 250,
            "hp_potion": 40,
            "depoison": 5,
            "mp_potion": 20,
        },
    }
    adjusted = rows_with_expected([row], book)
    assert report_supply_count(adjusted[0], "arrow") == 350
    assert adjusted[0]["items"]["arrows"] == 900
    assert row["items"]["silver_arrows"] == 250
    again = rows_with_expected([row], book)
    assert report_supply_count(again[0], "arrow") == 350
    caught = {
        "from": "Elf",
        "items": dict(row["items"], silver_arrows=260),
    }
    fresh = rows_with_expected([caught], book)
    assert report_supply_count(fresh[0], "arrow") == 260
    assert book == {}


def test_a_covered_spare_still_drops_and_a_short_spare_buys() -> None:
    specs = _supply_specs(PartyMemberConfig(), set())
    short = {
        "from": "Elf",
        "items": {
            "hp_potion": 0,
            "depoison": 5,
            "mp_potion": 20,
            "arrows": 500,
            "silver_arrows": 0,
        },
        "map_id": 4,
        "x": 1,
        "y": 1,
    }
    bag = {"hp": 30, "depoison": 5, "mp": 20, "arrow": 500}
    drop = choose_supply_duty(bag, [short], specs, self_name="Keeper")
    assert drop is not None
    assert drop["kind"] == "drop"
    assert drop["item"] == "hp"
    still = choose_supply_duty(
        {"hp": 25, "depoison": 5, "mp": 20, "arrow": 500},
        [short],
        specs,
        self_name="Keeper",
    )
    assert still is not None
    assert still["kind"] == "drop"
    buy = choose_supply_duty(
        {"hp": 20, "depoison": 5, "mp": 20, "arrow": 500},
        [short],
        specs,
        self_name="Keeper",
    )
    assert buy["kind"] == "buy"
    assert buy["party_need"] == 10
    assert buy["buy"] == 20
    full = {
        "from": "Elf",
        "items": dict(short["items"], hp_potion=40),
    }
    reserve = choose_supply_duty(
        {"hp": 5, "depoison": 5, "mp": 20, "arrow": 500},
        [full],
        specs,
        self_name="Keeper",
    )
    assert reserve["kind"] == "buy"
    assert reserve["party_need"] == 0
    assert reserve["buy"] == 20


def test_party_supply_does_not_handle_mp() -> None:
    specs = _supply_specs(PartyMemberConfig(), {"mage"})
    assert [row["item"] for row in specs] == ["hp", "arrow"]
    duty = choose_supply_duty(
        {"hp": 30, "depoison": 5, "mp": 0, "arrow": 500},
        [
            {
                "from": "Mage",
                "items": {
                    "hp_potion": 40,
                    "depoison": 5,
                    "mp_potion": 0,
                    "arrows": 500,
                    "silver_arrows": 400,
                },
                "map_id": 4,
                "x": 1,
                "y": 1,
            }
        ],
        specs,
        self_name="Keeper",
    )
    assert duty is None


def test_brains_adopt_the_manager_and_the_session_keeps_it() -> None:
    from pathlib import Path

    from app._06_party.brains import MageBrain, ShopkeeperBrain

    class _Mgr:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, _state: object) -> object:
            self.calls += 1
            return type("I", (), {"reason": "from-manager"})()

    mgr = _Mgr()
    shop = ShopkeeperBrain(manager=mgr).adopt(object())
    mage = MageBrain(manager=mgr).adopt(object())
    assert shop.ready is True and shop.intent.reason == "from-manager"
    assert mage.ready is True and mage.intent.reason == "from-manager"
    assert mgr.calls == 2
    text = Path("session/bot_controller.py").read_text(encoding="utf-8")
    assert "ShopkeeperBrain" not in text
    assert "MageBrain" not in text
    assert "PartyMemberManager" in text


if __name__ == "__main__":
    test_shopkeeper_does_not_take_ground_loot()
    test_random_loot_still_available_for_a_normal_seat()
    test_short_shopkeeper_buys_before_dropping()
    test_drop_qty_keeps_the_shopkeeper_reserve()
    test_drop_uses_the_boss_give_count()
    test_mage_seat_is_not_an_arrow_target()
    test_party_buy_qty_does_not_replace_solo()
    test_potions_come_before_arrows_and_mp_stays_on_the_mage()
    test_party_supply_reads_silver_arrows_only()
    test_named_supply_pile_must_match_the_claim()
    test_blue_potion_count_comes_from_the_bag()
    test_later_supply_rows_are_bought_before_returning()
    test_one_trip_buys_the_configured_count()
    test_a_broke_item_is_skipped_for_the_next_buy()
    test_party_hp_buy_qty_stays_off_solo_shops()
    test_leader_skips_arrow_shop_only_while_the_socket_is_live()
    test_line_hold_omits_only_a_live_shop_phase()
    test_party_loot_uses_the_boss_weight_line()
    test_policy_merge_keeps_arrow_and_pickup_knobs()
    test_same_map_drop_converts_game_xy_before_travel()
    test_a_class_mage_keeps_mp_when_the_seat_is_not_mage()
    test_a_drop_updates_the_count_until_the_report_changes()
    test_a_covered_spare_still_drops_and_a_short_spare_buys()
    test_mp_is_not_bought_without_a_shop_behavior()
    test_brains_adopt_the_manager_and_the_session_keeps_it()
    print("ok")
