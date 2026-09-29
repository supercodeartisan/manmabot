"""Attack eligibility is allow/deny only — no player vs monster level."""
from __future__ import annotations

from app._03_world import CharacterType, GameState, ObjectType
from app._03_world.constants import configure_species_filter
from app._03_world.objects import ObjectStatus, WorldObject
from app._04_decision.combat_query import list_attackable
from app._04_decision.target_selector import select_target


def _mob(track_id: int, species: str, *, rx: int = 1, ry: int = 0) -> WorldObject:
    return WorldObject(
        track_id=track_id,
        object_type=ObjectType.MONSTER,
        species_name=species,
        status=ObjectStatus.ALIVE,
        world_rx=rx,
        world_ry=ry,
    )


def _state(*mobs: WorldObject, level: int = 5) -> GameState:
    state = GameState(character_type=CharacterType.ELF)
    state.set_player(
        state.player.__class__(
            track_id=state.player.track_id,
            position=state.player.position,
            level=level,
            character_type=CharacterType.ELF,
        )
    )
    for mob in mobs:
        state._objects[mob.track_id] = mob
    return state


def test_higher_level_monster_is_attackable_unless_filtered() -> None:
    # dragon catalog level is 50; player is 5. Old logic skipped this as strong.
    dragon = _mob(1, "dragon")
    state = _state(dragon, level=5)
    configure_species_filter("blacklist", [], [])
    try:
        ids = {obj.track_id for obj in list_attackable(state, check_path=False)}
        assert 1 in ids
        assert select_target(state) is dragon
        configure_species_filter("blacklist", ["dragon"], [])
        assert list_attackable(state, check_path=False) == []
        assert select_target(state) is None
    finally:
        configure_species_filter("blacklist", [], [])


def test_level_five_or_over_must_not_attack_scarecrow() -> None:
    from app._04_decision.species_rules import is_scarecrow_species

    dummy = _mob(3, "monster_허수아비")
    chinese = _mob(4, "稻草人")
    assert is_scarecrow_species(dummy)
    assert is_scarecrow_species(chinese)
    configure_species_filter("blacklist", [], [])
    try:
        low = _state(dummy, level=4)
        ids = {obj.track_id for obj in list_attackable(low, check_path=False)}
        assert ids == {3}
        assert select_target(low) is dummy
        ready = _state(dummy, level=5)
        assert list_attackable(ready, check_path=False) == []
        assert select_target(ready) is None
        older = _state(dummy, level=12)
        assert list_attackable(older, check_path=False) == []
    finally:
        configure_species_filter("blacklist", [], [])


def test_occluded_memory_monster_is_still_attackable() -> None:
    hidden = _mob(8, "monster_오크", rx=3, ry=0)
    hidden.occluded = True
    hidden.world_cx = 13
    hidden.world_cy = 10
    state = _state(hidden, level=8)
    configure_species_filter("blacklist", [], [])
    try:
        ids = {obj.track_id for obj in list_attackable(state, check_path=False)}
        assert ids == {8}
    finally:
        configure_species_filter("blacklist", [], [])


def test_species_filter_does_not_use_click_range() -> None:
    from app._03_world.objects import Position
    from app._03_world.world_coords import WorldOrigin
    from app._04_decision.combat_query import in_attack_click_range

    far = _mob(9, "monster_오크", rx=12, ry=0)
    far.position = Position(0.35, 0.40)
    assert in_attack_click_range(far) is True
    state = _state(far, level=8)
    configure_species_filter("blacklist", [], [])
    try:
        kept = list_attackable(
            state, origin=WorldOrigin(x=10, y=10), check_path=True
        )
        assert [obj.track_id for obj in kept] == [9]
        configure_species_filter("blacklist", ["monster_오크"], [])
        assert list_attackable(state, check_path=False) == []
    finally:
        configure_species_filter("blacklist", [], [])


def test_whitelist_attacks_only_listed_species() -> None:
    orc = _mob(1, "monster_오크")
    wolf = _mob(2, "monster_늑대인간")
    state = _state(orc, wolf, level=1)
    configure_species_filter("whitelist", [], ["monster_오크"])
    try:
        ids = {obj.track_id for obj in list_attackable(state, check_path=False)}
        assert ids == {1}
    finally:
        configure_species_filter("blacklist", [], [])


def test_whitelist_orc_fighter_matches_spaced_and_compact_keys() -> None:
    fighter = _mob(3, "monster_오크전사_8")
    compact = _mob(4, "오크전사")
    spaced = _mob(5, "monster_오크 전사")
    wolf = _mob(6, "monster_늑대인간")
    state = _state(fighter, compact, spaced, wolf, level=8)
    configure_species_filter("whitelist", [], ["monster_오크 전사"])
    try:
        ids = {obj.track_id for obj in list_attackable(state, check_path=False)}
        assert ids == {3, 4, 5}
    finally:
        configure_species_filter("blacklist", [], [])
