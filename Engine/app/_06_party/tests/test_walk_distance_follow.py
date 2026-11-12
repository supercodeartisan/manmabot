"""Walk steps, not Chebyshev, decide the stand beside the leader and the follow."""
from __future__ import annotations

import numpy as np

from app._03_world.space.terrain_map import TerrainMap
from app._06_party.config import PartyMemberConfig
from app._06_party.follow_field import build_follow_field, nearest_walkable
from app._06_party.policy import MemberKind, PolicyInput, decide_policy


def _wall_map(gap: bool = True) -> TerrainMap:
    """20×20 open ground. Column x=5 is a wall from y=0 to 15; open below if ``gap``."""
    grid = np.ones((20, 20), dtype=bool)
    grid[0:16, 5] = False
    if not gap:
        grid[:, 5] = False
    return TerrainMap.from_array(grid)


def _origin(x: int, y: int):
    return type("O", (), {"x": x, "y": y})()


def _policy(**kwargs) -> PolicyInput:
    base = dict(
        paused=False,
        dead=False,
        origin_ok=True,
        leader_present=True,
        leader_dist=2,
        chasing=False,
        need_potion=False,
        self_threat=False,
        assist_ready=False,
        config=PartyMemberConfig(),
        leader_walk_dist=None,
    )
    base.update(kwargs)
    return PolicyInput(**base)


def test_a_wall_between_is_not_beside_the_leader():
    field = build_follow_field(_wall_map(), (6, 5), 18)
    walk = field.walk_distance((4, 5), 2)
    assert walk > 20


def test_no_walk_inside_the_window_is_never_close():
    field = build_follow_field(_wall_map(gap=False), (6, 5), 18)
    assert field.reached((4, 5)) is False
    assert field.walk_distance((4, 5), 2) == 19


def test_a_leader_on_a_blocked_cell_is_still_reached():
    grid = np.ones((20, 20), dtype=bool)
    grid[10, 10] = False
    field = build_follow_field(TerrainMap.from_array(grid), (10, 10), 8)
    assert field.steps((12, 10)) == 2
    assert field.steps((11, 11)) == 1


def test_a_member_on_a_blocked_cell_counts_from_the_next_tile():
    grid = np.ones((20, 20), dtype=bool)
    grid[10, 12] = False
    field = build_follow_field(TerrainMap.from_array(grid), (10, 10), 8)
    assert field.steps((12, 10)) is None
    assert field.member_steps((12, 10)) == 2


def test_two_tiles_across_a_wall_follows_and_two_open_tiles_hold():
    across = decide_policy(_policy(leader_dist=2, leader_walk_dist=22))
    assert across.kind is MemberKind.FOLLOW
    assert "walk=22" in across.reason
    beside = decide_policy(_policy(leader_dist=2, leader_walk_dist=2))
    assert beside.kind is MemberKind.HOLD
    unknown = decide_policy(_policy(leader_dist=2, leader_walk_dist=None))
    assert unknown.kind is MemberKind.HOLD


def test_a_fighting_leader_across_a_wall_pulls_the_member_around():
    leash = decide_policy(
        _policy(leader_dist=2, leader_walk_dist=22, leader_farming=True)
    )
    assert leash.kind is MemberKind.FOLLOW
    assert leash.reason.startswith("follow_combat_leash")
    near = decide_policy(
        _policy(leader_dist=2, leader_walk_dist=5, leader_farming=True)
    )
    assert near.kind is MemberKind.FOLLOW
    assert near.reason.startswith("follow_combat_near")
    held = decide_policy(
        _policy(leader_dist=2, leader_walk_dist=2, leader_farming=True)
    )
    assert held.kind is MemberKind.HOLD


def test_the_walk_cost_counts_the_detour():
    from app._06_party.follow_route import estimate_walk_steps

    steps = estimate_walk_steps(_wall_map(), (4, 5), (6, 5))
    assert steps is not None and steps > 20
    open_steps = estimate_walk_steps(_wall_map(), (6, 5), (9, 5))
    assert open_steps == 3


