"""Stale Setup roles must not land on a filled live hotbar cell."""
from __future__ import annotations

from hotbar.inspect import DetectedCell, merge_detected_spell_slots


def test_merge_drops_hp_potion_on_wind_blade_cell() -> None:
    detected = {
        "heal": {"box": 1, "key": "f11", "enabled": True, "reuse_s": 0.5, "cast": "double"},
        "mage_attack": {
            "box": 1,
            "key": "f10",
            "enabled": True,
            "reuse_s": 0.5,
            "cast": "press",
        },
    }
    previous = {
        "hp_potion": {
            "box": 2,
            "key": "f11",
            "enabled": True,
            "reuse_s": 0.0,
            "cast": "press",
        },
        "heal": {"box": 1, "key": "f11", "enabled": True, "reuse_s": 0.5, "cast": "double"},
    }
    cells = [
        DetectedCell(box=1, key="f11", kr_name="heal", role="heal", kind="SPELL", bound=True),
        DetectedCell(
            box=1, key="f10", kr_name="light", role="mage_attack", kind="SPELL", bound=True
        ),
        DetectedCell(
            box=2,
            key="f11",
            kr_name="風刃",
            role="mage_attack",
            kind="SPELL",
            bound=False,
        ),
    ]
    merged = merge_detected_spell_slots(detected, previous, cells=cells)
    potion = merged.get("hp_potion") or {}
    # UI still wants potion, but must not keep wind-blade coordinates.
    assert int(potion.get("box") or 0) == 0
    assert str(potion.get("key") or "") in ("", "f11", "f5", "f9")


def test_merge_wants_role_without_inventing_empty_cell_key() -> None:
    detected = {
        "heal": {"box": 1, "key": "f11", "enabled": True, "reuse_s": 0.5, "cast": "double"},
    }
    previous = {
        "hp_potion": {
            "box": 2,
            "key": "f9",
            "enabled": True,
            "reuse_s": 0.0,
            "cast": "press",
        },
    }
    cells = [
        DetectedCell(box=1, key="f11", kr_name="heal", role="heal", kind="SPELL", bound=True),
        DetectedCell(box=2, key="f9", kind="EMPTY"),
    ]
    merged = merge_detected_spell_slots(detected, previous, cells=cells)
    potion = merged["hp_potion"]
    # UI still wants potion, but scan did not place it — no press key.
    assert potion.get("enabled") is True
    assert int(potion.get("box") or 0) == 0


if __name__ == "__main__":
    test_merge_drops_hp_potion_on_wind_blade_cell()
    test_merge_wants_role_without_inventing_empty_cell_key()
    print("merge live cells ok")
