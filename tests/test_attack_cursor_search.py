"""Attack cursor is hunted in a 1-tile ring around the memory cell."""
from __future__ import annotations

from types import SimpleNamespace

from app._03_world.objects import ObjectType, Position, WorldObject
from app._03_world.world_coords import content_to_world
from app._05_action.cursor_verify import attack_click_search
from app._05_action.travel_click import object_cursor_search_destinations


def test_search_includes_primary_and_one_tile_ring() -> None:
    obj = WorldObject(
        track_id=1,
        object_type=ObjectType.MONSTER,
        position=Position(x=0.5, y=0.5),
        world_rx=1,
        world_ry=0,
    )
    dests = object_cursor_search_destinations(obj, radius=1)
    assert dests[0].x == 0.5 and dests[0].y == 0.5
    tiles = {(int(t.x), int(t.y)) for t in (content_to_world(p.x, p.y) for p in dests[1:])}
    assert (1, 0) in tiles
    assert (2, 0) in tiles
    assert (1, 1) in tiles
    assert (0, 0) not in tiles
    assert len(dests) >= 5


def test_loot_points_stay_on_the_pile() -> None:
    from app._04_decision import player_mode as pm
    from app._05_action.cursor_verify import object_loot_screen_points
    from app._05_action.travel_click import object_cursor_search_destinations

    obj = WorldObject(
        track_id=1,
        object_type=ObjectType.ITEM,
        position=Position(x=0.62, y=0.41),
        world_rx=1,
        world_ry=0,
    )
    dests = object_cursor_search_destinations(
        obj, radius=pm.LOOT_CURSOR_SEARCH_TILES
    )
    tiles = {
        (int(t.x), int(t.y))
        for t in (content_to_world(p.x, p.y) for p in dests)
    }
    assert pm.LOOT_CURSOR_SEARCH_TILES == 0.0
    assert (2, 0) not in tiles
    assert (1, 1) not in tiles
    assert len(dests) <= 2

    def screen_point(nx, ny, _bounds):
        return (nx * 100.0, ny * 100.0)

    executor = SimpleNamespace(_screen_point=screen_point)
    points = object_loot_screen_points(executor, obj, None)
    assert len(points) == len(dests)
    assert all(isinstance(p, tuple) and len(p) == 2 for p in points)


def test_default_hunt_is_point_two_tiles() -> None:
    from app._04_decision import player_mode as pm

    obj = WorldObject(
        track_id=1,
        object_type=ObjectType.MONSTER,
        position=Position(x=0.5, y=0.5),
        world_rx=1,
        world_ry=0,
    )
    dests = object_cursor_search_destinations(obj)
    tiles = {
        (int(t.x), int(t.y))
        for t in (content_to_world(p.x, p.y) for p in dests[1:])
    }
    assert pm.ATTACK_CURSOR_SEARCH_TILES == 0.2
    assert (1, 0) in tiles
    assert (2, 0) not in tiles
    assert (1, 1) not in tiles


def test_search_includes_one_and_a_half_tile_ring() -> None:
    obj = WorldObject(
        track_id=1,
        object_type=ObjectType.MONSTER,
        position=Position(x=0.5, y=0.5),
        world_rx=1,
        world_ry=0,
    )
    tight = object_cursor_search_destinations(obj, radius=1)
    wide = object_cursor_search_destinations(obj, radius=1.5)
    assert len(wide) > len(tight)


def test_attack_click_search_uses_neighbor_when_center_fails(monkeypatch) -> None:
    from app._05_action import cursor_verify

    clicks: list[tuple[float, float]] = []

    def fake_probe(_executor, x, y, _labels):
        if (x, y) == (20.0, 20.0):
            return SimpleNamespace(label="sword", handle=2, score=0.9)
        return None

    monkeypatch.setattr(cursor_verify, "_probe_labels", fake_probe)
    monkeypatch.setattr(cursor_verify, "CURSOR_VERIFY_ENABLED", True)
    executor = SimpleNamespace(
        last_cursor_match=None,
        last_cursor_reject_reason=None,
        mouse=SimpleNamespace(click=lambda x, y, snap=True: clicks.append((x, y))),
    )
    assert attack_click_search(executor, [(1.0, 1.0), (20.0, 20.0)]) is True
    assert clicks == [(20.0, 20.0)]


