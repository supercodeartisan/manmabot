"""Tile ↔ world conversion. Origins come from the loaded pack, never a hardcoded map."""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from app._03_world.space.tile_world import (
    PackAxes,
    axes_from_pack,
    clamp_popup_top_left,
    parse_world_int,
    stored_world_note,
    stored_world_tuple,
)
from app._04_decision.world_nav.ready.map_assets import discover_map_packs
from app._06_party.leader_schedule import hunt_marks
from session.probes import load_map_pack_safe


def test_mainland_origin_is_tile_zero_and_pixel_scale_is_not_a_world_multiplier() -> None:
    pack = load_map_pack_safe("mainland")
    assert pack is not None
    assert pack.id == "mainland"
    assert (pack.origin_x, pack.origin_y, pack.pixel_scale) == (32448, 32128, 4)
    axes = axes_from_pack(pack)
    assert axes is not None
    assert axes.tile_to_world(0, 0) == (32448, 32128)
    assert axes.tile_to_world(421, 1143) == (32869, 33271)
    assert axes.world_to_tile(32869, 33271) == (421, 1143)
    # 4 image pixels per tile. Multiplying the tile by that scale is a different coordinate.
    assert axes.tile_to_world(421, 1143) != (32448 + 421 * 4, 32128 + 1143 * 4)


def test_other_maps_keep_their_own_origin_and_pixel_scale() -> None:
    scaled = load_map_pack_safe("mainland")
    unit = load_map_pack_safe("dragon_valley_dungeon_F4")
    assert scaled is not None and unit is not None
    assert unit.pixel_scale == 1
    assert (unit.origin_x, unit.origin_y) != (scaled.origin_x, scaled.origin_y)
    axes = axes_from_pack(unit)
    assert axes is not None
    assert axes.pixel_scale == 1
    assert axes.tile_to_world(10, 20) == (unit.origin_x + 10, unit.origin_y + 20)
    same_origin = PackAxes("scaled", scaled.origin_x, scaled.origin_y, 4)
    flat_origin = PackAxes("flat", scaled.origin_x, scaled.origin_y, 1)
    assert same_origin.tile_to_world(10, 20) == flat_origin.tile_to_world(10, 20)


def test_integer_round_trip_and_y_grows_with_the_tile() -> None:
    axes = PackAxes("sample", 32576, 32704, 1)
    tiles = [(0, 0), (1, 0), (0, 1), (421, 1143), (-3, 8)]
    for tile in tiles:
        assert axes.world_to_tile(*axes.tile_to_world(*tile)) == tile
    worlds = [(32576, 32704), (32580, 32709), (30000, 34000)]
    for world in worlds:
        assert axes.tile_to_world(*axes.world_to_tile(*world)) == world
    assert axes.tile_to_world(0, 5)[1] - axes.origin_y == 5
    assert axes.tile_to_world(5, 0)[0] - axes.origin_x == 5


def test_missing_pack_metadata_does_not_invent_an_origin() -> None:
    assert axes_from_pack(None) is None
    assert axes_from_pack(SimpleNamespace(id="orphan")) is None
    assert axes_from_pack(SimpleNamespace(id="orphan", origin_x=1, origin_y=2)) is None
    assert (
        axes_from_pack(SimpleNamespace(id="orphan", origin_x=1, origin_y=2, pixel_scale=0))
        is None
    )
    assert (
        axes_from_pack(SimpleNamespace(id="", origin_x=1, origin_y=2, pixel_scale=1))
        is None
    )
    assert stored_world_tuple(None, {"shape": "point", "x": 1, "y": 2}) is None
    assert stored_world_note(None, {"shape": "point", "x": 1, "y": 2}, unavailable="missing") == (
        "missing"
    )


def test_map_244_packs_keep_the_origin_of_their_own_folder() -> None:
    packs = [pack for pack in discover_map_packs() if int(pack.map_id) == 244]
    assert packs
    seen: dict[str, tuple[int, int]] = {}
    for pack in packs:
        axes = axes_from_pack(pack)
        assert axes is not None
        assert axes.pack_id == pack.pack_id
        assert axes.tile_to_world(0, 0) == (pack.origin_x, pack.origin_y)
        seen[pack.pack_id] = (pack.origin_x, pack.origin_y)
    loaded = load_map_pack_safe("polluted_land_of_blessing_dungeon")
    assert loaded is not None
    assert int(loaded.origin_x) == seen["polluted_land_of_blessing_dungeon"][0]
    other = axes_from_pack(
        SimpleNamespace(id="other_244", origin_x=1, origin_y=2, pixel_scale=4)
    )
    assert other is not None
    assert other.tile_to_world(3, 4) == (4, 6)
    assert other.origin_x != loaded.origin_x


def test_duplicate_numeric_map_ids_do_not_share_one_origin() -> None:
    groups: dict[int, list] = defaultdict(list)
    for pack in discover_map_packs():
        groups[int(pack.map_id)].append(pack)
    for packs in groups.values():
        origins = {}
        for pack in packs:
            axes = axes_from_pack(pack)
            assert axes is not None
            assert axes.pack_id == pack.pack_id
            origins[pack.pack_id] = axes.tile_to_world(0, 0)
        assert len(origins) == len(packs)


def test_display_note_does_not_rewrite_the_stored_mark() -> None:
    pack = load_map_pack_safe("mainland")
    axes = axes_from_pack(pack)
    area = {"name": "point_1", "shape": "point", "region": "mainland", "x": 421, "y": 1143}
    before = dict(area)
    assert stored_world_note(axes, area, unavailable="missing") == "(32869, 33271)"
    assert area == before
    rect = {"name": "area_1", "shape": "area", "x0": 421, "y0": 1143, "x1": 533, "y1": 1315}
    rect_before = dict(rect)
    assert stored_world_note(axes, rect, unavailable="missing") == "(32869, 33271 ~ 32981, 33443)"
    assert rect == rect_before


def test_hunt_marks_still_read_the_stored_tile() -> None:
    row = {
        "areas": [{"name": "point_1", "shape": "point", "x": 421, "y": 1143}],
        "selected_farms": ["point_1"],
    }
    mark = hunt_marks(row)[0]
    assert mark["x0"] == 421
    assert mark["y0"] == 1143
    assert mark["x1"] == 421
    assert mark["y1"] == 1143


def test_parse_world_int_rejects_non_integers() -> None:
    assert parse_world_int(" 32869 ") == 32869
    assert parse_world_int("-12") == -12
    assert parse_world_int("+7") == 7
    assert parse_world_int("") is None
    assert parse_world_int("12.5") is None
    assert parse_world_int("12a") is None
    assert parse_world_int("1e2") is None


def test_popup_top_left_stays_on_the_point_until_it_would_leave_the_view() -> None:
    assert clamp_popup_top_left(10, 20, 40, 16, 0, 0, 200, 100) == (10, 20)
    assert clamp_popup_top_left(180, 20, 40, 16, 0, 0, 200, 100) == (161, 20)
    assert clamp_popup_top_left(10, 90, 40, 16, 0, 0, 200, 100) == (10, 85)
    assert clamp_popup_top_left(-30, -10, 40, 16, 0, 0, 200, 100) == (0, 0)
    assert clamp_popup_top_left(10, 20, 500, 400, 5, 6, 100, 80) == (5, 6)
