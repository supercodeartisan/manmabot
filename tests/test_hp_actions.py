from __future__ import annotations

from app._04_decision.hp_actions import find_hp_restore_hotbar, pick_hp_action
from manmabot_v1.hp_actions import (
    HP_ACTION_IDS,
    default_hp_actions,
    normalize_hp_actions,
    sync_legacy_from_actions,
    to_engine_actions,
)
from manmabot_v1.profile import Profile
from manmabot_v1.schedule import ScheduleStore
from manmabot_v1.task_runtime import apply_runtime_settings


def test_default_order_is_heal_tree_potion_teleport_safe():
    from manmabot_v1.hp_actions import item_action_id, known_hp_action_ids

    ids = [row["id"] for row in default_hp_actions()]
    assert ids == [
        "heal",
        "mother_tree",
        item_action_id("빨간 물약"),
        "teleport",
        "safe_zone",
    ]
    assert item_action_id("주홍 물약") not in ids
    assert "hp_potion" not in ids
    assert ids == list(known_hp_action_ids())
    assert ids == list(HP_ACTION_IDS)


def test_normalize_keeps_user_order_and_fills_missing():
    raw = [
        {"id": "hp_potion", "enabled": False, "hp_below": 40},
        {"id": "heal", "enabled": True, "hp_below": 70},
    ]
    rows = normalize_hp_actions(raw)
    ids = [row["id"] for row in rows]
    assert ids[0] == "item:빨간 물약"
    assert ids[1] == "heal"
    assert "mother_tree" in ids
    assert "teleport" in ids
    assert "safe_zone" in ids
    assert rows[0]["enabled"] is False
    assert rows[1]["hp_below"] == 70
    assert "item:주홍 물약" not in ids


def test_normalize_keeps_inventory_item_without_catalog_fill():
    from manmabot_v1.hp_actions import item_action_id

    raw = [
        {"id": "heal", "enabled": True, "hp_below": 60},
        {"id": item_action_id("주홍 물약"), "enabled": True, "hp_below": 40},
        {"id": "teleport", "enabled": True, "hp_below": 25},
    ]
    rows = normalize_hp_actions(
        raw,
        extra_item_keys=("주홍 물약",),
        fill_catalog=False,
    )
    ids = [row["id"] for row in rows]
    assert ids[0] == "heal"
    assert item_action_id("주홍 물약") in ids
    assert item_action_id("맑은 물약") not in ids
    assert item_action_id("엔트의 열매") not in ids
    assert "mother_tree" in ids
    assert "safe_zone" in ids
    assert "item:heal" not in ids


def test_inventory_item_key_allows_non_restore_bag_rows():
    from manmabot_v1.hp_actions import inventory_item_key_for_hp_action

    assert inventory_item_key_for_hp_action({"name": "단검", "count": 1}) == "단검"
    assert inventory_item_key_for_hp_action({"name": "주홍 물약", "count": 2}) == "주홍 물약"
    assert inventory_item_key_for_hp_action({"name": "—", "id": 42}) == "#42"


def test_inventory_hp_item_keys_match_catalog_restore_items():
    from app._03_world.game_catalog import hp_restore_item
    from manmabot_v1.hp_actions import inventory_hp_item_keys

    red = hp_restore_item("빨간 물약")
    assert red is not None
    keys = inventory_hp_item_keys(
        [
            {"id": red.ids[0], "name": "아데나", "count": 10},
            {"name": "주홍 물약", "count": 2},
            {"name": "단검", "count": 1},
        ]
    )
    assert "빨간 물약" in keys
    assert "주홍 물약" in keys
    assert "단검" not in keys


def test_engine_normalize_keeps_unknown_item_action():
    from app._04_decision.hp_actions import normalize_hp_actions as engine_normalize

    rows = engine_normalize(
        [
            {"id": "heal", "enabled": True, "hp_below": 0.6},
            {"id": "item:테스트회복물약XYZ", "enabled": True, "hp_below": 0.4},
        ]
    )
    custom = next(row for row in rows if row["id"] == "item:테스트회복물약XYZ")
    assert custom["enabled"] is True
    assert custom["hp_below"] == 0.4


def test_apply_hp_actions_falls_through_failed_heal_to_potion(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    fired: list[str] = []

    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": True,
            "hp_potion": True,
            "mother_tree": False,
            "teleport": False,
            "safe_zone": False,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: (
            fired.append(action_id)
            or (Status.FAILURE if action_id == "heal" else Status.SUCCESS)
        ),
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.40)
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)

    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["heal", "item:빨간 물약"]


def test_hp_spike_uses_teleport_not_heal(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    fired: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": True,
            "hp_potion": True,
            "mother_tree": True,
            "teleport": True,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or Status.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.40)
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_combat_hp_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "is_low_level_hp_mode", lambda *_a, **_k: False)

    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["teleport"]


def test_hp_spike_low_level_prefers_teleport_then_tree(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    fired: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": False,
            "hp_potion": False,
            "mother_tree": True,
            "teleport": False,  # field forbid; spike re-enables via _can_teleport_now
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or Status.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "_can_teleport_now", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mode_actions, "_hp_action_enabled", lambda *_a, **_k: True
    )
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.40)
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_combat_hp_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "is_low_level_hp_mode", lambda *_a, **_k: True)

    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["teleport"]


