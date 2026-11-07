from PySide6.QtWidgets import QApplication

from settings.profile import Profile
from ui_qt.editors.party_tab import PartyTab
from ui_qt.editors.party_workspace import PartyWorkspace
from ui_qt.theme.apply import apply_classic_qt_theme
from ui_qt.viewmodels.settings_bag import SettingsBag

app = QApplication([])
apply_classic_qt_theme(app, "ko", font_size=11)
bag = SettingsBag(Profile())
bag.set("party", "role", "leader")
bag.set("party", "enabled", True)
tab = PartyTab(bag=bag, strings={}, language="ko", profile=None)
ws = PartyWorkspace(tab)
ws.resize(980, 680)
ws._on_role_chosen("leader")
ws._leader_buttons[2].click()
ws.show()
app.processEvents()
ws.grab().save(r"d:\ManmabotV1_final_final_final\tmp\stage1_leader_ops.png")
ws.set_locked(False, "")
ws.show_picker()
ws._on_role_chosen("member")
ws._member_buttons[2].click()
app.processEvents()
ws.grab().save(r"d:\ManmabotV1_final_final_final\tmp\stage1_member_assist.png")
print("saved")
