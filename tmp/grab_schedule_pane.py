from PySide6.QtWidgets import QApplication

from settings.schedule import ScheduleStore, ScheduleTask
from ui.schedule_i18n import tr
from ui_qt.i18n_overlay import merge_ui_strings
from ui_qt.shell.schedule_list import ScheduleListPane
from ui_qt.shell.schedule_shell import ScheduleShell
from ui_qt.theme.apply import apply_classic_qt_theme

app = QApplication([])
apply_classic_qt_theme(app, "ko", font_size=11)
strings = merge_ui_strings("ko", tr("ko"))
pane = ScheduleListPane(
    store=ScheduleStore(),
    tasks=[ScheduleTask(name="테스트", enabled=True)],
    strings=strings,
    language="ko",
)
pane.resize(314, 760)
pane.show()
app.processEvents()
pane.grab().save(r"d:\ManmabotV1_final_final_final\tmp\schedule_solo.png")
shell = ScheduleShell.__new__(ScheduleShell)
shell._settings_mode = "party"
shell.schedule_list = pane
shell._apply_schedule_pane_mode()
app.processEvents()
pane.grab().save(r"d:\ManmabotV1_final_final_final\tmp\schedule_party.png")
print("saved", pane.isEnabled())