def test_hp_spike_falls_back_to_talking_scroll(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    fired: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": True,
            "hp_potion": True,
            "mother_tree": False,
            "teleport": False,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or Status.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.40)
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_combat_hp_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "is_low_level_hp_mode", lambda *_a, **_k: False)

    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["safe_zone"]


def test_low_level_field_blocks_heal_in_availability(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    state = SimpleNamespace(
        player=SimpleNamespace(level=10, character_type=CharacterType.ELF),
        character_type=CharacterType.ELF,
    )
    monkeypatch.setattr(mode_actions, "_can_heal_now", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_can_item_now", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_can_teleport_now", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_can_safe_now", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app._04_decision.mode_control.elf_uses_mother_tree",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_enabled",
        lambda *_a, **_k: True,
    )
    can = mode_actions._hp_action_availability(
        state, board, retreat_starters=True
    )
    assert can["heal"] is False
    assert can["teleport"] is False
    assert can["mother_tree"] is True
    assert can["safe_zone"] is True

    board.player_mode = PlayerMode.RETREATING
    can_r = mode_actions._hp_action_availability(
        state, board, retreat_starters=True
    )
    assert can_r["heal"] is True


def test_low_mp_skips_heal_and_teleport_uses_scroll(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    fired: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": False,
            "hp_potion": False,
            "mother_tree": False,
            "teleport": False,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or Status.SUCCESS,
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.25)
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_combat_hp_threat", lambda *_a, **_k: True)

    result = mode_actions.apply_hp_actions(SimpleNamespace(), board)
    assert result is Status.SUCCESS
    assert fired == ["safe_zone"]


def test_teleport_blocked_when_mp_is_reserved(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    player = PlayerState(
        track_id=1,
        position=Position.zero(),
        hp=20,
        max_hp=100,
        mp=10,
        max_mp=100,
        character_type=CharacterType.ELF,
    )
    state = SimpleNamespace(player=player, last_hotbar=None)
    assert mode_actions.heal_blocked_by_mana(state) is True
    assert mode_actions._can_teleport_now(state, None) is False


def test_mp_below_five_blocks_heal_and_teleport_even_above_reserve():
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box({"teleport": {"box": 1, "key": "f11", "enabled": True}})
    try:
        player = PlayerState(
            track_id=1,
            position=Position.zero(),
            hp=20,
            max_hp=100,
            mp=4,
            max_mp=10,
            character_type=CharacterType.ELF,
        )
        state = SimpleNamespace(player=player, last_hotbar=None)
        assert mode_actions.heal_blocked_by_mana(state) is True
        assert mode_actions._can_teleport_now(state, None) is False
    finally:
        configure_spell_box()


def test_pick_skips_unavailable_and_respects_thresholds():
    actions = to_engine_actions(default_hp_actions())
    can = {
        "heal": False,
        "mother_tree": True,
        "hp_potion": True,
        "teleport": True,
        "safe_zone": True,
    }
    assert pick_hp_action(0.50, actions, can) == "item:빨간 물약"
    assert pick_hp_action(0.25, actions, can) == "mother_tree"
    can["mother_tree"] = False
    assert pick_hp_action(0.25, actions, can) == "item:빨간 물약"


def test_find_hp_restore_hotbar_uses_live_box_key():
    from types import SimpleNamespace

    world = SimpleNamespace(
        last_hotbar={
            "slots": [
                {"slot": 10, "box": 2, "key": "f7", "name": "주홍 물약 (4)"},
                {"slot": 3, "box": 1, "key": "f8", "name": "빨간 물약 (10)"},
            ]
        }
    )
    assert find_hp_restore_hotbar(world, "주홍 물약") == (2, "f7")
    assert find_hp_restore_hotbar(world, "item:빨간 물약") == (1, "f8")
    layout = {
        "boxes": {
            "3": {"f12": {"kr_name": "엔트의 열매", "kind": "ITEM", "count": 2}},
        }
    }
    assert find_hp_restore_hotbar(None, "엔트의 열매", layout=layout) == (3, "f12")


def test_runtime_applies_hp_action_order():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["recovery"]["hp_actions"] = [
        {"id": "mother_tree", "enabled": True, "hp_below": 22},
        {"id": "heal", "enabled": True, "hp_below": 60},
        {"id": "hp_potion", "enabled": False, "hp_below": 50},
        {"id": "safe_zone", "enabled": True, "hp_below": 18},
        {"id": "teleport", "enabled": False, "hp_below": 30},
    ]
    apply_runtime_settings(task, profile)
    assert [row["id"] for row in profile.hp_actions][:2] == ["mother_tree", "heal"]
    assert profile.use_heal is True
    assert profile.use_hp_potion is False
    assert profile.hp_potion_ratio == 0.60
    assert profile.hp_escape_ratio == 0.18


def test_runtime_disables_mp_escape_option():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["recovery"]["escape_mp_enabled"] = True
    task.settings["recovery"]["escape_mp_below"] = 22
    apply_runtime_settings(task, profile)
    assert profile.mp_escape_enabled is False


def test_runtime_applies_teleport_surround_count():
    profile = Profile()
    task = ScheduleStore().create(profile)
    task.settings["recovery"]["random_teleport_enabled"] = True
    task.settings["recovery"]["teleport_when_surrounded"] = True
    task.settings["recovery"]["teleport_surround_count"] = 6
    apply_runtime_settings(task, profile)
    assert profile.teleport_when_surrounded is True
    assert profile.teleport_surround_count == 6


def test_disabled_mp_escape_skips_mage_low_mp():
    from app._04_decision import player_mode as pm
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import is_mage_low_mp

    previous = pm.MP_ESCAPE_ENABLED
    try:
        configure_decision({"decision": {"mp": {"escape_enabled": False}}})
        assert pm.MP_ESCAPE_ENABLED is False
        assert is_mage_low_mp(None) is False
    finally:
        pm.MP_ESCAPE_ENABLED = previous


def test_apply_recovery_enables_assigned_slots():
    from manmabot_v1.hp_actions import apply_recovery_to_spell_slots

    slots = {
        "heal": {"box": 1, "key": "f8", "enabled": False},
        "hp_potion": {"box": 1, "key": "f5", "enabled": False},
        "teleport": {"box": 0, "key": "f10", "enabled": False},
    }
    actions = [
        {"id": "heal", "enabled": True, "hp_below": 20},
        {"id": "hp_potion", "enabled": True, "hp_below": 30},
        {"id": "teleport", "enabled": True, "hp_below": 30},
    ]
    out = apply_recovery_to_spell_slots(slots, actions)
    assert out["heal"]["enabled"] is True
    assert out["hp_potion"]["enabled"] is True
    assert out["teleport"]["enabled"] is False


def test_recovery_potion_fires_at_threshold(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryItem, InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "hp_potion", "enabled": True, "hp_below": 30},
                            {"id": "heal", "enabled": True, "hp_below": 20},
                            {"id": "teleport", "enabled": True, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": True, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "hp_potion": {"box": 1, "key": "f5", "enabled": True},
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "teleport": {"box": 1, "key": "f10", "enabled": False},
            "mother_tree": {"box": 2, "key": "f6", "enabled": False},
            "talking_scroll": {"box": 1, "key": "f8", "enabled": True},
        }
    )
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=25,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.25,
        character_type=CharacterType.ELF,
        inventory=InventoryState(
            hp_potion=8,
            bag_ready=True,
            items=[InventoryItem(name="빨간 물약", quantity=8, item_id=14)],
        ),
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    result = mode_actions.apply_hp_actions(
        SimpleNamespace(
            player=player,
            last_hotbar={
                "slots": [
                    {
                        "slot": 0,
                        "box": 1,
                        "key": "f5",
                        "name": "빨간 물약",
                        "id": 14,
                        "count": 8,
                    }
                ]
            },
        ),
        board,
    )
    assert result is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action.value == "use_hp_potion"


def test_orange_potion_uses_matching_hotbar_slot(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryItem, InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "item:주홍 물약", "enabled": True, "hp_below": 70},
                            {"id": "item:빨간 물약", "enabled": True, "hp_below": 40},
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "teleport", "enabled": False, "hp_below": 30},
                            {"id": "safe_zone", "enabled": False, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box({"hp_potion": {"box": 1, "key": "f9", "enabled": True}})
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=50,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.50,
        character_type=CharacterType.ELF,
        inventory=InventoryState(
            hp_potion=4,
            bag_ready=True,
            items=[
                InventoryItem(name="주홍 물약", quantity=4, item_id=15),
                InventoryItem(name="빨간 물약", quantity=10, item_id=14),
            ],
        ),
    )
    state = SimpleNamespace(
        player=player,
        last_hotbar={
            "slots": [
                {
                    "slot": 10, "box": 2, "key": "f7",
                    "name": "주홍 물약", "id": 15, "count": 4,
                },
                {
                    "slot": 3, "box": 1, "key": "f8",
                    "name": "빨간 물약", "id": 14, "count": 10,
                },
            ]
        },
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    try:
        result = mode_actions.apply_hp_actions(state, board)
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action.value == "use_hp_potion"
        assert board.intent.item_key == "주홍 물약"
        assert board.intent.hotbar_box == 2
        assert board.intent.hotbar_key == "f7"
    finally:
        configure_spell_box()


def test_empty_hp_potions_use_talking_scroll_when_teleport_off(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "hp_potion", "enabled": True, "hp_below": 30},
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "teleport", "enabled": True, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "hp_potion": {"box": 1, "key": "f5", "enabled": True},
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "teleport": {"box": 1, "key": "f10", "enabled": False},
            "talking_scroll": {"box": 1, "key": "f8", "enabled": True},
            "mother_tree": {"box": 2, "key": "f6", "enabled": False},
        }
    )
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=25,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.25,
        character_type=CharacterType.ELF,
        inventory=InventoryState(hp_potion=0, bag_ready=True),
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    try:
        result = mode_actions.apply_hp_actions(SimpleNamespace(player=player), board)
        assert board.scratch.get("hp_retreat_kind") == "safe_zone"
        if result is Status.SUCCESS:
            assert board.intent is not None
            assert board.intent.action.value == "use_talking_scroll"
        else:
            assert result is mode_actions.HP_RETREAT_STARTED
    finally:
        configure_spell_box()