def test_a_blocked_leader_cell_snaps_to_the_member_side():
    grid = np.ones((20, 20), dtype=bool)
    grid[10, 10] = False
    terrain = TerrainMap.from_array(grid)
    assert nearest_walkable(terrain, (10, 10), toward=(4, 10)) == (9, 10)
    assert nearest_walkable(terrain, (3, 3)) == (3, 3)


def test_a_click_behind_a_wall_corner_is_not_clickable():
    from app._06_party.intents import _client_walk_clear

    grid = np.ones((20, 20), dtype=bool)
    grid[5, 5] = False
    grid[5, 6] = False
    terrain = TerrainMap.from_array(grid)
    assert _client_walk_clear(terrain, _origin(4, 4), (6, 6)) is False
    assert _client_walk_clear(terrain, _origin(4, 4), (4, 7)) is True


def test_an_unstick_click_shortens_the_walk_and_skips_tried_tiles(monkeypatch):
    from app._06_party import intents

    terrain = _wall_map()
    monkeypatch.setattr("app._04_decision.nav_config.get_terrain_map", lambda: terrain)
    field = build_follow_field(terrain, (6, 5), 18)
    before = field.member_steps((4, 5))
    picked = intents.plan_follow_unstick(
        _origin(4, 5), (6, 5), walk_steps=field.member_steps
    )
    assert picked is not None
    _intent, goal, detail, tile = picked
    assert goal == (6, 5)
    assert detail.startswith("unstick hop")
    assert tile[0] != 5
    assert field.member_steps(tile) < before
    again = intents.plan_follow_unstick(
        _origin(4, 5), (6, 5), walk_steps=field.member_steps, tried=[tile]
    )
    assert again is not None and again[3] != tile


def test_a_stuck_follow_waits_then_clicks_once(monkeypatch):
    from app._06_party import manager as mgr_mod
    from app._06_party.follow import FOLLOW_STUCK_S
    from app._06_party.manager import PartyMemberManager
    from app._06_party.state import MemberRuntime
    import random

    clock = {"t": 100.0}
    monkeypatch.setattr(mgr_mod.time, "monotonic", lambda: clock["t"])
    calls = []

    def _unstick(origin, leader, **kwargs):
        calls.append(list(kwargs.get("tried") or []))
        return ("intent", leader, "unstick hop 1,1 → 6,5", (1, 1))

    monkeypatch.setattr(mgr_mod, "plan_follow_unstick", _unstick)
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    mgr._rng = random.Random(0)
    me = _origin(4, 5)

    assert mgr._follow_stuck_escape(me, (6, 5), None, None) is None
    t = 0.0
    while t + 0.5 < FOLLOW_STUCK_S:
        t += 0.5
        clock["t"] = 100.0 + t
        assert mgr._follow_stuck_escape(me, (6, 5), None, None) is None
    clock["t"] = 100.0 + FOLLOW_STUCK_S + 0.1
    picked = mgr._follow_stuck_escape(me, (6, 5), None, None)
    assert picked is not None and picked[3] == (1, 1)
    assert calls == [[]]
    assert mgr.runtime.scratch["follow_stuck"]["tried"] == [(1, 1)]


def test_a_heal_gap_does_not_count_as_stuck(monkeypatch):
    from app._06_party import manager as mgr_mod
    from app._06_party.follow import FOLLOW_STUCK_S
    from app._06_party.manager import PartyMemberManager
    from app._06_party.state import MemberRuntime
    import random

    clock = {"t": 100.0}
    monkeypatch.setattr(mgr_mod.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(
        mgr_mod,
        "plan_follow_unstick",
        lambda *_a, **_k: ("intent", (6, 5), "unstick", (1, 1)),
    )
    mgr = PartyMemberManager.__new__(PartyMemberManager)
    mgr.runtime = MemberRuntime()
    mgr._rng = random.Random(0)
    me = _origin(4, 5)
    assert mgr._follow_stuck_escape(me, (6, 5), None, None) is None
    clock["t"] = 100.0 + FOLLOW_STUCK_S + 2.0
    assert mgr._follow_stuck_escape(me, (6, 5), None, None) is None
