"""Unit tests for hunt resume snapshot apply (no LC)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from session.hunt_resume import apply_hunt_resume  # noqa: E402


class _Cursor:
    def __init__(self):
        self.entries = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.index = 0
        self.elapsed_s = 0.0
        self.running_since = 1.0


class HuntResumeTests(unittest.TestCase):
    def test_apply_routine_and_farm(self):
        cursor = _Cursor()
        board = SimpleNamespace(
            scratch={"routine_cursor": cursor},
            farm_area_index=0,
            farm_tour_pos=0,
        )
        ok = apply_hunt_resume(
            board,
            {
                "routine_index": 2,
                "elapsed_s": 123.5,
                "farm_area_index": 1,
            },
        )
        self.assertTrue(ok)
        self.assertEqual(cursor.index, 2)
        self.assertEqual(cursor.elapsed_s, 123.5)
        self.assertEqual(cursor.running_since, 0.0)
        self.assertEqual(board.farm_area_index, 1)

    def test_apply_clamps_index(self):
        cursor = _Cursor()
        board = SimpleNamespace(scratch={"routine_cursor": cursor})
        apply_hunt_resume(board, {"routine_index": 99, "elapsed_s": 1})
        self.assertEqual(cursor.index, 2)


if __name__ == "__main__":
    unittest.main()