def test_safe_zone_uses_talking_scroll_not_teleport(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        PURPOSE_TRAINING,
        SCRATCH_RETREAT_SCROLL,
    )
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "hp_potion", "enabled": False, "hp_below": 30},
                            {"id": "teleport", "enabled": False, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "hp_potion": {"box": 1, "key": "f5", "enabled": False},
            "teleport": {"box": 1, "key": "f10", "enabled": True},
            "talking_scroll": {"box": 1, "key": "f8", "enabled": True},
            "mother_tree": {"box": 2, "key": "f6", "enabled": False},
        }
    )
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=25,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.25,
        character_type=CharacterType.ELF,
        inventory=InventoryState(hp_potion=0, bag_ready=True),
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    try:
        result = mode_actions.apply_hp_actions(SimpleNamespace(player=player), board)
        assert board.scratch.get("hp_retreat_kind") == "safe_zone"
        assert board.retreat_teleport_pending is False
        if result is Status.SUCCESS:
            assert board.intent is not None
            assert board.intent.action.value == "use_talking_scroll"
        else:
            assert result is mode_actions.HP_RETREAT_STARTED
            assert board.scratch.get(SCRATCH_RETREAT_SCROLL) == PURPOSE_TRAINING
            assert board.scratch.get(SCRATCH_RETREAT_SCROLL) == HP_SAFE_SCROLL_PURPOSE
    finally:
        configure_spell_box()


