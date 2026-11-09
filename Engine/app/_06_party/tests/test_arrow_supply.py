"""Party arrow supply decisions. No game client."""
from __future__ import annotations

from app._04_decision.player_mode import LOOT_MODE_ADENA
from app._04_decision.shop_trip import needs_arrow_buy
from app._06_party.arrow_policy import (
    line_omit_names,
    party_shop_buy_qty,
    pick_arrow_duty,
    shopkeeper_socket_live,
)
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
    test_party_buy_qty_does_not_replace_solo()
    test_leader_skips_arrow_shop_only_while_the_socket_is_live()
    test_line_hold_omits_only_a_live_shop_phase()
    test_party_loot_uses_the_boss_weight_line()
    test_policy_merge_keeps_arrow_and_pickup_knobs()
    print("ok")
