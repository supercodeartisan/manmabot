"""Unit tests for hotbar role mapping (no screen capture required)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import random

from manmabot_v1.hotbar.inspect import (
    DetectedCell,
    DetectedLayout,
    HotbarInspectError,
    _disabled_slots,
    count_from_hotbar_label,
    find_role_on_hotbar,
    hotbar_has_role,
    fold_hotbar_name,
    hotbar_arrow_slot,
    load_role_map,
    merge_detected_spell_slots,
    next_hotbar_refresh_s,
    resolve_role,
    role_map_path,
    slot_to_box_key,
)
from manmabot_v1.spell_defaults import SLOT_IDS


class HotbarInspectTests(unittest.TestCase):
    def test_role_map_file_exists(self) -> None:
        path = role_map_path()
        self.assertTrue(path.is_file(), path)
        lookups = load_role_map(path)
        self.assertIn("__templates__", lookups)
        self.assertIn("__icons__", lookups)
        self.assertEqual(resolve_role("", "힐", "", lookups), "heal")
        self.assertEqual(resolve_role("", "初級治癒術", "", lookups), "heal")
        self.assertEqual(resolve_role("", "初級治癒術(4/0)", "", lookups), "heal")
        self.assertEqual(resolve_role("", "傳送術", "", lookups), "teleport")
        self.assertEqual(
            resolve_role("", "체력 회복제 (11)", "", lookups), "hp_potion"
        )
        self.assertEqual(resolve_role("", "비취 물약", "", lookups), "depoison")
        self.assertEqual(resolve_role("", "말하는 두루마리", "", lookups), "talking_scroll")
        self.assertEqual(resolve_role("", "說話的卷軸", "", lookups), "talking_scroll")
        self.assertEqual(resolve_role("", "说话的卷轴", "", lookups), "talking_scroll")
        self.assertEqual(resolve_role("", "说话卷轴", "", lookups), "talking_scroll")
        self.assertEqual(resolve_role("", "说话的卷轴 (3)", "", lookups), "talking_scroll")
        self.assertEqual(resolve_role("", "传送术", "", lookups), "teleport")
        self.assertEqual(resolve_role("", "初级治愈术", "", lookups), "heal")
        self.assertEqual(resolve_role("", "世界树的呼唤", "", lookups), "mother_tree")
        self.assertEqual(resolve_role("", "红色药水", "", lookups), "hp_potion")
        self.assertEqual(resolve_role("", "体力回复剂", "", lookups), "hp_potion")

    def test_resolve_role_prefers_template(self) -> None:
        lookups = {
            "__templates__": {"spells/1단계/힐.png": "heal"},
            "__kr__": {"힐": "mage_attack"},
            "__zh__": {"初級治癒術": "light"},
        }
        self.assertEqual(
            resolve_role("spells/1단계/힐.png", "힐", "初級治癒術", lookups),
            "heal",
        )

    def test_load_role_map_rejects_unknown_role(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.csv"
            path.write_text(
                "template,kr_name,zh_name,role\n"
                "spells/x.png,x,,not_a_role\n",
                encoding="utf-8",
            )
            with self.assertRaises(HotbarInspectError):
                load_role_map(path)

    def test_disabled_slots_and_layout(self) -> None:
        slots = _disabled_slots()
        for sid in SLOT_IDS:
            self.assertFalse(slots[sid]["enabled"])
            self.assertEqual(slots[sid]["box"], 0)
        layout = DetectedLayout(
            cells=[
                DetectedCell(
                    box=1,
                    key="f5",
                    template="spells/1단계/힐.png",
                    kr_name="힐",
                    role="heal",
                    bound=True,
                )
            ],
            spell_slots=slots,
        )
        payload = layout.to_profile_dict()
        self.assertEqual(payload["boxes"]["1"]["f5"]["role"], "heal")
        self.assertTrue(payload["boxes"]["1"]["f5"]["bound"])
        cell = DetectedCell(
            box=2, key="f5", kr_name="체력 회복제", kind="ITEM", count=12, label="체력 회복제",
        )
        self.assertEqual(cell.to_dict()["kind"], "ITEM")
        self.assertEqual(cell.to_dict()["count"], 12)

    def test_slot_to_box_key(self) -> None:
        self.assertEqual(slot_to_box_key(0), (1, "f5"))
        self.assertEqual(slot_to_box_key(7), (1, "f12"))
        self.assertEqual(slot_to_box_key(8), (2, "f5"))
        self.assertEqual(slot_to_box_key(15), (2, "f12"))
        self.assertEqual(slot_to_box_key(16), (3, "f5"))
        self.assertEqual(slot_to_box_key(23), (3, "f12"))

    def test_fold_hotbar_name_strips_count(self) -> None:
        self.assertEqual(fold_hotbar_name("체력 회복제 (11)"), "체력 회복제")
        self.assertEqual(fold_hotbar_name("+0 화살 (2,540)"), "화살")
        self.assertEqual(fold_hotbar_name("힐"), "힐")
        self.assertEqual(fold_hotbar_name("初級治癒術(4/0)"), "初級治癒術")
        self.assertEqual(count_from_hotbar_label("아데나 (1,277)"), 1277)
        self.assertIsNone(count_from_hotbar_label("初級治癒術(4/0)"))

    def test_merge_keeps_previous_bound_role(self) -> None:
        detected = _disabled_slots()
        previous = _disabled_slots()
        previous["talking_scroll"] = {
            "box": 1, "key": "f8", "reuse_s": 0.0, "cast": "press", "enabled": True,
        }
        merged = merge_detected_spell_slots(detected, previous)
        self.assertTrue(merged["talking_scroll"]["enabled"])
        self.assertEqual(merged["talking_scroll"]["box"], 1)
        self.assertFalse(merged["heal"]["enabled"])

    def test_find_role_on_hotbar_uses_live_names(self) -> None:
        snap = {
            "slots": [
                {"slot": 5, "name": "初級治癒術"},
                {"slot": 0, "name": "말하는 두루마리"},
            ]
        }
        self.assertEqual(find_role_on_hotbar(snap, "heal"), (1, "f10"))
        self.assertEqual(find_role_on_hotbar(snap, "talking_scroll"), (1, "f5"))
        self.assertTrue(hotbar_has_role(snap, "heal"))
        self.assertIsNone(find_role_on_hotbar(snap, "light"))
        self.assertIsNone(find_role_on_hotbar(snap, "teleport"))

    def test_find_role_on_hotbar_teleport_is_skill_only(self) -> None:
        skill = {"slots": [{"slot": 6, "name": "텔레포트"}]}
        zh = {"slots": [{"slot": 6, "name": "傳送術"}]}
        self.assertEqual(find_role_on_hotbar(skill, "teleport"), (1, "f11"))
        self.assertEqual(find_role_on_hotbar(zh, "teleport"), (1, "f11"))
        self.assertTrue(hotbar_has_role(skill, "teleport"))
        self.assertIsNone(
            find_role_on_hotbar({"slots": [{"name": "매스 텔레포트"}]}, "teleport")
        )
        self.assertIsNone(
            find_role_on_hotbar({"slots": [{"name": "마법서 (텔레포트)"}]}, "teleport")
        )
        self.assertFalse(
            hotbar_has_role({"slots": [{"name": "순간이동 주문서"}]}, "teleport")
        )

    def test_merge_scan_role_wins_same_key(self) -> None:
        detected = _disabled_slots()
        previous = _disabled_slots()
        detected["heal"] = {
            "box": 1, "key": "f10", "reuse_s": 0.0, "cast": "double", "enabled": True,
        }
        previous["light"] = {
            "box": 1, "key": "f10", "reuse_s": 720.0, "cast": "press", "enabled": True,
        }
        previous["heal"] = {
            "box": 1, "key": "f8", "reuse_s": 0.0, "cast": "double", "enabled": True,
        }
        merged = merge_detected_spell_slots(detected, previous)
        self.assertTrue(merged["heal"]["enabled"])
        self.assertEqual(merged["heal"]["key"], "f10")
        self.assertFalse(merged["light"]["enabled"])

    def test_hotbar_refresh_interval_is_five_to_seven_seconds(self) -> None:
        rng = random.Random(0)
        samples = [next_hotbar_refresh_s(rng) for _ in range(80)]
        self.assertTrue(all(5.0 <= value <= 7.0 for value in samples))
        self.assertLess(min(samples), 5.5)
        self.assertGreater(max(samples), 6.5)

    def test_commit_hotbar_scan_updates_layout(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        from manmabot_v1.bot_controller import BotController
        from manmabot_v1.profile import Profile

        seen: list[tuple[dict, dict]] = []
        controller = BotController(on_hotbar=lambda layout, slots: seen.append((layout, slots)))
        profile = Profile()
        world = SimpleNamespace(last_hotbar=None)
        detected = DetectedLayout(
            cells=[
                DetectedCell(
                    box=1, key="f5", kr_name="체력 회복제", kind="ITEM", count=3
                )
            ]
        )
        with patch("app._05_action.spell_box.configure_spell_box"):
            controller._commit_hotbar_scan(
                profile, world, detected, persist=False, log_result=False
            )
        self.assertEqual(
            profile.hotbar_layout["boxes"]["1"]["f5"]["kr_name"],
            "체력 회복제",
        )
        self.assertEqual(profile.hotbar_layout["boxes"]["1"]["f5"]["count"], 3)
        self.assertEqual(len(seen), 1)

    def test_hotbar_arrow_slot_prefers_silver_over_normal(self) -> None:
        layout = DetectedLayout(
            cells=[
                DetectedCell(box=1, key="f9", kr_name="화살", kind="ITEM", count=80),
                DetectedCell(box=2, key="f5", kr_name="은 화살", kind="ITEM", count=200),
            ]
        ).to_profile_dict()
        self.assertEqual(hotbar_arrow_slot(layout, "silver"), (2, "f5"))
        self.assertEqual(hotbar_arrow_slot(layout, "normal"), (1, "f9"))


if __name__ == "__main__":
    unittest.main()