def test_hp_safe_zone_talking_scroll_fires_once(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "teleport", "enabled": False, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "teleport": {"box": 1, "key": "f10", "enabled": False},
            "talking_scroll": {"box": 1, "key": "f8", "enabled": True},
        }
    )
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    fired: list[str] = []
    import app._04_decision.talking_scroll as scroll_mod

    monkeypatch.setattr(
        scroll_mod,
        "emit_talking_scroll",
        lambda *_a, **_k: fired.append("scroll") or Status.SUCCESS,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=20,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.20,
        character_type=CharacterType.ELF,
        inventory=InventoryState(hp_potion=0, bag_ready=True),
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    state = SimpleNamespace(player=player, last_hotbar=None, monsters=lambda: ())
    try:
        first = mode_actions.apply_hp_actions(state, board)
        assert first is Status.SUCCESS
        assert fired == ["scroll"]
        assert board.scratch.get(SCRATCH_HP_SAFE_SCROLLED) is True
        board.intent = None
        second = mode_actions.apply_hp_actions(state, board)
        assert fired == ["scroll"]
        assert second is not Status.SUCCESS or (
            board.intent is None or board.intent.action.value != "use_talking_scroll"
        )
    finally:
        configure_spell_box()


def test_hp_safe_landed_blocks_teleport_row(monkeypatch):
    """After HP safe-zone scroll, same retreat must not pick teleport again."""
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                            {"id": "teleport", "enabled": True, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "teleport": {"box": 1, "key": "f10", "enabled": True},
            "talking_scroll": {"box": 1, "key": "f8", "enabled": True},
        }
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    board.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
    board.scratch["live_hotbar"] = {
        "slots": [{"name": "텔레포트", "box": 1, "key": "f10"}]
    }
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        character_type=CharacterType.ELF,
        hp=20,
        max_hp=100,
        mp=50,
        max_mp=100,
        inventory=InventoryState(hp_potion=0),
    )
    state = SimpleNamespace(
        player=player,
        character_type=CharacterType.ELF,
        last_hotbar=board.scratch["live_hotbar"],
        monsters=lambda: [],
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    try:
        can = mode_actions._hp_action_availability(
            state, board, retreat_starters=True
        )
        assert can["teleport"] is False
        result = mode_actions.apply_inplace_hp_support(state, board)
        assert result is not mode_actions.HP_RETREAT_STARTED
        assert board.retreat_teleport_pending is False
        if board.intent is not None:
            assert board.intent.action.value != "teleport"
    finally:
        configure_spell_box()


def test_hp_safe_zone_always_uses_eighth_npc_not_rotation():
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.mode_control import (
        RETREAT_FOR_HP,
        RETREAT_FOR_RETURN,
        begin_retreat,
    )
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        PURPOSE_SPELLBOOK,
        PURPOSE_TRAINING,
        SCRATCH_RETREAT_SCROLL,
        SCRATCH_RETREAT_SCROLL_I,
    )
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box(
        {"talking_scroll": {"box": 1, "key": "f8", "enabled": True}}
    )
    try:
        hp_board = Blackboard()
        assert begin_retreat(
            hp_board,
            reason=RETREAT_FOR_HP,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
        )
        assert hp_board.scratch.get(SCRATCH_RETREAT_SCROLL) == PURPOSE_TRAINING
        assert hp_board.scratch.get(SCRATCH_RETREAT_SCROLL) == HP_SAFE_SCROLL_PURPOSE
        assert hp_board.scratch.get(SCRATCH_RETREAT_SCROLL_I) in (None, 0)

        again = Blackboard()
        again.scratch[SCRATCH_RETREAT_SCROLL_I] = 0
        assert begin_retreat(
            again,
            reason=RETREAT_FOR_HP,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
        )
        assert again.scratch.get(SCRATCH_RETREAT_SCROLL) == PURPOSE_TRAINING

        ret_board = Blackboard()
        assert begin_retreat(
            ret_board,
            reason=RETREAT_FOR_RETURN,
            prefer_scroll=True,
            allow_teleport=False,
            use_mother_tree=False,
            walk_to_safe=True,
        )
        assert ret_board.scratch.get(SCRATCH_RETREAT_SCROLL) == PURPOSE_SPELLBOOK
    finally:
        configure_spell_box()


