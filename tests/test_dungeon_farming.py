"""Dungeon-only farming fixes must not change island hunt-map tests."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app._03_world.enums import ActionType
from app._03_world.world_coords import WorldOrigin
from app._04_decision.behavior_tree import Status
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors import mode_ticks
from app._04_decision.dungeon import set_dungeon_mode_override
from app._04_decision.player_mode import PlayerMode
from app._04_decision import player_mode as pm
from app._04_decision.talking_scroll import (
    farm_return_scroll_spot,
    hunt_map_is_dungeon,
    on_dungeon_return_town,
    player_on_selected_map,
)
from manmabot_v1.probes import map_style_is_dungeon


def teardown_function() -> None:
    set_dungeon_mode_override(None)
    pm.HUNT_MAP_ID = "talking_island"


def test_dungeon_pack_id_wins_over_normal_style():
    assert map_style_is_dungeon("giran_dungeon_F1", "normal") is True
    assert map_style_is_dungeon("talking_island", "normal") is False
    assert map_style_is_dungeon("mainland", None) is False


def test_dungeon_return_spot_is_giran_town():
    assert farm_return_scroll_spot("giran_dungeon_F1") == "giran_teleporter"
    assert farm_return_scroll_spot("talking_island") == "ti_spellbook"
    assert farm_return_scroll_spot("mainland") == "giran_teleporter"


def test_player_on_selected_map_dungeon_uses_pack_id(monkeypatch):
    set_dungeon_mode_override(True)
    pm.HUNT_MAP_ID = "giran_dungeon_F1"
    monkeypatch.setattr(
        "app._03_world.map_pack.get_active_map_pack",
        lambda: SimpleNamespace(id="mainland", name="Main Land"),
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=10, y=10)
    assert hunt_map_is_dungeon() is True
    assert player_on_selected_map(board) is False
    monkeypatch.setattr(
        "app._03_world.map_pack.get_active_map_pack",
        lambda: SimpleNamespace(id="giran_dungeon_F1", name="Giran Dungeon F1"),
    )
    assert player_on_selected_map(board) is True


def test_island_player_on_selected_map_still_uses_terrain(monkeypatch):
    set_dungeon_mode_override(False)
    pm.HUNT_MAP_ID = "talking_island"
    monkeypatch.setattr(
        "app._04_decision.nav_config.get_terrain_map",
        lambda: SimpleNamespace(width=80, height=80),
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


def test_scroll_to_hunt_map_does_not_loop_in_return_town(monkeypatch):
    set_dungeon_mode_override(True)
    pm.HUNT_MAP_ID = "giran_dungeon_F1"
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.player_on_selected_map",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.hunt_map_is_dungeon",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.on_dungeon_return_town",
        lambda: True,
    )
    monkeypatch.setattr(
        "app._04_decision.nav_config.navigation_configure_in_progress",
        lambda: False,
    )
    fired: list[str] = []

    def fake_emit(blackboard, **kwargs):
        fired.append(str(kwargs.get("spot_id") or ""))
        return Status.SUCCESS

    monkeypatch.setattr(
        "app._04_decision.talking_scroll.emit_talking_scroll", fake_emit
    )
    board = Blackboard()
    board.player_mode = PlayerMode.FARMING
    assert mode_ticks._maybe_scroll_to_hunt_map(SimpleNamespace(), board) is None
    assert fired == []


def test_dungeon_tick_skips_newbie_training(monkeypatch):
    set_dungeon_mode_override(True)
    pm.HUNT_MAP_ID = "giran_dungeon_F1"
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.player_on_selected_map",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.hunt_map_is_dungeon",
        lambda: True,
    )
    monkeypatch.setattr(mode_ticks, "_maybe_dungeon_death", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_emergency_teleport", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "apply_hp_actions", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_low_mp_to_safe", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_return_on_vitals", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_return_on_idle", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_support_spells", lambda *_a, **_k: None)
    called = {"newbie": 0}

    def boom(*_a, **_k):
        called["newbie"] += 1
        raise AssertionError("newbie training must not run on dungeon tick")

    monkeypatch.setattr(mode_ticks, "_tick_newbie_training", boom)
    monkeypatch.setattr(mode_ticks, "_maybe_post_respawn_spellbook", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_shop_trip", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_post_shop_farm_return", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_scroll_to_hunt_map", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "farm_loot_or_combat", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app._04_decision.patrol.get_patrol_waypoints", lambda: []
    )
    monkeypatch.setattr(
        "app._04_decision.patrol.begin_or_continue_patrol", lambda *_a, **_k: False
    )
    board = Blackboard()
    board.world_origin = WorldOrigin(x=1, y=1)
    status = mode_ticks._tick_dungeon_farming(SimpleNamespace(), board)
    assert status is Status.SUCCESS
    assert called["newbie"] == 0


def test_dungeon_tick_idles_when_off_floor(monkeypatch):
    set_dungeon_mode_override(True)
    pm.HUNT_MAP_ID = "giran_dungeon_F1"
    monkeypatch.setattr(mode_ticks, "_maybe_dungeon_death", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_emergency_teleport", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "apply_hp_actions", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_low_mp_to_safe", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_return_on_vitals", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_return_on_idle", lambda *_a, **_k: False)
    monkeypatch.setattr(mode_ticks, "_maybe_support_spells", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_post_respawn_spellbook", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_shop_trip", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_post_shop_farm_return", lambda *_a, **_k: None)
    monkeypatch.setattr(mode_ticks, "_maybe_scroll_to_hunt_map", lambda *_a, **_k: None)
    combat = MagicMock(return_value=Status.SUCCESS)
    monkeypatch.setattr(mode_ticks, "farm_loot_or_combat", combat)
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.player_on_selected_map",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "app._04_decision.talking_scroll.hunt_map_is_dungeon",
        lambda: True,
    )
    board = Blackboard()
    status = mode_ticks._tick_dungeon_farming(SimpleNamespace(), board)
    assert status is Status.SUCCESS
    combat.assert_not_called()
    assert board.intent is not None
    assert board.intent.reason == "dungeon, off hunt floor"


def test_on_dungeon_return_town(monkeypatch):
    set_dungeon_mode_override(True)
    pm.HUNT_MAP_ID = "giran_dungeon_F1"
    monkeypatch.setattr(
        "app._03_world.map_pack.get_active_map_pack",
        lambda: SimpleNamespace(id="mainland", name="Main Land"),
    )
    assert on_dungeon_return_town() is True
    monkeypatch.setattr(
        "app._03_world.map_pack.get_active_map_pack",
        lambda: SimpleNamespace(id="giran_dungeon_F1", name="Giran Dungeon F1"),
    )
    assert on_dungeon_return_town() is False
