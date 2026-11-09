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
    party_shop_buy_qty,
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
        [{"from": "Elf", "items": {"arrows": 50, "silver_arrows": 0}, "map_id": 4, "x": 3, "y": 4}],
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
        [{"from": "Elf", "items": {"arrows": 290}, "map_id": 4, "x": 3, "y": 4}],
        member_min=300,
        keeper_min=300,
        give_qty=80,
        self_name="Keeper",
    )
    assert duty is not None
    assert duty["qty"] == 80
    short = pick_arrow_duty(
        320,
        [{"from": "Elf", "items": {"arrows": 10}, "map_id": 4, "x": 3, "y": 4}],
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
        {"from": "Mage", "items": {"arrows": 0}, "map_id": 4, "x": 1, "y": 1},
        {"from": "Boss", "items": {"arrows": 10}, "map_id": 4, "x": 2, "y": 2},
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


def test_potions_come_before_arrows_and_mp_stays_on_the_mage() -> None:
    specs = _supply_specs(PartyMemberConfig(), {"mage"})
    assert [row["item"] for row in specs] == ["hp", "depoison", "mp", "arrow"]
    assert specs[2]["can_buy"] is False
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
    assert buy["buy"] == 20
    assert buy["keeper_min"] == 20
    rows = _supply_rows()
    for row in rows:
        row["items"]["hp_potion"] = 40
        row["items"]["depoison"] = 5
    mp = choose_supply_duty(full, rows, specs, self_name="Keeper")
    assert mp is not None
    assert mp["item"] == "mp"
    assert mp["name"] == "Mage"
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


def test_named_supply_pile_must_match_the_claim() -> None:
    assert supply_pile_matches(_Pile("빨간 물약"), "hp") is True
    assert supply_pile_matches(_Pile("빨간 물약"), "arrow") is False
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
    assert next_supply_buy(short, specs, after_item="hp")["item"] == "depoison"
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


def test_one_trip_buys_enough_to_reach_the_reserve() -> None:
    assert supply_fill_qty(5, 20, 10) == 15
    assert supply_fill_qty(5, 20, 30) == 30
    assert supply_fill_qty(18, 20, 10) == 10
    assert supply_fill_qty(0, 1500, 10) == 999
    assert affordable_supply_qty(15, 100, 52) == 1
    assert affordable_supply_qty(15, 40, 52) == 0
    assert affordable_supply_qty(15, None, 52) == 15


def test_a_broke_item_is_skipped_for_the_next_buy() -> None:
    specs = _supply_specs(PartyMemberConfig(), set())
    duty = choose_supply_duty(
        {"hp": 0, "depoison": 0, "mp": 20, "arrow": 500},
        [],
        specs,
        self_name="Keeper",
        skip_buys={"hp"},
    )
    assert duty is not None
    assert duty["item"] == "depoison"


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


if __name__ == "__main__":
    test_shopkeeper_does_not_take_ground_loot()
    test_random_loot_still_available_for_a_normal_seat()
    test_short_shopkeeper_buys_before_dropping()
    test_drop_qty_keeps_the_shopkeeper_reserve()
    test_drop_uses_the_boss_give_count()
    test_mage_seat_is_not_an_arrow_target()
    test_party_buy_qty_does_not_replace_solo()
    test_potions_come_before_arrows_and_mp_stays_on_the_mage()
    test_named_supply_pile_must_match_the_claim()
    test_blue_potion_count_comes_from_the_bag()
    test_later_supply_rows_are_bought_before_returning()
    test_one_trip_buys_enough_to_reach_the_reserve()
    test_a_broke_item_is_skipped_for_the_next_buy()
    test_party_hp_buy_qty_stays_off_solo_shops()
    test_leader_skips_arrow_shop_only_while_the_socket_is_live()
    test_line_hold_omits_only_a_live_shop_phase()
    test_party_loot_uses_the_boss_weight_line()
    test_policy_merge_keeps_arrow_and_pickup_knobs()
    print("ok")