def test_heal_available_when_mp_unknown():
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {"decision": {"hp": {"recover_enabled": True, "use_heal": True}}}
    )
    configure_spell_box({"heal": {"box": 1, "key": "f8", "enabled": True}})
    try:
        player = PlayerState(
            track_id=1,
            position=Position(0.5, 0.5),
            hp=40,
            max_hp=100,
            hp_ratio=0.40,
            character_type=CharacterType.ELF,
        )
        assert mode_actions._can_heal_now(
            SimpleNamespace(
                player=player,
                last_hotbar={"slots": [{"box": 1, "key": "f8", "name": "힐"}]},
            )
        ) is True
    finally:
        configure_spell_box()


def test_retreat_heal_and_potion_until_almost_full(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": True, "hp_below": 55},
                            {"id": "hp_potion", "enabled": True, "hp_below": 55},
                            {"id": "teleport", "enabled": False, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
        }
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    high = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=70,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.70,
        character_type=CharacterType.ELF,
    )
    low = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=50,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.50,
        character_type=CharacterType.ELF,
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    bar = {"slots": [{"box": 1, "key": "f8", "name": "힐"}]}
    try:
        assert mode_actions.apply_hp_actions(
            SimpleNamespace(player=high, last_hotbar=bar), board
        ) is None
        result = mode_actions.apply_hp_actions(
            SimpleNamespace(player=low, last_hotbar=bar), board
        )
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action.value == "heal"
    finally:
        configure_spell_box()


def test_retreat_follows_hp_order_when_potion_is_first(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "actions": to_engine_actions(
                        [
                            {"id": "hp_potion", "enabled": True, "hp_below": 80},
                            {"id": "heal", "enabled": True, "hp_below": 80},
                            {"id": "teleport", "enabled": False, "hp_below": 30},
                            {"id": "safe_zone", "enabled": True, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
        }
    )
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=70,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.70,
        character_type=CharacterType.ELF,
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    try:
        result = mode_actions.apply_hp_actions(
            SimpleNamespace(
                player=player,
                last_hotbar={
                    "slots": [
                        {"box": 1, "key": "f8", "name": "힐"},
                        {"box": 1, "key": "f9", "name": "빨간 물약", "count": 4},
                    ]
                },
            ),
            board,
        )
        assert result is Status.SUCCESS
        assert board.intent is not None
        assert board.intent.action.value == "use_hp_potion"
    finally:
        configure_spell_box()


def test_legacy_sync_matches_enabled_rows():
    legacy = sync_legacy_from_actions(default_hp_actions())
    assert legacy["use_heal"] is True
    assert legacy["use_hp_potion"] is True
    assert legacy["hp_potion_below"] == 55
    assert legacy["escape_hp_below"] == 30


def _dead_player():
    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState

    return PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=0,
        max_hp=100,
        mp=0,
        max_mp=50,
        hp_ratio=0.0,
        level=12,
        character_type=CharacterType.ELF,
        alive=False,
    )


def test_hp_zero_does_not_emit_heal(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    monkeypatch.setattr(mode_actions, "maybe_use_antidote", lambda *_a, **_k: None)
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    result = mode_actions.apply_hp_actions(
        SimpleNamespace(player=_dead_player()), board
    )
    assert result is None
    assert board.intent is None


def test_island_farm_tick_idles_while_dead_not_heal(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision.player_mode import PlayerMode

    monkeypatch.setattr(
        "app._04_decision.dungeon.is_dungeon_map", lambda: False
    )
    heal = {"called": False}

    def boom_heal(*_a, **_k):
        heal["called"] = True
        raise AssertionError("heal must not click the corpse")

    monkeypatch.setattr(mode_ticks, "apply_hp_actions", boom_heal)
    monkeypatch.setattr(mode_ticks, "farm_loot_or_combat", boom_heal)
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    status = mode_ticks.tick_farming(
        SimpleNamespace(player=_dead_player()), board
    )
    assert status is Status.SUCCESS
    assert heal["called"] is False
    assert board.intent is not None
    assert board.intent.action is ActionType.IDLE
    assert board.intent.reason == "waiting for respawn"


def test_island_farm_tick_clicks_restart_after_death_confirm(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import ActionType
    from app._04_decision.behavior_tree import Status
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision import mode_control
    from app._04_decision.player_mode import PlayerMode

    monkeypatch.setattr(
        "app._04_decision.dungeon.is_dungeon_map", lambda: False
    )
    monkeypatch.setattr(mode_control, "DEATH_CONFIRM_SECONDS", 0.0)
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    status = mode_ticks.tick_farming(
        SimpleNamespace(player=_dead_player()), board
    )
    assert status is Status.SUCCESS
    assert board.intent is not None
    assert board.intent.action is ActionType.RESPAWN
    assert board.intent.reason == "death confirmed, restart"


def _retreat_player(*, hp: int, potions: int | None = None, mp: int = 40):
    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState

    inv = InventoryState(
        hp_potion=0 if potions is None else int(potions),
        bag_ready=potions is not None,
    )
    return PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=hp,
        max_hp=100,
        mp=mp,
        max_mp=50,
        hp_ratio=hp / 100.0,
        character_type=CharacterType.ELF,
        inventory=inv,
    )


def _no_heal_no_potion_box():
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "hp_potion": {"box": 1, "key": "f9", "enabled": False},
        }
    )


def test_retreat_exits_at_half_hp_without_heal_or_potion():
    from types import SimpleNamespace

    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import retreat_exit_ready
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "full_ratio": 0.99,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                }
            }
        }
    )
    _no_heal_no_potion_box()
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        low = SimpleNamespace(player=_retreat_player(hp=40, potions=0))
        ready = SimpleNamespace(player=_retreat_player(hp=50, potions=0))
        assert mode_actions.can_active_hp_recover(low) is False
        assert retreat_exit_ready(board, low) is False
        assert retreat_exit_ready(board, ready) is True
        assert mode_actions.retreat_recover_until_ratio(ready) == 0.50
    finally:
        configure_spell_box()


