"""Golem catalog levels stay available; attack eligibility is allow/deny only."""
from __future__ import annotations

from app._03_world.constants import configure_species_level_overrides
from app._03_world.objects import ObjectType, WorldObject
from app._04_decision.species_rules import (
    golem_blocked_by_player_level,
    golem_required_player_level,
    is_avoided_species,
    is_golem_species,
)


def _golem(
    species: str = "monster_돌 골렘",
    *,
    rx: int = 1,
    ry: int = 0,
    detail: str | None = None,
) -> WorldObject:
    return WorldObject(
        track_id=1,
        object_type=ObjectType.MONSTER,
        species_name=species,
        detail_classification=detail,
        world_rx=rx,
        world_ry=ry,
    )


def test_stone_and_lava_are_golem_family() -> None:
    assert is_golem_species(_golem("monster_돌 골렘"))
    assert is_golem_species(_golem("monster_라바 골렘"))


def test_catalog_level_is_minimum_to_attack_awake_golem() -> None:
    stone = _golem("monster_돌 골렘")
    lava = _golem("monster_라바 골렘")
    configure_species_level_overrides({})
    try:
        assert golem_required_player_level(stone) == 13
        assert golem_required_player_level(lava) == 43
        assert golem_blocked_by_player_level(stone, 12)
        assert not golem_blocked_by_player_level(stone, 13)
        assert golem_blocked_by_player_level(lava, 42)
        assert not golem_blocked_by_player_level(lava, 43)
        assert not is_avoided_species(stone, player_level=12)
        assert not is_avoided_species(stone, player_level=13)
    finally:
        configure_species_level_overrides({})


def test_forced_level_from_species_list_overrides_catalog() -> None:
    stone = _golem("monster_돌 골렘")
    configure_species_level_overrides({"monster_돌 골렘": 20})
    try:
        assert golem_required_player_level(stone) == 20
        assert golem_blocked_by_player_level(stone, 19)
        assert not golem_blocked_by_player_level(stone, 20)
        assert not is_avoided_species(stone, player_level=19)
        assert not is_avoided_species(stone, player_level=20)
    finally:
        configure_species_level_overrides({})


def test_unknown_player_level_does_not_attack_golem() -> None:
    stone = _golem("monster_돌 골렘")
    configure_species_level_overrides({})
    try:
        assert golem_blocked_by_player_level(stone, None)
        assert not is_avoided_species(stone, player_level=None)
    finally:
        configure_species_level_overrides({})


def test_sleeping_golem_is_never_attacked() -> None:
    sleeper = _golem("monster_골램_50")
    configure_species_level_overrides({})
    try:
        assert is_avoided_species(sleeper, player_level=50)
        assert not golem_blocked_by_player_level(sleeper, 50)
    finally:
        configure_species_level_overrides({})


def test_far_golem_still_skipped_nearby_golem_is_allowed() -> None:
    nearby = _golem(rx=1, ry=0)
    far = _golem(rx=5, ry=4)
    configure_species_level_overrides({})
    try:
        assert not is_avoided_species(nearby, player_level=1)
        assert is_avoided_species(far, player_level=50)
    finally:
        configure_species_level_overrides({})
