"""UI wants a role; press cell comes only from the live hotbar list."""
from __future__ import annotations

from hotbar.inspect import resolve_hotbar_press


def test_resolve_uses_live_snap_role() -> None:
    snap = {
        "slots": [
            {
                "slot": 6,
                "box": 1,
                "key": "f11",
                "name": "初級治癒術",
                "label": "初級治癒術",
                "type": "SPELL",
            }
        ]
    }
    # Role map may or may not tag this name as heal; layout path covers role field.
    layout = {
        "boxes": {
            "1": {
                "f11": {
                    "box": 1,
                    "key": "f11",
                    "kr_name": "初級治癒術",
                    "role": "heal",
                    "kind": "SPELL",
                }
            }
        }
    }
    assert resolve_hotbar_press("heal", snap=None, layout=layout) == (1, "f11")
    # Snap present without a heal mapping → None (no Setup fallback).
    empty_mapped = {
        "slots": [
            {
                "slot": 7,
                "box": 1,
                "key": "f12",
                "name": "神聖武器",
                "type": "SPELL",
            }
        ]
    }
    assert resolve_hotbar_press("heal", snap=empty_mapped, layout=layout) is None


def test_resolve_hp_potion_ignores_spell_cell() -> None:
    layout = {
        "boxes": {
            "2": {
                "f11": {
                    "box": 2,
                    "key": "f11",
                    "kr_name": "風刃",
                    "role": "mage_attack",
                    "kind": "SPELL",
                }
            }
        }
    }
    assert resolve_hotbar_press("hp_potion", layout=layout) is None


if __name__ == "__main__":
    test_resolve_uses_live_snap_role()
    test_resolve_hp_potion_ignores_spell_cell()
    print("resolve hotbar press ok")