def test_retreat_waits_for_almost_full_when_heal_available():
    from types import SimpleNamespace

    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import retreat_exit_ready
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "full_ratio": 0.99,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "hp_potion": {"box": 1, "key": "f9", "enabled": False},
        }
    )
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        heal_bar = {"slots": [{"box": 1, "key": "f8", "name": "힐"}]}
        half = SimpleNamespace(
            player=_retreat_player(hp=50, potions=0), last_hotbar=heal_bar
        )
        almost = SimpleNamespace(
            player=_retreat_player(hp=90, potions=0), last_hotbar=heal_bar
        )
        assert mode_actions.can_active_hp_recover(half) is True
        assert retreat_exit_ready(board, half) is False
        assert retreat_exit_ready(board, almost) is True
        assert mode_actions.retreat_recover_until_ratio(half) == 0.90
    finally:
        configure_spell_box()


def test_retreat_exits_at_half_hp_when_heal_slot_on_but_skill_missing():
    from types import SimpleNamespace

    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import retreat_exit_ready
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "full_ratio": 0.99,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
        }
    )
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        ready = SimpleNamespace(
            player=_retreat_player(hp=50, potions=0),
            last_hotbar={"slots": []},
        )
        assert mode_actions.can_active_hp_recover(ready) is False
        assert retreat_exit_ready(board, ready) is True
        assert mode_actions.retreat_recover_until_ratio(ready) == 0.50
    finally:
        configure_spell_box()


def test_retreat_exits_at_half_hp_when_hotbar_potion_count_is_zero():
    from types import SimpleNamespace

    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import retreat_exit_ready
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
        }
    )
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        ready = SimpleNamespace(
            player=_retreat_player(hp=50, potions=0),
            last_hotbar={
                "slots": [
                    {
                        "box": 1,
                        "key": "f9",
                        "name": "빨간 물약",
                        "count": 0,
                    }
                ]
            },
        )
        assert mode_actions.can_active_hp_recover(ready) is False
        assert retreat_exit_ready(board, ready) is True
        assert mode_actions.retreat_recover_until_ratio(ready) == 0.50
    finally:
        configure_spell_box()


def test_hotbar_zero_wins_over_stale_bag_and_falls_through(monkeypatch):
    """Bag may still show potions while the live hotbar slot is empty."""
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryItem, InventoryState, PlayerState
    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box
    from manmabot_v1.hp_actions import to_engine_actions

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "actions": to_engine_actions(
                        [
                            {"id": "heal", "enabled": False, "hp_below": 20},
                            {"id": "hp_potion", "enabled": True, "hp_below": 55},
                            {"id": "teleport", "enabled": True, "hp_below": 55},
                            {"id": "safe_zone", "enabled": False, "hp_below": 30},
                            {"id": "mother_tree", "enabled": False, "hp_below": 30},
                        ]
                    ),
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
            "teleport": {"box": 1, "key": "f10", "enabled": True},
        }
    )
    monkeypatch.setattr(mode_actions, "hp_spike_drop", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=40,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.40,
        level=20,
        character_type=CharacterType.ELF,
        inventory=InventoryState(
            hp_potion=12,
            bag_ready=True,
            items=[InventoryItem(name="빨간 물약", quantity=12, item_id=14)],
        ),
    )
    state = SimpleNamespace(
        player=player,
        last_hotbar={
            "slots": [
                {
                    "box": 1,
                    "key": "f9",
                    "name": "빨간 물약",
                    "id": 14,
                    "count": 0,
                },
                {
                    "box": 1,
                    "key": "f10",
                    "name": "텔레포트",
                },
            ]
        },
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    try:
        assert mode_actions._can_item_now(state, "빨간 물약") is False
        assert mode_actions._hp_item_count(state, "빨간 물약") == 0
        result = mode_actions.apply_hp_actions(state, board)
        assert result is not None and result is not Status.FAILURE
        assert board.scratch.get("hp_retreat_kind") == "teleport"
    finally:
        configure_spell_box()


def test_can_heal_without_hotbar_snapshot(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {"decision": {"hp": {"recover_enabled": True, "use_heal": True}}}
    )
    configure_spell_box({"heal": {"box": 1, "key": "f8", "enabled": True}})
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=40,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.40,
        character_type=CharacterType.ELF,
    )
    try:
        assert mode_actions._can_heal_now(SimpleNamespace(player=player, last_hotbar=None))
        blocked = mode_actions._can_heal_now(
            SimpleNamespace(
                player=player,
                last_hotbar={"slots": [{"box": 1, "key": "f5", "name": "파워 업"}]},
            )
        )
        assert blocked is False
    finally:
        configure_spell_box()


