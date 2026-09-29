from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from manmabot_v1.server_list import server_names_list


class ServerListTests(unittest.TestCase):
    def test_korean_list_contains_known_servers(self) -> None:
        names = server_names_list("ko")
        self.assertIn("린델", names)
        self.assertIn("오렌", names)
        self.assertGreater(len(names), 10)

    def test_chinese_list_is_loaded(self) -> None:
        names = server_names_list("zh-CN")
        self.assertTrue(names)
        self.assertNotEqual(names, server_names_list("ko"))


if __name__ == "__main__":
    unittest.main()
