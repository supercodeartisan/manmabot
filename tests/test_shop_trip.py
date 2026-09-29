"""Live shop trip: arrival, min-stock triggers, and buy quantities."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app._03_world.memory_inventory import refresh_shop_needs_from_inventory
from app._03_world.objects import Position
from app._03_world.player import InventoryState, PlayerState
from app._03_world.world_coords import WorldOrigin
from app._04_decision.blackboard import Blackboard
from app._04_decision import shops as shops_mod
from app._04_decision.shop_trip import SCRATCH_SHOP_SCROLLED, _at_shop
from app._04_decision.talking_scroll import (
    SCRATCH_SCROLL_ARRIVAL,
    SCRATCH_SCROLL_SPOT,
    apply_talking_scroll_arrival,
)
from app._05_action.controller import ActionExecutor


def test_scroll_arrival_does_not_zero_player_origin(monkeypatch):
    called: dict[str, str] = {}

    def fake_origin(config, map_id):
        called["map"] = map_id
        return WorldOrigin(x=0, y=0)

    monkeypatch.setattr(
        "app._03_world.map_pack.get_active_map_pack",
        lambda: SimpleNamespace(id="talking_island"),
    )
    monkeypatch.setattr(
        "app._04_decision.nav_config.configure_map_origin_for_map",
        fake_origin,
    )
    monkeypatch.setattr(
        "app._04_decision.nav_config.start_configure_navigation_for_map_async",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "app._04_decision.behaviors.travel.clear_travel",
        lambda bb: None,
    )
    monkeypatch.setattr(
        "app._04_decision.farm_time.reset_farm_timer",
        lambda bb: None,
    )

    board = Blackboard()
    board.world_origin = WorldOrigin(x=120, y=340)
    board.scratch[SCRATCH_SCROLL_ARRIVAL] = True
    board.scratch[SCRATCH_SCROLL_SPOT] = "giran_general_goods"

    assert apply_talking_scroll_arrival(board, {"navigation": {}}) is True
    assert called["map"] == "mainland"
    assert board.world_origin.x == 120
    assert board.world_origin.y == 340
    board.scratch[SCRATCH_SCROLL_ARRIVAL] = True
    board.scratch[SCRATCH_SCROLL_SPOT] = "giran_general_goods"
    assert apply_talking_scroll_arrival(board, {"navigation": {}}) is True
    assert called == {"map": "mainland"}


def test_at_shop_uses_raw_world_coords(monkeypatch):
    board = Blackboard()
    behavior = SimpleNamespace(npc_world_x=33455, npc_world_y=32820)
    state = SimpleNamespace(
        last_print_state={"player": {"x": 33454, "y": 32819}},
        last_memory_snapshot=None,
    )
    monkeypatch.setattr(
        "manmabot_v1.shopping.runtime.close_enough_to_click",
        lambda _origin, _behavior: False,
    )
    assert _at_shop(state, board, behavior) is True
    state.last_print_state = {"player": {"x": 32642, "y": 32946}}
    assert _at_shop(state, board, behavior) is False
    board.scratch[SCRATCH_SHOP_SCROLLED] = True
    state.last_print_state = {"player": {"x": 33450, "y": 32810}}
    assert _at_shop(state, board, behavior) is True


def test_open_shop_uses_behavior_map_origin_for_both_ends():
    from app._03_world.memory_sync import get_map_origin
    from manmabot_v1.shopping.runtime import (
        ensure_behavior_map_origin,
        npc_content_uv,
        player_game_xy,
        world_near_shop,
    )

    behavior = SimpleNamespace(
        map_id="mainland",
        npc_world_x=33455,
        npc_world_y=32820,
    )
    ensure_behavior_map_origin(behavior)
    ox, oy = get_map_origin()
    assert ox == 32448
    assert oy == 32128
    origin = SimpleNamespace(x=33454 - ox, y=32819 - oy)
    uv = npc_content_uv(behavior, origin)
    assert uv is not None
    world = SimpleNamespace(
        last_print_state={"player": {"x": 33454, "y": 32819}},
        last_memory_snapshot=None,
    )
    assert player_game_xy(world) == (33454, 32819)
    assert world_near_shop(world, behavior) is True


def test_giran_npc_pick_uses_closest_live_entity():
    from manmabot_v1.shopping.runtime import shop_npc_memory_hit

    behavior = SimpleNamespace(npc_world_x=33455, npc_world_y=32820)
    world = SimpleNamespace(
        last_print_entities=[
            {
                "classification": "npc",
                "world_cx": 33453,
                "world_cy": 32818,
                "world_rx": 4,
                "world_ry": 2,
            },
            {
                "classification": "npc",
                "world_cx": 33455,
                "world_cy": 32820,
                "world_rx": 2,
                "world_ry": 1,
            },
            {
                "classification": "monster",
                "world_cx": 33455,
                "world_cy": 32820,
                "world_rx": 0,
                "world_ry": 0,
            },
        ],
        npcs=lambda: [],
    )
    hit = shop_npc_memory_hit(world, behavior)
    assert hit["world_rx"] == 2
    assert hit["world_cy"] == 32820


def test_shop_trip_emits_talking_scroll_before_walk(monkeypatch):
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import tick_shop_trip

    behavior = SimpleNamespace(
        scroll_spot="ti_general_goods",
        map_id="talking_island",
        npc_world_x=32680,
        npc_world_y=32810,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.choose_shopping_behavior",
        lambda *_a, **_k: "buy_hp_potions_talking",
    )
    monkeypatch.setattr("app._04_decision.shop_trip._load_behavior", lambda *_a, **_k: behavior)
    monkeypatch.setattr("app._04_decision.shop_trip._at_shop", lambda *_a, **_k: False)
    monkeypatch.setattr("app._04_decision.shop_trip._can_scroll", lambda *_a, **_k: True)
    monkeypatch.setattr("app._04_decision.shop_trip._can_walk", lambda *_a, **_k: True)

    walked: list[object] = []
    monkeypatch.setattr(
        "app._04_decision.mode_control.begin_travel",
        lambda *a, **k: walked.append((a, k)),
    )

    def fake_emit(blackboard, **kwargs):
        blackboard.emit(ActionType.USE_TALKING_SCROLL, reason=str(kwargs.get("reason") or ""))
        return Status.SUCCESS

    monkeypatch.setattr("app._04_decision.shop_trip.emit_talking_scroll", fake_emit)
    monkeypatch.setattr("app._04_decision.behaviors.travel.clear_travel", lambda *_a, **_k: None)

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    status = tick_shop_trip(SimpleNamespace(), board)
    assert status is Status.SUCCESS
    assert board.scratch.get(SCRATCH_SHOP_SCROLLED) is True
    assert walked == []
    assert board.intent is not None
    assert board.intent.action == ActionType.USE_TALKING_SCROLL


def test_shop_trip_after_scroll_waits_until_live_landing(monkeypatch):
    """After the hop, do not click the stall on the old map."""
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import tick_shop_trip

    behavior = SimpleNamespace(
        scroll_spot="giran_general_goods",
        map_id="mainland",
        npc_world_x=33455,
        npc_world_y=32820,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.choose_shopping_behavior",
        lambda *_a, **_k: "buy_hp_potions_ch_mainland",
    )
    monkeypatch.setattr("app._04_decision.shop_trip._load_behavior", lambda *_a, **_k: behavior)
    monkeypatch.setattr("app._04_decision.shop_trip._at_shop", lambda *_a, **_k: False)
    monkeypatch.setattr("app._04_decision.shop_trip._can_scroll", lambda *_a, **_k: True)
    monkeypatch.setattr("app._04_decision.shop_trip._can_walk", lambda *_a, **_k: True)

    walked: list[object] = []
    monkeypatch.setattr(
        "app._04_decision.mode_control.begin_travel",
        lambda *a, **k: walked.append((a, k)),
    )
    emitted: list[object] = []
    monkeypatch.setattr(
        "app._04_decision.shop_trip.emit_talking_scroll",
        lambda *_a, **_k: emitted.append("scroll") or Status.SUCCESS,
    )

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    board.scratch[SCRATCH_SHOP_SCROLLED] = True
    status = tick_shop_trip(
        SimpleNamespace(last_print_state={"player": {"x": 32580, "y": 32950}}),
        board,
    )
    assert status is Status.SUCCESS
    assert walked == []
    assert emitted == []
    assert board.intent is not None
    assert board.intent.action == ActionType.IDLE
    assert "waiting for shop landing" in str(board.intent.reason)


def test_shop_trip_after_scroll_opens_npc_like_practice(monkeypatch):
    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import tick_shop_trip

    behavior = SimpleNamespace(
        scroll_spot="giran_general_goods",
        map_id="mainland",
        npc_world_x=33455,
        npc_world_y=32820,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.choose_shopping_behavior",
        lambda *_a, **_k: "buy_hp_potions_mainland",
    )
    monkeypatch.setattr("app._04_decision.shop_trip._load_behavior", lambda *_a, **_k: behavior)
    monkeypatch.setattr("app._04_decision.shop_trip._can_scroll", lambda *_a, **_k: True)
    monkeypatch.setattr("app._04_decision.shop_trip._can_walk", lambda *_a, **_k: True)

    walked: list[object] = []
    monkeypatch.setattr(
        "app._04_decision.mode_control.begin_travel",
        lambda *a, **k: walked.append((a, k)),
    )

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    board.scratch[SCRATCH_SHOP_SCROLLED] = True
    state = SimpleNamespace(last_print_state={"player": {"x": 33440, "y": 32805}})
    status = tick_shop_trip(state, board)
    assert status is Status.SUCCESS
    assert walked == []
    assert board.intent is not None
    assert board.intent.action == ActionType.SHOP_STOP

    status = tick_shop_trip(state, board)
    assert status is Status.SUCCESS
    assert walked == []
    assert board.intent is not None
    assert board.intent.action == ActionType.SHOP_BUY_ARROWS
    assert board.intent.shop_behavior_id == "buy_hp_potions_mainland"


def test_shop_trip_walks_only_when_scroll_unavailable(monkeypatch):
    """Practice walks only when talking scroll cannot fire and maps match."""
    from app._04_decision.behavior_tree import Status
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import tick_shop_trip

    behavior = SimpleNamespace(
        scroll_spot="giran_general_goods",
        map_id="mainland",
        npc_world_x=33455,
        npc_world_y=32820,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.choose_shopping_behavior",
        lambda *_a, **_k: "buy_hp_potions_ch_mainland",
    )
    monkeypatch.setattr("app._04_decision.shop_trip._load_behavior", lambda *_a, **_k: behavior)
    monkeypatch.setattr("app._04_decision.shop_trip._at_shop", lambda *_a, **_k: False)
    monkeypatch.setattr("app._04_decision.shop_trip._can_scroll", lambda *_a, **_k: False)
    monkeypatch.setattr("app._04_decision.shop_trip._can_walk", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "manmabot_v1.shopping.runtime.shop_nav_tile",
        lambda *_a, **_k: (900, 680),
    )

    walked: list[object] = []
    monkeypatch.setattr(
        "app._04_decision.mode_control.begin_travel",
        lambda *a, **k: walked.append((a, k)),
    )

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    status = tick_shop_trip(SimpleNamespace(), board)
    assert status is Status.FAILURE
    assert walked
    assert walked[0][1]["purpose"] == "shop"
    assert "walk to shop" in str(walked[0][1]["reason"])


def test_shopping_blocks_teleport_during_shop_wait():
    from app._04_decision.shop_trip import shopping_blocks_teleport
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    board = Blackboard()
    assert shopping_blocks_teleport(board) is False
    board.scratch[SCRATCH_SHOP_TRIP] = True
    assert shopping_blocks_teleport(board) is True


def test_shop_landing_timeout_retries_then_clears(monkeypatch):
    import time

    from app._03_world import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.shop_trip import (
        SCRATCH_SHOP_SCROLLED,
        SCRATCH_SHOP_SCROLLED_AT,
        SCRATCH_SHOP_SCROLL_RETRIES,
        SHOP_LANDING_WAIT_S,
        tick_shop_trip,
    )
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    behavior = SimpleNamespace(
        scroll_spot="giran_general_goods",
        map_id="mainland",
        npc_world_x=33455,
        npc_world_y=32820,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.choose_shopping_behavior",
        lambda *_a, **_k: "buy_hp_potions_mainland",
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip._load_behavior", lambda *_a, **_k: behavior
    )
    monkeypatch.setattr("app._04_decision.shop_trip._at_shop", lambda *_a, **_k: False)
    monkeypatch.setattr("app._04_decision.shop_trip._can_scroll", lambda *_a, **_k: True)
    monkeypatch.setattr("app._04_decision.shop_trip._can_walk", lambda *_a, **_k: False)

    scrolled: list[str] = []

    def fake_scroll(blackboard, **kwargs):
        scrolled.append(str(kwargs.get("reason") or ""))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.shop_trip.emit_talking_scroll", fake_scroll
    )

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    board.scratch[SCRATCH_SHOP_TRIP] = True
    board.scratch[SCRATCH_SHOP_SCROLLED] = True
    board.scratch[SCRATCH_SHOP_SCROLLED_AT] = time.time() - (
        float(SHOP_LANDING_WAIT_S) + 1.0
    )
    board.scratch[SCRATCH_SHOP_SCROLL_RETRIES] = 0

    status = tick_shop_trip(SimpleNamespace(), board)
    assert status is Status.SUCCESS
    assert scrolled  # retry scroll
    assert board.scratch.get(SCRATCH_SHOP_SCROLLED) is True
    assert int(board.scratch.get(SCRATCH_SHOP_SCROLL_RETRIES) or 0) == 1

    board.scratch[SCRATCH_SHOP_SCROLLED_AT] = time.time() - (
        float(SHOP_LANDING_WAIT_S) + 1.0
    )
    board.scratch[SCRATCH_SHOP_SCROLL_RETRIES] = 2
    scrolled.clear()
    status = tick_shop_trip(SimpleNamespace(), board)
    assert status is Status.SUCCESS
    assert scrolled == []
    assert board.scratch.get(SCRATCH_SHOP_TRIP) is None
    assert board.intent is not None
    assert board.intent.action == ActionType.IDLE
    assert "shop landing timeout" in str(board.intent.reason)


def test_confined_escape_skips_during_shop_wait(monkeypatch):
    from app._04_decision.behaviors.mode_ticks import _maybe_confined_escape
    from app._04_decision.talking_scroll import SCRATCH_SHOP_TRIP

    called: list[bool] = []
    monkeypatch.setattr(
        "app._04_decision.behaviors.unstick.try_confined_escape",
        lambda *_a, **_k: called.append(True) or True,
    )
    board = Blackboard()
    board.scratch[SCRATCH_SHOP_TRIP] = True
    assert _maybe_confined_escape(SimpleNamespace(), board) is None
    assert called == []


def test_talking_scroll_shop_wait_covers_mainland_reason():
    action = SimpleNamespace(
        reason="go to shop (buy_hp_potions_mainland)",
        destination=None,
    )
    assert ActionExecutor._talking_scroll_is_shop(action) is True


def test_live_resolves_only_sample_yaml_behaviors():
    from manmabot_v1.shopping.behaviors import load_behaviors

    sample_ids = {item.id for item in load_behaviors()}
    saved = {
        "SHOP_LOCALE": shops_mod.SHOP_LOCALE,
        "HP_POTION_NPC": shops_mod.HP_POTION_NPC,
        "SELL_MODE": shops_mod.SELL_MODE,
    }
    try:
        for locale in ("ko", "zh"):
            shops_mod.SHOP_LOCALE = locale
            for npc in ("talking", "mainland"):
                shops_mod.HP_POTION_NPC = npc
                for kind in ("hp", "depoison", "normal_arrows", "silver_arrows"):
                    bid = shops_mod.resolve_shopping_behavior_id(kind)
                    assert bid in sample_ids, bid
            for mode in ("sell_only_garbage", "sell_except_keep"):
                shops_mod.SELL_MODE = mode
                for bid in shops_mod.resolve_sell_behavior_ids():
                    assert bid in sample_ids, bid
    finally:
        _restore_shop_globals(saved)


def test_min_stock_and_buy_qty_follow_ui_settings():
    saved = {
        "ARROW_BUY_QTY": shops_mod.ARROW_BUY_QTY,
        "SILVER_ARROW_BUY_QTY": shops_mod.SILVER_ARROW_BUY_QTY,
        "HP_POTION_BUY_QTY": shops_mod.HP_POTION_BUY_QTY,
        "RETURN_POTION_ENABLED": shops_mod.RETURN_POTION_ENABLED,
        "RETURN_POTION_COUNT": shops_mod.RETURN_POTION_COUNT,
        "RESTOCK_POTIONS": shops_mod.RESTOCK_POTIONS,
        "RETURN_ARROW_ENABLED": shops_mod.RETURN_ARROW_ENABLED,
        "RETURN_ARROW_COUNT": shops_mod.RETURN_ARROW_COUNT,
        "BUY_NORMAL_ARROWS": shops_mod.BUY_NORMAL_ARROWS,
        "BUY_SILVER_ARROWS": shops_mod.BUY_SILVER_ARROWS,
        "BUY_DEPOISON": shops_mod.BUY_DEPOISON,
        "RETURN_DEPOISON_ENABLED": shops_mod.RETURN_DEPOISON_ENABLED,
    }
    try:
        shops_mod.ARROW_BUY_QTY = 250
        shops_mod.SILVER_ARROW_BUY_QTY = 80
        shops_mod.HP_POTION_BUY_QTY = 40
        assert shops_mod.buy_qty_for_behavior("buy_normal_arrows_talking") == 250
        assert shops_mod.buy_qty_for_behavior("buy_silver_arrows_mainland") == 80
        assert shops_mod.buy_qty_for_behavior("buy_hp_potions_talking") == 40
        assert shops_mod.buy_qty_for_behavior("buy_hp_potions_ch_mainland") == 40
        assert shops_mod.affordable_hp_potion_qty(40, 52 * 40 + 1) == 40
        assert shops_mod.affordable_hp_potion_qty(40, 52 * 10) == 10
        assert shops_mod.affordable_hp_potion_qty(40, 51) == 0
        assert shops_mod.affordable_hp_potion_qty(40, None) == 40

        shops_mod.RESTOCK_POTIONS = True
        shops_mod.RETURN_POTION_ENABLED = True
        shops_mod.RETURN_POTION_COUNT = 20
        shops_mod.BUY_NORMAL_ARROWS = True
        shops_mod.BUY_SILVER_ARROWS = False
        shops_mod.RETURN_ARROW_ENABLED = True
        shops_mod.RETURN_ARROW_COUNT = 300
        shops_mod.BUY_DEPOISON = False
        shops_mod.RETURN_DEPOISON_ENABLED = False

        board = Blackboard()
        player = PlayerState(
            track_id=0,
            position=Position.zero(),
            inventory=InventoryState(
                hp_potion=20,
                arrows=300,
                bag_ready=True,
            ),
        )
        world = SimpleNamespace(player=player)
        refresh_shop_needs_from_inventory(world, board)
        assert board.needs_potion is True
        assert board.needs_arrows is True

        player.inventory.hp_potion = 21
        player.inventory.arrows = 301
        refresh_shop_needs_from_inventory(world, board)
        assert board.needs_potion is False
        assert board.needs_arrows is False
    finally:
        for key, value in saved.items():
            setattr(shops_mod, key, value)


def test_potion_trip_skipped_when_adena_cannot_buy_one():
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.shop_trip import choose_shopping_behavior

    board = Blackboard()
    board.needs_potion = True
    player = PlayerState(
        track_id=0,
        position=Position.zero(),
        inventory=InventoryState(adena=51, bag_ready=True, hp_potion=0),
    )
    world = SimpleNamespace(player=player)
    saved = shops_mod.RESTOCK_POTIONS
    try:
        shops_mod.RESTOCK_POTIONS = True
        assert choose_shopping_behavior(world, board) is None
        assert board.needs_potion is False
        player.inventory.adena = 52
        board.needs_potion = True
        assert choose_shopping_behavior(world, board) is not None
    finally:
        shops_mod.RESTOCK_POTIONS = saved


def _restore_shop_globals(saved: dict) -> None:
    for key, value in saved.items():
        setattr(shops_mod, key, value)


def test_resolve_sell_behavior_ids_by_mode_and_locale():
    saved = {
        "SHOP_LOCALE": shops_mod.SHOP_LOCALE,
        "SELL_MODE": shops_mod.SELL_MODE,
    }
    try:
        shops_mod.SHOP_LOCALE = "ko"
        shops_mod.SELL_MODE = "sell_only_garbage"
        assert shops_mod.resolve_sell_behavior_ids() == (
            "sell_garbage",
            "sell_garbage_weapon",
            "sell_garbage_mainland",
            "sell_garbage_armor_mainland",
        )
        shops_mod.SELL_MODE = "sell_except_keep"
        assert shops_mod.resolve_sell_behavior_ids() == (
            "sell_except_keep",
            "sell_except_keep_weapon",
            "sell_except_keep_mainland",
            "sell_except_keep_armor_mainland",
        )
        shops_mod.SHOP_LOCALE = "zh"
        shops_mod.SELL_MODE = "sell_only_garbage"
        assert shops_mod.resolve_sell_behavior_ids() == (
            "sell_garbage_ch",
            "sell_garbage_weapon_ch",
            "sell_garbage_mainland_ch",
            "sell_garbage_armor_mainland_ch",
        )
        shops_mod.SELL_MODE = "sell_except_keep"
        assert shops_mod.resolve_sell_behavior_ids() == (
            "sell_except_keep_ch",
            "sell_except_keep_weapon_ch",
            "sell_except_keep_mainland_ch",
            "sell_except_keep_armor_mainland_ch",
        )
    finally:
        _restore_shop_globals(saved)


def test_needs_sell_uses_recovery_weight_gauge():
    from app._04_decision.shop_trip import needs_sell

    saved = {
        "RETURN_WEIGHT_ENABLED": shops_mod.RETURN_WEIGHT_ENABLED,
        "SELL_WEIGHT_RATIO": shops_mod.SELL_WEIGHT_RATIO,
    }
    try:
        shops_mod.RETURN_WEIGHT_ENABLED = True
        shops_mod.SELL_WEIGHT_RATIO = 0.30
        player = PlayerState(
            track_id=0,
            position=Position.zero(),
            weight=400.0,
            max_weight=1000.0,
            inventory=InventoryState(weight_ratio=0.10),
        )
        world = SimpleNamespace(player=player)
        assert needs_sell(world) is True
        world.player = replace(player, weight=200.0)
        assert needs_sell(world) is False
        shops_mod.RETURN_WEIGHT_ENABLED = False
        world.player = replace(player, weight=900.0)
        assert needs_sell(world) is False
        shops_mod.RETURN_WEIGHT_ENABLED = True
        world.player = PlayerState(
            track_id=0,
            position=Position.zero(),
            weight=0.0,
            max_weight=0.0,
            inventory=InventoryState(weight_ratio=0.35),
        )
        assert needs_sell(world) is True
    finally:
        _restore_shop_globals(saved)


def test_overweight_starts_sell_even_when_buy_is_also_needed():
    from app._04_decision.shop_trip import (
        SCRATCH_SELL_QUEUE,
        choose_shopping_behavior,
        clear_shop_trip,
    )

    saved = {
        "RETURN_WEIGHT_ENABLED": shops_mod.RETURN_WEIGHT_ENABLED,
        "SELL_WEIGHT_RATIO": shops_mod.SELL_WEIGHT_RATIO,
        "SELL_MODE": shops_mod.SELL_MODE,
        "SHOP_LOCALE": shops_mod.SHOP_LOCALE,
        "RESTOCK_POTIONS": shops_mod.RESTOCK_POTIONS,
        "BUY_NORMAL_ARROWS": shops_mod.BUY_NORMAL_ARROWS,
        "BUY_SILVER_ARROWS": shops_mod.BUY_SILVER_ARROWS,
    }
    try:
        shops_mod.RETURN_WEIGHT_ENABLED = True
        shops_mod.SELL_WEIGHT_RATIO = 0.30
        shops_mod.SELL_MODE = "sell_only_garbage"
        shops_mod.SHOP_LOCALE = "zh"
        shops_mod.RESTOCK_POTIONS = True
        shops_mod.BUY_NORMAL_ARROWS = True
        shops_mod.BUY_SILVER_ARROWS = False
        board = Blackboard()
        board.needs_potion = True
        board.needs_arrows = True
        player = PlayerState(
            track_id=0,
            position=Position.zero(),
            weight=400.0,
            max_weight=1000.0,
            inventory=InventoryState(weight_ratio=0.40),
        )
        world = SimpleNamespace(player=player)
        assert choose_shopping_behavior(world, board) == "sell_garbage_ch"
        assert board.scratch[SCRATCH_SELL_QUEUE] == [
            "sell_garbage_weapon_ch",
            "sell_garbage_mainland_ch",
            "sell_garbage_armor_mainland_ch",
        ]
        clear_shop_trip(board)
        shops_mod.SHOP_LOCALE = "ko"
        shops_mod.SELL_MODE = "sell_except_keep"
        assert choose_shopping_behavior(world, board) == "sell_except_keep"
        assert board.scratch[SCRATCH_SELL_QUEUE] == [
            "sell_except_keep_weapon",
            "sell_except_keep_mainland",
            "sell_except_keep_armor_mainland",
        ]
    finally:
        _restore_shop_globals(saved)


def test_player_off_selected_map_when_nav_tile_is_outside_terrain(monkeypatch):
    from app._04_decision.talking_scroll import player_on_selected_map

    terrain = SimpleNamespace(width=80, height=80)
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map", lambda: terrain
    )
    monkeypatch.setattr("app._04_decision.nav_config.get_farm_areas", lambda: [])
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_active_farm", lambda *_a, **_k: None
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=1200, y=40)
    assert player_on_selected_map(board) is False
    board.world_origin = WorldOrigin(x=10, y=10)
    assert player_on_selected_map(board) is True


def test_off_hunt_map_uses_talking_scroll(monkeypatch):
    from app._03_world.enums import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HUNT_MAP_SCROLL_AT

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.player_on_selected_map",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.nav_config.navigation_configure_in_progress",
        lambda: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.talking_scroll_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.farm_return_scroll_spot",
        lambda *_a, **_k: "ti_teleporter",
    )

    fired: list[str] = []

    def fake_emit(blackboard, **kwargs):
        fired.append(str(kwargs.get("spot_id") or ""))
        blackboard.emit(ActionType.USE_TALKING_SCROLL, reason="test")
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll", fake_emit
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    result = mode_ticks._maybe_scroll_to_hunt_map(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["ti_teleporter"]
    assert board.scratch.get(SCRATCH_HUNT_MAP_SCROLL_AT)