def test_arm_hp_escape_fallback_uses_talking_scroll(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import (
        HP_SAFE_SCROLL_PURPOSE,
        SCRATCH_HP_SAFE_SCROLLED,
        SCRATCH_RETREAT_SCROLL,
    )
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box(
        {
            "talking_scroll": {"box": 2, "key": "f5", "enabled": True},
            "mother_tree": {"box": 2, "key": "f6", "enabled": True},
            "teleport": {"box": 1, "key": "f10", "enabled": True},
        }
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    board.scratch["hp_retreat_kind"] = "teleport"
    monkeypatch.setattr(mode_actions, "is_low_level_hp_mode", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        lambda *_a, **_k: Status.SUCCESS,
    )
    try:
        result = mode_actions.arm_hp_escape_fallback(SimpleNamespace(), board)
        assert result is Status.SUCCESS
        assert board.scratch.get(SCRATCH_HP_SAFE_SCROLLED) is True
        assert board.scratch.get("hp_retreat_kind") == "safe_zone"
        assert board.scratch.get(SCRATCH_RETREAT_SCROLL) is None
        assert HP_SAFE_SCROLL_PURPOSE  # purpose constant still imported for clarity
    finally:
        configure_spell_box()


def test_retreat_tick_falls_back_when_teleport_cannot_cast(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app._05_action.spell_box import configure_spell_box

    configure_spell_box(
        {
            "talking_scroll": {"box": 2, "key": "f5", "enabled": True},
            "teleport": {"box": 1, "key": "f10", "enabled": True},
        }
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    board.retreat_teleport_pending = True
    board.scratch["hp_retreat_kind"] = "teleport"
    board.scratch["retreat_for"] = "hp"
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions._can_teleport_now",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(mode_ticks, "update_death_timer", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "should_emit_respawn", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_tick_mother_tree_retreat", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "retreat_exit_ready", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "waiting_for_respawn", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "is_hp_zero", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll",
        lambda *_a, **_k: Status.SUCCESS,
    )
    monkeypatch.setattr(mode_ticks, "_maybe_support_spells", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app._04_decision.behaviors.mode_actions.apply_inplace_hp_support",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(mode_ticks, "retreat_loot_if_clear", lambda *_a, **_k: None)
    try:
        result = mode_ticks.tick_retreating(SimpleNamespace(player=None), board)
        assert result is Status.SUCCESS
        assert board.retreat_teleport_pending is False
        assert board.scratch.get(SCRATCH_HP_SAFE_SCROLLED) is True
    finally:
        configure_spell_box()


def test_post_land_mother_tree_before_passive_wait(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import InventoryState, PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                },
                "elf": {"mother_tree": True},
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "hp_potion": {"box": 1, "key": "f9", "enabled": False},
            "mother_tree": {"box": 2, "key": "f6", "enabled": True},
        }
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=40,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.40,
        character_type=CharacterType.ELF,
        inventory=InventoryState(hp_potion=0, bag_ready=True),
    )
    state = SimpleNamespace(player=player, last_hotbar={"slots": []})
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    board.scratch["retreat_for"] = "hp"
    board.scratch["hp_retreat_kind"] = "safe_zone"
    board.scratch[SCRATCH_HP_SAFE_SCROLLED] = True
    try:
        result = mode_actions.maybe_mother_tree_before_passive_wait(state, board)
        assert result is mode_actions.HP_RETREAT_STARTED
        assert board.scratch.get("mother_tree_trip") == "cast"
        assert board.scratch.get("hp_post_land_tree_tried") is True
        # Second call must not re-arm.
        assert mode_actions.maybe_mother_tree_before_passive_wait(state, board) is None
    finally:
        configure_spell_box()


def test_post_land_mother_tree_skips_when_heal_available(monkeypatch):
    from types import SimpleNamespace

    from app._03_world.enums import CharacterType
    from app._03_world.objects import Position
    from app._03_world.player import PlayerState
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision.talking_scroll import SCRATCH_HP_SAFE_SCROLLED
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                },
                "elf": {"mother_tree": True},
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": True},
            "mother_tree": {"box": 2, "key": "f6", "enabled": True},
        }
    )
    player = PlayerState(
        track_id=1,
        position=Position(0.5, 0.5),
        hp=40,
        max_hp=100,
        mp=40,
        max_mp=50,
        hp_ratio=0.40,
        character_type=CharacterType.ELF,
    )
    state = SimpleNamespace(
        player=player,
        last_hotbar={"slots": [{"box": 1, "key": "f8", "name": "힐"}]},
    )
    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    board.scratch["retreat_for"] = "hp"
    board.scratch["hp_retreat_kind"] = "teleport"
    board.retreat_teleport_pending = False
    board.scratch[SCRATCH_HP_SAFE_SCROLLED] = False
    try:
        assert mode_actions.can_active_hp_recover(state) is True
        assert mode_actions.maybe_mother_tree_before_passive_wait(state, board) is None
        assert board.scratch.get("mother_tree_trip") is None
    finally:
        configure_spell_box()


def test_retreat_exits_at_half_hp_after_potions_run_out():
    from types import SimpleNamespace

    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.configure import configure_decision
    from app._04_decision.mode_control import retreat_exit_ready
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "almost_full_ratio": 0.90,
                    "full_ratio": 0.99,
                    "passive_recover_ratio": 0.50,
                    "use_heal": True,
                    "use_potion": True,
                }
            }
        }
    )
    configure_spell_box(
        {
            "heal": {"box": 1, "key": "f8", "enabled": False},
            "hp_potion": {"box": 1, "key": "f9", "enabled": True},
        }
    )
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        still_have = SimpleNamespace(player=_retreat_player(hp=50, potions=3))
        empty = SimpleNamespace(player=_retreat_player(hp=50, potions=0))
        empty_low = SimpleNamespace(player=_retreat_player(hp=40, potions=0))
        assert mode_actions.can_active_hp_recover(still_have) is True
        assert retreat_exit_ready(board, still_have) is False
        assert mode_actions.can_active_hp_recover(empty) is False
        assert retreat_exit_ready(board, empty_low) is False
        assert retreat_exit_ready(board, empty) is True
    finally:
        configure_spell_box()


