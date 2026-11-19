"""Unit tests for UIMessage classification (no driver / no LC)."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from session.uimsg_probe import (  # noqa: E402
    UiMsgKind,
    classify_uimsg_text,
    extract_uimsg_text,
)


class ClassifyTests(unittest.TestCase):
    def test_chinese_disconnect(self):
        self.assertEqual(
            classify_uimsg_text("與伺服器連線中斷。"),
            UiMsgKind.DISCONNECT,
        )

    def test_simplified_disconnect(self):
        self.assertEqual(
            classify_uimsg_text("与服务器连接中断。"),
            UiMsgKind.DISCONNECT,
        )

    def test_korean_disconnect(self):
        self.assertEqual(
            classify_uimsg_text("서버와의 연결이 끊어졌습니다."),
            UiMsgKind.DISCONNECT,
        )

    def test_korean_policy(self):
        self.assertEqual(
            classify_uimsg_text(
                "운영자의 요청 또는 정책에 의해 게임 접속이 종료되었습니다."
            ),
            UiMsgKind.POLICY_BLOCK,
        )

    def test_chinese_policy(self):
        self.assertEqual(
            classify_uimsg_text("因營運政策，遊戲連線已結束。"),
            UiMsgKind.POLICY_BLOCK,
        )

    def test_empty(self):
        self.assertEqual(classify_uimsg_text(""), UiMsgKind.NONE)

    def test_extract_lcapi_line(self):
        blob = (
            "# registry=x cms=0x1\n"
            "0\tUIMSG\tsize=27\tcap=31\tf1=0x1\tf2=0x100010101\t與伺服器連線中斷。\n"
            "# done total_ioctl=8\n"
        )
        text = extract_uimsg_text(blob)
        self.assertIn("連線中斷", text)
        self.assertEqual(classify_uimsg_text(text), UiMsgKind.DISCONNECT)


if __name__ == "__main__":
    unittest.main()
