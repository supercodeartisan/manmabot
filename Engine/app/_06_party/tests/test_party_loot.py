"""Leader loot policy: no priority knob, solo farm does not change who loots."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app._03_world.space.terrain_map import TerrainMap
from app._04_decision import player_mode as pm
from app._04_decision.behaviors.mode_actions import party_leader_pile_ok
from app._06_party.config import PartyMemberConfig
from app._06_party.loot import (
    PARTY_LOOT_WALK_TILES,
    party_loot_ownership_filter,
    party_loot_radius,
    party_loot_walk_meter,
    party_loot_walks,
    party_may_start_loot,
    party_should_drop_loot,
)


def _pile(rx: int, on_screen: bool):
    pos = SimpleNamespace(x=0.5, y=0.5) if on_screen else None
    return SimpleNamespace(world_rx=rx, world_ry=0, position=pos)


def _leader_board():
    return SimpleNamespace(scratch={"party_leader_no_loot": True})


def test_leader_takes_no_pile() -> None:
    board = _leader_board()
    assert not party_leader_pile_ok(board, _pile(1, True))
    assert not party_leader_pile_ok(board, _pile(4, True))
    assert not party_leader_pile_ok(board, None)


def test_solo_pile_check_does_not_apply_the_leader_cap() -> None:
    board = SimpleNamespace(scratch={})
    assert party_leader_pile_ok(board, _pile(20, False))


def test_responsible_loots_party_drops_not_only_own() -> None:
    cfg = PartyMemberConfig(
        random_loot=False, loot_role="responsible", farm_mode="solo"
    )
    assert party_loot_ownership_filter(cfg) is False


def test_other_members_loot_their_own_piles() -> None:
    cfg = PartyMemberConfig(random_loot=False, loot_role="none", farm_mode="solo")
    assert party_loot_ownership_filter(cfg) is True


def test_near_radius_is_shared_and_responsible_walks_twelve() -> None:
    saved_near = pm.LOOT_MAX_TILES
    saved_wide = pm.LOOT_ENGAGE_MAX_TILES
    pm.LOOT_MAX_TILES = 7
    pm.LOOT_ENGAGE_MAX_TILES = 30
    try:
        own = PartyMemberConfig(random_loot=False, loot_role="none")
        wide = PartyMemberConfig(random_loot=False, loot_role="responsible")
        rand = PartyMemberConfig(random_loot=True, loot_role="responsible")
        assert party_loot_radius(own) == 7
        assert party_loot_radius(wide) == PARTY_LOOT_WALK_TILES == 12
        assert party_loot_walks(wide) is True
        assert party_loot_walks(own) is False
        assert party_loot_walks(rand) is False
        assert pm.LOOT_ENGAGE_MAX_TILES == 30
    finally:
        pm.LOOT_MAX_TILES = saved_near
        pm.LOOT_ENGAGE_MAX_TILES = saved_wide


def _walk_meter(monkeypatch, grid, me):
    terrain = TerrainMap.from_array(grid)
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: terrain)
    monkeypatch.setattr(
        "app._04_decision.combat_query.object_absolute_tile",
        lambda obj, origin: obj.tile,
    )
    monkeypatch.setattr(
        "app._04_decision.combat_query.tile_distance_from_player",
        lambda obj: max(abs(obj.tile[0] - me[0]), abs(obj.tile[1] - me[1])),
    )
    origin = SimpleNamespace(x=me[0], y=me[1])
    return party_loot_walk_meter(origin, 12)


def test_walk_meter_counts_steps_on_open_ground(monkeypatch) -> None:
    grid = np.ones((40, 40), dtype=bool)
    meter = _walk_meter(monkeypatch, grid, (10, 10))
    assert meter(SimpleNamespace(tile=(22, 10))) == 12
    assert meter(SimpleNamespace(tile=(23, 10))) == 13


def test_a_pile_behind_a_wall_is_out_of_walk_range(monkeypatch) -> None:
    # Wall at x=12 from y=0..30: a pile 4 tiles east needs a long detour.
    grid = np.ones((40, 40), dtype=bool)
    grid[0:31, 12] = False
    meter = _walk_meter(monkeypatch, grid, (10, 10))
    steps = meter(SimpleNamespace(tile=(14, 10)))
    assert steps > 12
    assert meter(SimpleNamespace(tile=(10, 18))) == 8


def test_walk_meter_needs_terrain(monkeypatch) -> None:
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: None)
    assert party_loot_walk_meter(SimpleNamespace(x=1, y=1), 12) is None


def test_random_loot_is_party_drops_without_an_ownership_gate() -> None:
    cfg = PartyMemberConfig(random_loot=True, loot_role="none", farm_mode="party")
    assert party_loot_ownership_filter(cfg) is False


def test_loot_beats_follow_and_assist_drops_it() -> None:
    assert party_may_start_loot("follow", allowed=True)
    assert party_may_start_loot("hold", allowed=True)
    assert not party_may_start_loot("assist", allowed=True)
    assert not party_may_start_loot("follow", allowed=False)
    assert not party_should_drop_loot("follow", allowed=True)
    assert party_should_drop_loot("assist", allowed=True)
    assert party_should_drop_loot("follow", allowed=False)


def test_leader_policy_does_not_carry_a_loot_priority() -> None:
    cfg = PartyMemberConfig(farm_mode="solo").merge_leader_policy(
        {
            "random_loot": False,
            "loot_role": "responsible",
            "loot_priority": "loot",
        },
        self_name="",
    )
    assert not hasattr(cfg, "loot_priority")
    assert cfg.loot_role == "responsible"
    assert cfg.farm_mode == "solo"
    assert cfg.random_loot is False


if __name__ == "__main__":
    test_leader_takes_no_pile()
    test_solo_pile_check_does_not_apply_the_leader_cap()
    test_responsible_loots_party_drops_not_only_own()
    test_other_members_loot_their_own_piles()
    test_near_radius_is_shared_and_responsible_is_wider()
    test_random_loot_is_party_drops_without_an_ownership_gate()
    test_loot_beats_follow_and_assist_drops_it()
    test_leader_policy_does_not_carry_a_loot_priority()
    print("OK")
