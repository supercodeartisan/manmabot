"""PySide6 application entry for the schedule / operator console."""

from __future__ import annotations

import sys


def run_schedule_app() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZF")
        except Exception:
            pass

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from i18n.strings import ui_language
    from session.paths import ensure_userdata
    from settings.map_previews import brand_icon_path
    from settings.profile import load_profile
    from ui_qt.shell.schedule_shell import ScheduleShell
    from ui_qt.theme import apply_classic_qt_theme

    ensure_userdata()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("ZF")
    app.setOrganizationName("ZF")
    logo = brand_icon_path()
    if logo is not None:
        app.setWindowIcon(QIcon(str(logo)))
    profile = load_profile()
    language = ui_language(profile.language)
    from ui_qt.theme import tokens
    from ui_qt.theme.apply import font_roles_for_window

    body, section, _title = font_roles_for_window(
        tokens.DEFAULT_WIDTH, tokens.DEFAULT_HEIGHT
    )
    apply_classic_qt_theme(app, language, font_size=body, section_size=section)
    window = ScheduleShell(profile)
    window.show()
    return int(app.exec())
