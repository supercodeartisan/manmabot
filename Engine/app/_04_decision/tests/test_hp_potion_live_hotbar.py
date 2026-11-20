"""HP potion presses require a live/layout potion cell, not Setup alone."""
from __future__ import annotations

from app._04_decision.hp_actions import find_hp_restore_hotbar
from settings.hp_actions import apply_recovery_to_spell_slots


class _World:
    def __init__(self, layout: dict | None = None, snap: dict | None = None) -> None:
        self.hotbar_layout = layout
        self.last_hotbar = snap


def test_find_hp_restore_ignores_setup_slot_on_spell_cell() -> None:
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
    assert find_hp_restore_hotbar(_World(layout), "빨간 물약") is None


def test_find_hp_restore_uses_layout_potion_name() -> None:
    layout = {
        "boxes": {
            "2": {
                "f5": {
                    "box": 2,
                    "key": "f5",
                    "kr_name": "빨간 물약",
                    "role": "",
                    "kind": "ITEM",
                }
            }
        }
    }
    assert find_hp_restore_hotbar(_World(layout), "빨간 물약") == (2, "f5")


def test_apply_recovery_refuses_wind_blade_as_potion() -> None:
    slots = {
        "heal": {"box": 1, "key": "f11", "enabled": True, "reuse_s": 0.5, "cast": "double"},
        "hp_potion": {
            "box": 2,
            "key": "f11",
            "enabled": True,
            "reuse_s": 0.0,
            "cast": "press",
        },
    }
    actions = [
        {"id": "hp_potion", "enabled": True, "hp_below": 80, "box": 2, "key": "f11"},
        {"id": "heal", "enabled": True, "hp_below": 70, "box": 1, "key": "f11"},
    ]
    layout = {
        "boxes": {
            "1": {
                "f11": {
                    "box": 1,
                    "key": "f11",
                    "kr_name": "heal",
                    "role": "heal",
                    "kind": "SPELL",
                }
            },
            "2": {
                "f11": {
                    "box": 2,
                    "key": "f11",
                    "kr_name": "風刃",
                    "role": "mage_attack",
                    "kind": "SPELL",
                }
            },
        }
    }
    merged = apply_recovery_to_spell_slots(slots, actions, layout=layout)
    assert merged["heal"]["enabled"] is True
    assert int(merged["heal"]["box"]) == 1
    assert not merged["hp_potion"].get("enabled")
    assert int(merged["hp_potion"].get("box") or 0) == 0


if __name__ == "__main__":
    test_find_hp_restore_ignores_setup_slot_on_spell_cell()
    test_find_hp_restore_uses_layout_potion_name()
    test_apply_recovery_refuses_wind_blade_as_potion()
    print("hp potion live hotbar ok")
