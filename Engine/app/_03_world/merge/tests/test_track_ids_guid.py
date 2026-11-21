"""TrackIds prefer guid so heap ent remaps keep the same track_id."""
from __future__ import annotations

from app._03_world.merge.memory_entities import TrackIds, entities_to_handoff


def _item_snap(*, ent: str, guid: str) -> dict:
    return {
        "client_w": 800,
        "client_h": 600,
        "player": {"x": 100, "y": 200},
        "entities": [
            {
                "ent": ent,
                "guid": guid,
                "class": "Item",
                "name": "金幣",
                "species": 57,
                "own": "MINE",
                "contrib": 100,
                "world": {"cx": 32640, "cy": 33100},
                "iscr": {"x": 400.0, "y": 300.0},
            }
        ],
    }


def test_same_guid_keeps_track_id_when_ent_changes() -> None:
    tracks = TrackIds()
    first = entities_to_handoff(
        _item_snap(ent="0xAAAA", guid="0x474F24D"),
        id_map=tracks,
        species={},
        aliases={},
    )
    second = entities_to_handoff(
        _item_snap(ent="0xBBBB", guid="0x474F24D"),
        id_map=tracks,
        species={},
        aliases={},
    )
    assert len(first) == 1 and len(second) == 1
    assert first[0]["track_id"] == second[0]["track_id"]
    assert first[0]["memory_guid"] == "0x474F24D"


def test_missing_guid_falls_back_to_ent() -> None:
    tracks = TrackIds()
    a = entities_to_handoff(
        _item_snap(ent="0xAAAA", guid="0x0"),
        id_map=tracks,
        species={},
        aliases={},
    )
    b = entities_to_handoff(
        _item_snap(ent="0xBBBB", guid="0x0"),
        id_map=tracks,
        species={},
        aliases={},
    )
    assert a[0]["track_id"] != b[0]["track_id"]