def test_retreat_tick_returns_to_farm_at_half_hp_without_consumables(monkeypatch):
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors import mode_ticks
    from app._04_decision.configure import configure_decision
    from app._04_decision.player_mode import PlayerMode
    from app._05_action.spell_box import configure_spell_box

    configure_decision(
        {
            "decision": {
                "hp": {
                    "recover_enabled": True,
                    "passive_recover_ratio": 0.50,
                    "use_heal": False,
                    "use_potion": False,
                }
            }
        }
    )
    _no_heal_no_potion_box()
    monkeypatch.setattr(mode_ticks, "apply_inplace_hp_support", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app._04_decision.mode_control.get_active_farm", lambda *_a, **_k: None
    )
    try:
        board = Blackboard()
        board.player_mode = PlayerMode.RETREATING
        board.scratch["retreat_for"] = "hp"
        status = mode_ticks.tick_retreating(
            SimpleNamespace(player=_retreat_player(hp=50, potions=0)),
            board,
        )
        assert status is Status.FAILURE
        assert board.player_mode is PlayerMode.FARMING
    finally:
        configure_spell_box()


def test_natural_recover_under_attack_follows_hp_order(monkeypatch):
    import time
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.hp_actions import normalize_hp_actions
    from app._04_decision.player_mode import PlayerMode
    from app._04_decision import player_mode as pm

    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 1.0, 0.52), (now, 0.44)]
    previous = list(pm.HP_ACTIONS)
    fired: list[str] = []
    monkeypatch.setattr(mode_actions, "can_active_hp_recover", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "_nearby_monster_threat", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app._04_decision.shop_trip.shopping_blocks_teleport",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        mode_actions,
        "_hp_action_availability",
        lambda *_a, **_k: {
            "heal": False,
            "hp_potion": False,
            "mother_tree": False,
            "teleport": True,
            "safe_zone": True,
        },
    )
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or Status.SUCCESS,
    )
    try:
        pm.HP_ACTIONS = normalize_hp_actions(
            [
                {"id": "heal", "enabled": False, "hp_below": 0.90},
                {"id": "teleport", "enabled": True, "hp_below": 0.30},
                {"id": "safe_zone", "enabled": True, "hp_below": 0.30},
            ]
        )
        result = mode_actions.escape_natural_recover_under_attack(
            SimpleNamespace(player=_retreat_player(hp=44, potions=0)),
            board,
        )
        assert result is Status.SUCCESS
        assert fired == ["teleport"]

        fired.clear()
        pm.HP_ACTIONS = normalize_hp_actions(
            [
                {"id": "teleport", "enabled": False, "hp_below": 0.30},
                {"id": "safe_zone", "enabled": True, "hp_below": 0.30},
            ]
        )
        result = mode_actions.escape_natural_recover_under_attack(
            SimpleNamespace(player=_retreat_player(hp=44, potions=0)),
            board,
        )
        assert result is Status.SUCCESS
        assert fired == ["safe_zone"]
    finally:
        pm.HP_ACTIONS = previous


def test_natural_recover_skips_escape_when_heal_available(monkeypatch):
    import time

    from types import SimpleNamespace

    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 1.0, 0.52), (now, 0.44)]
    monkeypatch.setattr(mode_actions, "can_active_hp_recover", lambda *_a, **_k: True)
    monkeypatch.setattr(mode_actions, "_nearby_monster_threat", lambda *_a, **_k: True)
    fired: list[str] = []
    monkeypatch.setattr(
        mode_actions,
        "_execute_hp_action",
        lambda action_id, *_a, **_k: fired.append(action_id) or True,
    )
    assert mode_actions.escape_natural_recover_under_attack(
        SimpleNamespace(player=_retreat_player(hp=44, potions=0)),
        board,
    ) is None
    assert fired == []


def test_inplace_support_escapes_when_natural_recover_is_hit(monkeypatch):
    import time
    from types import SimpleNamespace

    from app._04_decision.behavior_tree import Status
    from app._04_decision.behaviors import mode_actions
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.player_mode import PlayerMode

    board = Blackboard()
    board.player_mode = PlayerMode.RETREATING
    now = time.time()
    board.scratch["hp_ratio_hist"] = [(now - 1.0, 0.52)]
    monkeypatch.setattr(mode_actions, "maybe_use_antidote", lambda *_a, **_k: None)
    monkeypatch.setattr("app._04_decision.mode_control.hp_ratio", lambda _state: 0.44)
    monkeypatch.setattr(mode_actions, "can_active_hp_recover", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_actions, "should_drink_mp_potion", lambda *_a, **_k: False)
    monkeypatch.setattr(
        mode_actions,
        "escape_natural_recover_under_attack",
        lambda *_a, **_k: Status.SUCCESS,
    )
    result = mode_actions.apply_inplace_hp_support(
        SimpleNamespace(player=_retreat_player(hp=44, potions=0)),
        board,
    )
    assert result is Status.SUCCESS
    hist = board.scratch.get("hp_ratio_hist") or []
    assert hist[-1][1] == 0.44
