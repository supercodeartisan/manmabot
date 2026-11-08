"""Individual magic class follows the account and is not editable."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[4]
for _path in (_ROOT / "UI", _ROOT / "Engine"):
    text = str(_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtWidgets import QApplication

from settings.profile import Profile
from ui_qt.editors.magic_tab import MagicTab
from ui_qt.viewmodels.settings_bag import SettingsBag


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_account_class_has_no_picker() -> None:
    _app()
    bag = SettingsBag(Profile())
    bag.set("magic", "class", "elf")
    tab = MagicTab(bag=bag, strings={"elf": "Elf", "mage": "Mage"}, language="en")
    tab.set_account_character("mage")
    assert bag.get_str("magic", "class") == "mage"
    tab.tabs.setCurrentIndex(1)
    assert not hasattr(tab, "class_combo")
    assert tab._ui_class == "mage"
    tab.set_account_character("elf")
    assert tab._ui_class == "elf"
    assert bag.get_str("magic", "class") == "elf"


if __name__ == "__main__":
    test_account_class_has_no_picker()
    print("magic class lock ok")