def test_attack_points_try_body_before_pixel_ring() -> None:
    from app._05_action.cursor_verify import object_attack_screen_points

    obj = WorldObject(
        track_id=1,
        object_type=ObjectType.MONSTER,
        position=Position(x=0.50, y=0.40),
        world_rx=2,
        world_ry=0,
    )

    def screen_point(nx, ny, _bounds):
        return (round(nx, 3), round(ny, 3))

    executor = SimpleNamespace(_screen_point=screen_point)
    points = object_attack_screen_points(executor, obj, None)
    assert points[0] == (0.5, 0.4)
    extras = {(1.0, 0.4), (0.5, 0.3)}
    assert points[1] not in extras


def test_attack_pixel_ring_starts_above_sprite() -> None:
    from app._05_action.cursor_verify import attack_pixel_offsets

    points = attack_pixel_offsets(100.0, 200.0, radii=(10.0,), n=8)
    assert points[0] == (100.0, 190.0)
    assert len(points) == 8


def test_attack_click_search_stops_on_arrow_lack(monkeypatch) -> None:
    from app._05_action import cursor_verify

    clicks: list[tuple[float, float]] = []

    def fake_probe(executor, x, y, _labels):
        match = SimpleNamespace(label="arrow_lack", handle=3, score=0.9)
        executor.last_cursor_match = match
        return match

    monkeypatch.setattr(cursor_verify, "_probe_labels", fake_probe)
    monkeypatch.setattr(cursor_verify, "CURSOR_VERIFY_ENABLED", True)
    executor = SimpleNamespace(
        last_cursor_match=None,
        last_cursor_reject_reason=None,
        mouse=SimpleNamespace(click=lambda x, y, snap=True: clicks.append((x, y))),
    )
    assert attack_click_search(executor, [(1.0, 1.0), (20.0, 20.0)]) is False
    assert clicks == []


def test_attack_click_search_skips_dialog_point(monkeypatch) -> None:
    from app._05_action import cursor_verify

    clicks: list[tuple[float, float]] = []
    probed: list[set[str]] = []

    def fake_probe(_executor, x, y, labels):
        probed.append({str(label) for label in labels})
        if (x, y) == (1.0, 1.0):
            return SimpleNamespace(label="dialog", handle=4, score=0.95)
        return SimpleNamespace(label="sword", handle=5, score=0.9)

    monkeypatch.setattr(cursor_verify, "_probe_labels", fake_probe)
    monkeypatch.setattr(cursor_verify, "CURSOR_VERIFY_ENABLED", True)
    executor = SimpleNamespace(
        last_cursor_match=None,
        last_cursor_reject_reason=None,
        mouse=SimpleNamespace(click=lambda x, y, snap=True: clicks.append((x, y))),
    )
    assert attack_click_search(executor, [(1.0, 1.0), (20.0, 20.0)]) is True
    assert clicks == [(20.0, 20.0)]
    assert any("dialog" in labels for labels in probed)


def test_dialog_click_allowed_only_for_shop() -> None:
    from app._05_action.cursor_catalog import DIALOG_OK_CATEGORIES
    from app._05_action.cursor_verify import _dialog_click_allowed

    assert _dialog_click_allowed(categories=DIALOG_OK_CATEGORIES) is True
    assert _dialog_click_allowed(labels=("dialog",)) is True
    assert _dialog_click_allowed(labels=("arrow", "fist", "sword")) is False
    assert _dialog_click_allowed(categories=None, labels=None) is False
