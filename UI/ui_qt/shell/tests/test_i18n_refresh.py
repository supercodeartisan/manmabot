"""Language refresh keeps typed text and skips ambiguous labels."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QWidget

from ui_qt.i18n_overlay import TxDict, tx
from ui_qt.i18n_refresh import bind_tx_keys, mapped_text, retranslate_tree
from settings.server_list import display_server_name


def test_mapped_text_requires_one_translation():
    old = {"a": "같은말", "b": "같은말", "c": "다른말"}
    new = {"a": "甲", "b": "乙", "c": "丙"}
    assert mapped_text("같은말", old, new) is None
    assert mapped_text("다른말", old, new) == "丙"
    assert mapped_text("없는말", old, new) is None
    assert mapped_text("", old, new) is None


def test_retranslate_skips_line_edits_and_updates_labels():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    label = QLabel("시작", root)
    typed = QLineEdit(root)
    typed.setText("내이름")
    typed.setPlaceholderText("이름")
    old = {"start": "시작", "name": "이름", "mine": "내이름"}
    new = {"start": "开始", "name": "名字", "mine": "我的名字"}
    changed = retranslate_tree(root, old, new)
    assert label.text() == "开始"
    assert typed.text() == "내이름"
    assert typed.placeholderText() == "名字"
    assert changed == 2
    root.deleteLater()
    app.processEvents()


def test_tx_key_wins_when_the_korean_word_is_ambiguous():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    old = {"delete": "삭제", "hp_action_remove": "삭제", "party_ui_delete": "삭제"}
    new = {"delete": "删除", "hp_action_remove": "移除", "party_ui_delete": "删除"}
    with bind_tx_keys():
        button = QPushButton(tx(old, "party_ui_delete", "삭제"), root)
    assert button.property("txKey") == "party_ui_delete"
    assert mapped_text("삭제", old, new) is None
    retranslate_tree(root, old, new)
    assert button.text() == "删除"
    root.deleteLater()
    app.processEvents()


def test_lookup_key_beats_an_ambiguous_word():
    app = QApplication.instance() or QApplication([])
    root = QWidget()
    old = TxDict({"delete": "삭제", "hp_action_remove": "삭제"})
    new = {"delete": "删除", "hp_action_remove": "移除"}
    with bind_tx_keys():
        button = QPushButton(old.get("delete"), root)
    assert button.property("txKey") == "delete"
    retranslate_tree(root, old, new)
    assert button.text() == "删除"
    root.deleteLater()
    app.processEvents()


def test_server_name_follows_the_window_language():
    assert display_server_name("데포로쥬", "zh", "ko") == "太陽神阿波羅"
    assert display_server_name("太陽神阿波羅", "ko", "zh-CN") == "데포로쥬"
    assert display_server_name("데포로쥬", "ko", "ko") == "데포로쥬"
