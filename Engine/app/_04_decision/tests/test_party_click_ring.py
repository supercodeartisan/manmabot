"""Party clicks skip a player's sprite. Solo clicks keep the center only."""
from __future__ import annotations

from app._02_state.objects import ObjectStatus, ObjectType, Relationship
from app._03_world.space.world_coords import WorldOrigin
from app._04_decision.avoidance import click_bodies


class _Body:
    def __init__(self, kind: ObjectType, x: int, y: int, track: int) -> None:
        self.object_type = kind
        self.status = ObjectStatus.ALIVE
        self.relationship = Relationship.NEUTRAL
        self.track_id = track
        self.world_cx = x
        self.world_cy = y
        self.memory_class = "monster" if kind is ObjectType.MONSTER else "player"


class _State:
    def __init__(self) -> None:
        self.objects = self
        self._rows = [
            _Body(ObjectType.PLAYER, 11, 11, 1),
            _Body(ObjectType.MONSTER, 14, 10, 2),
        ]

    def all_objects(self) -> list:
        return list(self._rows)


class _Board:
    def __init__(self, party: bool) -> None:
        self.scratch = {"party_player_ring": True} if party else {}


def test_solo_click_keeps_only_living_centers() -> None:
    origin = WorldOrigin(x=10, y=10)
    tiles = click_bodies(_State(), origin, _Board(False))
    assert (11, 11) in tiles
    assert (14, 10) in tiles
    assert (12, 11) not in tiles
    assert (15, 10) not in tiles
    assert (10, 10) not in tiles


def test_party_click_closes_the_tiles_touching_a_player() -> None:
    origin = WorldOrigin(x=10, y=10)
    tiles = click_bodies(_State(), origin, _Board(True))
    assert (11, 11) in tiles
    assert (12, 11) in tiles
    assert (11, 12) in tiles
    assert (10, 10) not in tiles
    assert (14, 10) in tiles
    assert (15, 10) not in tiles
