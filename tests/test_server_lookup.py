from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTOLOGIN_BOT = ROOT / "autologin" / "bot"
if str(AUTOLOGIN_BOT) not in sys.path:
    sys.path.insert(0, str(AUTOLOGIN_BOT))

from gameflow import GameFlow, lookup_server_in_table


ZH_CN = AUTOLOGIN_BOT / "data" / "servers_zh-CN.json"
KO = AUTOLOGIN_BOT / "data" / "servers_ko.json"


class ServerLookupTests(unittest.TestCase):
    def test_zh_cn_page2_name_is_not_page1(self) -> None:
        table = GameFlow._read_server_json(str(ZH_CN))
        self.assertEqual(
            lookup_server_in_table(table, "獨眼巨人庫克羅普斯"),
            ("2", "6", "left"),
        )
        self.assertEqual(
            lookup_server_in_table(table, "飛馬珀伽索斯"),
            ("2", "1", "left"),
        )
        self.assertEqual(
            lookup_server_in_table(table, "太陽神阿波羅"),
            ("1", "1", "left"),
        )

    def test_korean_name_stays_on_its_own_page(self) -> None:
        table = GameFlow._read_server_json(str(KO))
        self.assertEqual(
            lookup_server_in_table(table, "린델"),
            ("2", "4", "left"),
        )
        self.assertIsNone(lookup_server_in_table(table, "飛馬珀伽索斯"))

    def test_lookup_uses_other_locale_table_when_lang_is_ko(self) -> None:
        flow = GameFlow.__new__(GameFlow)
        flow.lang = "ko"
        flow._server_table = GameFlow._read_server_json(str(KO))
        hit = flow._lookup_server("獨眼巨人庫克羅普斯")
        self.assertEqual(hit, ("2", "6", "left"))
        self.assertEqual(
            lookup_server_in_table(flow._server_table, "獨眼巨人庫克羅普斯"),
            hit,
        )


if __name__ == "__main__":
    unittest.main()
