"""Schedule console shell — list + editor + classic schedule drive."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from i18n.strings import START_FAIL, ui_language
from session.bot_controller import RunState
from session.game_shutdown import close_game_client
from session.paths import LOG_DIR, ensure_userdata, is_portable
from session.probes import Lamp, probe_game
from settings.accounts import AccountStore
from settings.farm_schedule import normalize_routine, routine_is_break_only
from settings.profile import Profile, load_profile, save_profile
from settings.schedule import ScheduleStore, ScheduleTask
from settings.schedule_clock import ScheduleSession
from ui.schedule_i18n import LANGUAGES, LANGUAGE_NAMES, tr
from ui_qt.i18n_overlay import merge_ui_strings
from ui_qt.dialogs.accounts_dialog import AccountsDialog
from ui_qt.dialogs.driver_setup_dialog import show_driver_setup
from ui_qt.dialogs.map_editor_dialog import open_map_editor as launch_map_editor
from ui_qt.dialogs.setup_wizard import SetupWizard
from ui_qt.editors.task_editor import TaskEditor
from ui_qt.facade.qt_bridge import QtBridge
from ui_qt.shell.schedule_list import ScheduleListPane
from ui_qt.theme import tokens
from ui_qt.theme.apply import (
    apply_classic_qt_theme,
    font_px_for_window,
    font_roles_for_window,
    mark_accent,
)
from ui_qt.theme.run_glyphs import run_glyph

_SPLASH_CLASS = "ZFStartupSplash"
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SW_SHOW = 5


def _startup_splash_visible() -> bool:
    """True while this process still has the topmost loading popup."""
    import ctypes
    import os
    from ctypes import wintypes

    from win32_prototypes import bind_user32

    user32 = ctypes.windll.user32
    bind_user32(user32)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    found = False
    pid = os.getpid()

    def _visit(hwnd, _lparam):
        nonlocal found
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) != pid or not user32.IsWindowVisible(hwnd):
            return True
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, name, 64)
        if name.value == _SPLASH_CLASS:
            found = True
            return False
        return True

    callback = enum_proc(_visit)
    _startup_splash_visible._callback = callback  # type: ignore[attr-defined]
    user32.EnumWindows(callback, 0)
    return found


def _force_window_top(hwnd: int, *, topmost: bool) -> None:
    """Put hwnd above other windows. Topmost beats the loading popup."""
    if not hwnd:
        return
    import ctypes
    from ctypes import wintypes

    from win32_prototypes import bind_user32

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    bind_user32(user32)
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    target = wintypes.HWND(hwnd)
    insert = wintypes.HWND(_HWND_TOPMOST if topmost else _HWND_NOTOPMOST)
    flags = _SWP_NOMOVE | _SWP_NOSIZE
    flags |= _SWP_SHOWWINDOW if topmost else _SWP_NOACTIVATE
    fg = user32.GetForegroundWindow()
    fg_thread = 0
    attached = False
    if fg:
        owner = wintypes.DWORD()
        fg_thread = int(user32.GetWindowThreadProcessId(fg, ctypes.byref(owner)) or 0)
    this_thread = int(kernel32.GetCurrentThreadId() or 0)
    try:
        user32.AllowSetForegroundWindow(wintypes.DWORD(0xFFFFFFFF))
    except Exception:
        pass
    if fg_thread and fg_thread != this_thread:
        attached = bool(user32.AttachThreadInput(fg_thread, this_thread, True))
    try:
        if topmost:
            user32.ShowWindow(target, _SW_SHOW)
        user32.SetWindowPos(target, insert, 0, 0, 0, 0, flags)
        user32.SetForegroundWindow(target)
        user32.BringWindowToTop(target)
    finally:
        if attached:
            user32.AttachThreadInput(fg_thread, this_thread, False)


class ScheduleShell(QMainWindow):
    """PySide schedule root with list + full editor tabs."""

    def __init__(self, profile: Profile | None = None) -> None:
        super().__init__()
        ensure_userdata()
        self.profile = profile or load_profile()
        self.language = ui_language(self.profile.language)
        self.profile.language = self.language
        self.t = merge_ui_strings(self.language, tr(self.language))
        self.store = ScheduleStore()
        self.tasks = self.store.load()
        self._session = ScheduleSession()
        self._editing_id: str | None = None
        self._creating_new = False
        self._closing = False
        self._login_not_before = 0.0
        self._log_lines: list[str] = []
        self._shown_start_reason = ""
        self._debug_win = None
        self._party_win = None
        self._op_sig: tuple | None = None
        self._probe_sig: tuple | None = None
        self._probe_at = 0.0
        self._main_splitter: QSplitter | None = None
        self._launch_front_armed = False
        self._launch_front_tries = 0
        # Classic default window (1187×806) → 8pt body, not 11.
        self._ui_scale_font_px = 8
        self._scale_timer = QTimer(self)
        self._scale_timer.setSingleShot(True)
        self._scale_timer.setInterval(80)
        self._scale_timer.timeout.connect(self._apply_window_scale)

        self.bridge = QtBridge(self.profile, parent=self)
        # Queued so arming-thread emits never touch widgets directly.
        self.bridge.stateChanged.connect(
            lambda: self._refresh_operator(force=True),
            Qt.ConnectionType.QueuedConnection,
        )
        self.bridge.logLine.connect(
            self._append_log, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.userStopped.connect(
            self._on_user_stop, Qt.ConnectionType.QueuedConnection
        )
        self.bridge.rebind_hotkeys()

        self.setWindowTitle(self.t["console_title"])
        from PySide6.QtGui import QIcon
        from settings.map_previews import brand_icon_path

        logo = brand_icon_path()
        if logo is not None:
            self.setWindowIcon(QIcon(str(logo)))
        self.setMinimumSize(tokens.MIN_WIDTH, tokens.MIN_HEIGHT)
        self.resize(tokens.DEFAULT_WIDTH, tokens.DEFAULT_HEIGHT)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            body, section, _title = font_roles_for_window(
                tokens.DEFAULT_WIDTH, tokens.DEFAULT_HEIGHT
            )
            apply_classic_qt_theme(
                app, self.language, self, font_size=body, section_size=section
            )
        self._build()
        self.schedule_list.set_live_clock_provider(self._live_routine_clock)
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint, bool(self.profile.always_on_top)
        )
        self._refresh_operator(force=True)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()
        QTimer.singleShot(400, self._warm_memory_monitor)

        if self.tasks:
            self.schedule_list.refresh(select=0)
            self._edit_selected()
        else:
            self._begin_new()
        QTimer.singleShot(0, self._lock_pane_split)

    def _warm_memory_monitor(self) -> None:
        """Attach player memory as soon as the console is up (not only on Start)."""
        if self._closing:
            return

        def runner() -> None:
            from session.monitor_launch import warm_memory_at_startup

            warm_memory_at_startup(
                log=lambda message: self.bridge.logLine.emit(str(message)),
                timeout_s=8.0,
                wait_snapshot=True,
            )
            self.bridge.dispatch(lambda: self._refresh_operator(force=True))

        threading.Thread(
            target=runner, name="memory-warm", daemon=True
        ).start()

    def _build(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(4)
        layout.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._main_splitter = splitter
        self.schedule_list = ScheduleListPane(
            store=self.store,
            tasks=self.tasks,
            strings=self.t,
            language=self.language,
        )
        self.schedule_list.taskSelected.connect(self._on_task_selected)
        self.schedule_list.newRequested.connect(self._begin_new)
        self.schedule_list.editRequested.connect(self._edit_selected)
        splitter.addWidget(self.schedule_list)

        self.editor = TaskEditor(
            profile=self.profile,
            bridge=self.bridge,
            strings=self.t,
            language=self.language,
            on_log=self._append_log,
            on_commit=self._commit_editor,
            on_update=self._commit_update,
            on_add=self._commit_add,
            on_apply=self._apply_editor_task,
            on_open_map_editor=self.open_map_editor,
            on_run_setup=self.run_setup,
            on_start_driver=self.start_driver,
            on_profile_reloaded=self._on_profile_reloaded,
            get_log_lines=lambda: list(self._log_lines),
            clear_shell_logs=self._clear_shell_logs,
        )
        self.editor.accountChanged.connect(self._sync_list_account)
        if self.editor.move_tab is not None:
            self.editor.move_tab.set_farm_clock_provider(self._live_farm_clock)
        self.editor.set_timing_reader(self.schedule_list.read_timing_into)
        self._bind_schedule_dirty_signals()
        self.schedule_list.account_combo.currentIndexChanged.connect(
            self._sync_editor_account
        )
        splitter.addWidget(self.editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Classic: sash locked to randomize row; placeholder until first lock.
        splitter.setSizes([360, max(400, tokens.DEFAULT_WIDTH - 360)])
        splitter.setHandleWidth(0)
        splitter.handle(1).setEnabled(False)
        layout.addWidget(splitter, stretch=1)

        status = QStatusBar()
        self.setStatusBar(status)
        self.footer = status
        status.showMessage(self.t.get("console_title", "ZF"))

    def _lock_pane_split(self) -> None:
        """Pin the schedule pane to the randomize control (classic sash lock)."""
        splitter = self._main_splitter
        if splitter is None:
            return
        total = int(splitter.width())
        if total < tokens.MIN_WIDTH - 48:
            return
        self.schedule_list._align_account_to_time()
        target = int(self.schedule_list.preferred_pane_width())
        editor_floor = 280
        left = target if target + editor_floor <= total else max(120, total - editor_floor)
        right = max(1, total - left)
        splitter.setSizes([left, right])

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._lock_pane_split)
        QTimer.singleShot(0, self._apply_window_scale)
        if not self._launch_front_armed:
            self._launch_front_armed = True
            QTimer.singleShot(0, self._reveal_main_window)

    def _reveal_main_window(self) -> None:
        """Drop the loading window once this console has painted."""
        if self._closing:
            return
        self._lock_pane_split()
        self._apply_window_scale()
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        from session.startup_splash import close_startup_splash

        close_startup_splash()
        QTimer.singleShot(40, self._raise_launch_window)

    def _raise_launch_window(self) -> None:
        """Bring the console forward after the loading window is gone."""
        if self._closing:
            return
        self._launch_front_tries += 1
        if _startup_splash_visible() and self._launch_front_tries < 25:
            from session.startup_splash import close_startup_splash

            close_startup_splash()
            QTimer.singleShot(40, self._raise_launch_window)
            return
        self.raise_()
        self.activateWindow()
        hwnd = int(self.winId() or 0)
        if hwnd:
            _force_window_top(hwnd, topmost=True)
            if not bool(self.profile.always_on_top):
                _force_window_top(hwnd, topmost=False)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._scale_timer.start()

    def _apply_window_scale(self) -> None:
        """Refresh body font with classic-style live UI scale."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        size = font_px_for_window(self.width(), self.height())
        if size == self._ui_scale_font_px:
            self._lock_pane_split()
            return
        self._ui_scale_font_px = size
        body, section, _title = font_roles_for_window(self.width(), self.height())
        apply_classic_qt_theme(
            app, self.language, self, font_size=body, section_size=section
        )
        self._lock_pane_split()

    def _status_chip(self, strip: QFrame) -> QLabel:
        chip = QLabel("")
        chip.setObjectName("statusChip")
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setMinimumWidth(72)
        strip.layout().addWidget(chip)
        return chip

    def _paint_status_chip(self, label: QLabel, text: str, mode: str) -> None:
        bg, fg = tokens.STRIP.get(mode, tokens.STRIP["off"])
        label.setText(text)
        label.setStyleSheet(
            f"QLabel#statusChip {{ background: {bg}; color: {fg}; "
            f"padding: 3px 10px; border: none; }}"
        )

    def _build_header(self) -> QWidget:
        # Classic order: strip · … · accounts · language · topmost · debug · power · stop
        bar = QFrame()
        bar.setObjectName("chrome")
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(4)

        strip = QFrame()
        strip.setObjectName("statusStrip")
        strip_row = QHBoxLayout(strip)
        strip_row.setContentsMargins(1, 1, 1, 1)
        strip_row.setSpacing(1)
        self.state_chip = self._status_chip(strip)
        self.game_lamp = self._status_chip(strip)
        self.memory_lamp = self._status_chip(strip)
        self.map_lamp = self._status_chip(strip)
        row.addWidget(strip)
        row.addStretch(1)

        accounts_btn = QPushButton(self.t.get("manage_accounts", "Accounts"))
        accounts_btn.clicked.connect(self._open_accounts)
        row.addWidget(accounts_btn)

        self.language_combo = QComboBox()
        self.language_combo.setMinimumWidth(100)
        for label, code in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        index = self.language_combo.findData(self.language)
        if index < 0 and self.language in LANGUAGE_NAMES:
            index = self.language_combo.findText(LANGUAGE_NAMES[self.language])
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        row.addWidget(self.language_combo)

        self.topmost = QCheckBox(self.t.get("always_on_top", "Always on top"))
        self.topmost.setChecked(bool(self.profile.always_on_top))
        self.topmost.toggled.connect(self._on_topmost)
        row.addWidget(self.topmost)

        self.humanize_move = QCheckBox(self.t.get("humanize_move", "Humanize mouse move"))
        self.humanize_move.setToolTip(
            self.t.get(
                "humanize_move_tip",
                "Curved cursor path. Each move finishes within 0.02 s.",
            )
        )
        self.humanize_move.setChecked(bool(getattr(self.profile, "humanize_move", True)))
        self.humanize_move.toggled.connect(self._on_humanize_move)
        row.addWidget(self.humanize_move)

        if not is_portable():
            debug_btn = QPushButton(self.t.get("debug", "Debug"))
            debug_btn.clicked.connect(self.open_debug)
            row.addWidget(debug_btn)

        # Party etview — BitBlt + markers/ATK like etview.exe + party status.
        party_btn = QPushButton(self.t.get("party_monitor", "Party"))
        party_btn.setToolTip(
            self.t.get(
                "party_monitor_tip",
                "Party etview: game capture + entity markers, leader ATK target, socket messages.",
            )
        )
        party_btn.clicked.connect(self.open_party_monitor)
        row.addWidget(party_btn)

        self.power_btn = QPushButton(self.t.get("start", "Start"))
        self.power_btn.setIcon(run_glyph("start"))
        self.power_btn.clicked.connect(self._toggle_run)
        mark_accent(self.power_btn)
        self.stop_btn = QPushButton(self.t.get("stop", "Stop"))
        self.stop_btn.setIcon(run_glyph("stop"))
        self.stop_btn.clicked.connect(self._on_stop)
        row.addWidget(self.power_btn)
        row.addWidget(self.stop_btn)
        return bar

    def _open_accounts(self) -> None:
        def _changed() -> None:
            self.schedule_list.refresh_accounts()
            self.editor.refresh_accounts(
                select_id=self.editor.account_combo.currentData()
            )
            self.schedule_list.refresh(
                select=self.schedule_list.selected_index(),
                reload_accounts=False,
            )

        dialog = AccountsDialog(
            self.t,
            self,
            profile=self.profile,
            language=self.language,
            on_changed=_changed,
        )
        dialog.exec()
        _changed()

    def _bind_schedule_dirty_signals(self) -> None:
        pane = self.schedule_list
        touch = self.editor.schedule_content_touched
        pane.mode_window.toggled.connect(touch)
        pane.mode_duration.toggled.connect(touch)
        pane.start_time.textChanged.connect(touch)
        pane.end_time.textChanged.connect(touch)
        pane.duration_spin.valueChanged.connect(touch)
        pane.repeat_daily.toggled.connect(touch)
        for box in pane.weekday_checks:
            box.toggled.connect(touch)
        pane.account_combo.currentIndexChanged.connect(touch)

    def _sync_list_account(self, account_id) -> None:
        combo = self.schedule_list.account_combo
        combo.blockSignals(True)
        index = combo.findData(account_id)
        combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)

    def _sync_editor_account(self) -> None:
        self.editor.set_account_id(self.schedule_list.account_combo.currentData())

    def open_debug(self) -> None:
        if is_portable():
            return
        win = self._debug_win
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return
        from ui_qt.debug.debug_window import DebugWindow

        self._debug_win = DebugWindow(
            self,
            controller=self.bridge.controller,
            get_logs=lambda: list(self._log_lines),
            t=self.t,
            get_arming=lambda: self.bridge.arming,
            on_close=lambda: setattr(self, "_debug_win", None),
        )
        self._debug_win.show()

    def _close_debug(self) -> None:
        win = self._debug_win
        self._debug_win = None
        if win is not None:
            win.close()

    def open_party_monitor(self) -> None:
        win = self._party_win
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return
        from ui_qt.debug.party_monitor_window import PartyMonitorWindow

        self._party_win = PartyMonitorWindow(
            self,
            controller=self.bridge.controller,
            t=self.t,
            on_close=lambda: setattr(self, "_party_win", None),
        )
        self._party_win.show()

    def _close_party_monitor(self) -> None:
        win = self._party_win
        self._party_win = None
        if win is not None:
            win.close()

    def open_map_editor(
        self,
        map_id: str,
        *,
        dungeon: bool = False,
        area_kind: str = "farm",
        on_closed=None,
    ) -> None:
        try:
            existing = getattr(self, "_map_editor_dialog", None)
            if existing is not None:
                try:
                    same = (
                        existing.isVisible()
                        and getattr(existing.editor, "map_id", None) == map_id
                        and bool(getattr(existing.editor, "_dungeon", False)) == bool(dungeon)
                        and str(getattr(existing.editor, "_area_kind", "farm"))
                        == ("safe" if str(area_kind) == "safe" and not dungeon else "farm")
                    )
                    if same:
                        existing.raise_()
                        existing.activateWindow()
                        return
                    existing.close()
                except RuntimeError:
                    self._map_editor_dialog = None

            def _closed() -> None:
                self._map_editor_dialog = None
                if on_closed is not None:
                    try:
                        on_closed()
                    except Exception:
                        pass

            self._map_editor_dialog = launch_map_editor(
                self,
                map_id=map_id,
                dungeon=dungeon,
                area_kind=area_kind,
                language=self.language,
                can_edit=lambda: self.bridge.controller.state == RunState.STOPPED,
                on_changed=lambda: self.editor.reload_move_areas(),
                on_closed=_closed,
            )
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("title", self.t.get("console_title", "ZF")), str(exc))
            if on_closed is not None:
                try:
                    on_closed()
                except Exception:
                    pass

    def apply_profile(self, profile: Profile) -> None:
        language = ui_language(profile.language)
        self.profile.__dict__.update(profile.__dict__)
        save_profile(self.profile)
        self.bridge.profile = self.profile
        self.bridge.coordinator.profile = self.profile
        if language != self.language:
            self.profile.language = language
            save_profile(self.profile)
            QMessageBox.information(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                self.t.get(
                    "restart_language",
                    "Language saved. Restart the Qt shell to refresh all labels.",
                ),
            )
        else:
            if self.editor.move_tab is not None:
                self.editor.move_tab.reload_from_profile()
            self._refresh_operator(force=True)

    def run_setup(self) -> None:
        if self.bridge.controller.state != RunState.STOPPED:
            QMessageBox.warning(
                self,
                self.t.get("setup", "Setup"),
                self.t.get("stop_to_apply", "Stop the bot before applying."),
            )
            return
        try:
            SetupWizard(
                self,
                profile=self.profile,
                on_apply=self.apply_profile,
                on_log=self._append_log,
            ).exec()
        except Exception as exc:
            QMessageBox.warning(self, self.t.get("setup", "Setup"), str(exc))

    def start_driver(self) -> None:
        from session.monitor_launch import try_start_driver

        ok, detail = try_start_driver(log=self._append_log)
        box = QMessageBox.information if ok else QMessageBox.warning
        box(self, self.t.get("start_driver", "Start driver"), str(detail))

    def show_drivers(self) -> None:
        show_driver_setup(
            self,
            language=self.language,
            require_ready=False,
            on_log=self._append_log,
        )

    def _on_language_changed(self) -> None:
        code = str(self.language_combo.currentData() or self.language)
        if code == self.language:
            return
        self._rebuild_for_language(code)

    def _rebuild_for_language(self, language: str) -> None:
        """Classic parity: destroy chrome and rebuild labels without restarting the process."""
        editing_id = self._editing_id
        creating = self._creating_new
        selected = self.schedule_list.selected_index()
        self.profile.language = language
        save_profile(self.profile)
        if self._debug_win is not None:
            try:
                self._debug_win.close()
            except Exception:
                pass
            self._debug_win = None
        if self._party_win is not None:
            try:
                self._party_win.close()
            except Exception:
                pass
            self._party_win = None
        self._poll_timer.stop()
        editor = getattr(self, "editor", None)
        bar = getattr(editor, "income_bar", None) if editor is not None else None
        if bar is not None:
            bar.shutdown()
        self.language = language
        self.t = merge_ui_strings(language, tr(language))
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            body, section, _title = font_roles_for_window(self.width(), self.height())
            self._ui_scale_font_px = body
            apply_classic_qt_theme(
                app, language, self, font_size=body, section_size=section
            )
        self.setWindowTitle(self.t["console_title"])
        old = self.takeCentralWidget()
        if old is not None:
            old.deleteLater()
        self._build()
        self.schedule_list.set_live_clock_provider(self._live_routine_clock)
        self.language_combo.blockSignals(True)
        for i in range(self.language_combo.count()):
            if self.language_combo.itemData(i) == language:
                self.language_combo.setCurrentIndex(i)
                break
        self.language_combo.blockSignals(False)
        if creating:
            self._begin_new()
        elif editing_id:
            for i, task in enumerate(self.tasks):
                if task.id == editing_id:
                    self.schedule_list.refresh(select=i)
                    self._edit_selected()
                    break
            else:
                self.schedule_list.refresh(
                    select=selected if selected is not None else None
                )
        else:
            self.schedule_list.refresh(
                select=selected if selected is not None else (0 if self.tasks else None)
            )
        self._poll_timer.start()
        self._refresh_operator(force=True)
        QTimer.singleShot(0, self._lock_pane_split)

    def _on_topmost(self, checked: bool) -> None:
        self.profile.always_on_top = bool(checked)
        save_profile(self.profile)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        self.show()

    def _on_humanize_move(self, checked: bool) -> None:
        self.profile.humanize_move = bool(checked)
        save_profile(self.profile)
        self.bridge.coordinator.profile = self.profile
        self.bridge.coordinator.controller.set_humanize_move(bool(checked))

    def _on_user_stop(self) -> None:
        self._disarm_schedule()

    def _disarm_schedule(self) -> None:
        self._session.disarm()
        self.bridge.coordinator.hold_recovery = False

    def _on_task_selected(self, task) -> None:
        if self._editing_id:
            return
        if task is None:
            return
        self._creating_new = False
        self.schedule_list.show_timing_from(task)
        self.editor.load_task(task, editing=False)

    def _blank_task(self) -> ScheduleTask:
        """A new schedule starts empty. It does not copy the live profile."""
        task = ScheduleTask(name="", account_id=None, server="")
        task.settings = {"move": {"routine": []}}
        return task

    def _begin_new(self) -> None:
        self._editing_id = None
        self._creating_new = True
        task = self._blank_task()
        self.schedule_list.clear_selection()
        self.schedule_list.show_timing_from(task)
        self.editor.load_task(task, editing=False, inherit_profile_routine=False)
        self.editor.set_commit_mode(False)
        self.footer.showMessage(self.t.get("task_details", "New schedule"))

    def _enter_edit(self, task) -> None:
        """Open ``task`` so the next save updates this schedule."""
        self._editing_id = task.id
        self._creating_new = False
        self.schedule_list.show_timing_from(task)
        self.editor.load_task(task, editing=True)

    def _edit_selected(self) -> None:
        task = self.schedule_list.selected_task()
        if task is None:
            return
        self._enter_edit(task)
        self.footer.showMessage(self.t.get("edit_schedule", "Edit"))

    def _publish_paused_schedule(self, task) -> None:
        """While paused, push the saved schedule into the running worker."""
        from session.runtime_settings import publish_paused_task

        if self.bridge.arming:
            return
        try:
            status = publish_paused_task(self.bridge.controller, self.profile, task)
        except Exception as exc:
            self._append_log(f"Paused settings reload failed: {exc}")
            return
        if status == "not_paused":
            return
        self.bridge.profile = self.profile
        self.bridge.coordinator.profile = self.profile
        try:
            self.bridge.invalidate_map_probe()
        except Exception:
            pass
        key = (
            "paused_settings_applied_keep_identity"
            if status == "applied_keep_identity"
            else "paused_settings_applied"
        )
        text = self.t.get(key, key)
        self.footer.showMessage(text)
        self._append_log(text)
        self._refresh_operator(force=True)

    def _routine_vm(self):
        move = getattr(self.editor, "move_tab", None)
        return getattr(move, "vm", None) if move is not None else None

    def _gap_lines(self, gaps: list[dict]) -> list[str]:
        lines: list[str] = []
        for gap in gaps:
            status = self.t.get(str(gap.get("setting_key") or ""), "")
            label = str(gap.get("label") or gap.get("map_id") or "")
            lines.append(f"{gap.get('index', '')}. {label} — {status}")
        return lines

    def _warn_incomplete_routine(
        self,
        gaps: list[dict],
        *,
        action: str,
        sections: list[tuple[str, list[dict]]] | None = None,
    ) -> None:
        intro = self.t.get(f"routine_setup_block_{action}", "")
        if sections:
            chunks = [
                heading + "\n" + "\n".join(self._gap_lines(rows))
                for heading, rows in sections
                if rows
            ]
            detail = "\n\n".join(chunks)
        else:
            detail = "\n".join(self._gap_lines(gaps))
        text = intro if not detail else f"{intro}\n\n{detail}"
        QMessageBox.warning(
            self,
            self.t.get(
                "routine_setup_block_title",
                self.t.get("title", self.t.get("console_title", "ZF")),
            ),
            text,
        )

    def _editor_routine_gaps(self) -> list[dict]:
        vm = self._routine_vm()
        if vm is None:
            return []
        return list(vm.incomplete_setups())

    def _block_editor_routine(self, action: str) -> bool:
        """True when save/create must stop because a routine setup is still needed."""
        gaps = self._editor_routine_gaps()
        if not gaps:
            return False
        self._warn_incomplete_routine(gaps, action=action)
        return True

    def _blocked_enabled_schedules(self) -> list[tuple[ScheduleTask, list[dict]]]:
        vm = self._routine_vm()
        if vm is None:
            return []
        blocked: list[tuple[ScheduleTask, list[dict]]] = []
        for task in self.tasks:
            if not task.enabled:
                continue
            routine = ((task.settings or {}).get("move") or {}).get("routine")
            gaps = list(vm.incomplete_setups(routine))
            if gaps:
                blocked.append((task, gaps))
        return blocked

    def _commit_update(self) -> bool:
        """Overwrite the schedule under edit and stay on that edit."""
        if not self._editing_id:
            return False
        if self._block_editor_routine("save"):
            return False
        collected = self.editor.collect_task()
        self.schedule_list.read_timing_into(collected)
        if (
            QMessageBox.question(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                self.t.get("confirm_update_schedule", "Save changes?"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        collected.id = self._editing_id
        index = next(
            (i for i, item in enumerate(self.tasks) if item.id == self._editing_id),
            None,
        )
        if index is None:
            self.tasks.append(collected)
            index = len(self.tasks) - 1
        else:
            self.tasks[index] = collected
        self.schedule_list.persist(select=index)
        self._enter_edit(collected)
        self.footer.showMessage(self.t.get("saved", "Saved"))
        self._publish_paused_schedule(collected)
        return True

    def _commit_add(self) -> bool:
        """Store the form as a new list row, then open that row for edit."""
        if self._block_editor_routine("create"):
            return False
        collected = self.editor.collect_task()
        self.schedule_list.read_timing_into(collected)
        if not collected.account_id:
            QMessageBox.warning(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                self.t.get("account_required", "Account required."),
            )
            return False
        prompt = (
            self.t.get("confirm_save_as_new", self.t.get("confirm_create_schedule", "Add?"))
            if self._editing_id
            else self.t.get("confirm_create_schedule", "Add?")
        )
        if (
            QMessageBox.question(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                prompt,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return False
        collected.id = uuid.uuid4().hex
        self.tasks.append(collected)
        index = len(self.tasks) - 1
        # Claim the new id before the list selects it, so that selection
        # does not reload the form as a blank new schedule.
        self._editing_id = collected.id
        self._creating_new = False
        self.schedule_list.persist(select=index)
        self._enter_edit(collected)
        self.footer.showMessage(self.t.get("schedule_added", "Added"))
        return True

    def _commit_editor(self) -> bool:
        if self._editing_id:
            return self._commit_update()
        return self._commit_add()

    def _apply_editor_task(self) -> bool:
        if self.bridge.arming or self.bridge.controller.state != RunState.STOPPED:
            QMessageBox.warning(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                self.t.get("stop_to_apply", "Stop the bot before applying."),
            )
            return False
        task = self.editor.collect_task()
        self.schedule_list.read_timing_into(task)
        count = len(self.editor.bag.apply_task(task))
        try:
            valid_account = (
                task.account_id
                if task.account_id and AccountStore().get(task.account_id) is not None
                else None
            )
        except Exception:
            valid_account = None
        if valid_account and self.profile.selected_account_id != valid_account:
            self.profile.selected_account_id = valid_account
            save_profile(self.profile)
            count += 1
        if self.editor.move_tab is not None:
            self.editor.move_tab.apply_to_profile()
        self.bridge.invalidate_map_probe()
        self.bridge.profile = self.profile
        self.bridge.coordinator.profile = self.profile
        self.footer.showMessage(self.t.get("applied", "Applied ({count})").format(count=count))
        self._refresh_operator(force=True)
        return True

    def _overlay_party_from_editor(self) -> None:
        """Push live Party-tab settings onto profile (schedule Start can wipe it)."""
        try:
            from settings.schedule import ScheduleTask
            from settings.task_runtime import apply_runtime_settings

            party = dict(self.editor.bag.section("party") or {})
            apply_runtime_settings(
                ScheduleTask(settings={"party": party}),
                self.profile,
            )
            save_profile(self.profile)
            self.bridge.profile = self.profile
            self.bridge.coordinator.profile = self.profile
            role = str(getattr(self.profile, "party_role", "member") or "member")
            port = int(getattr(self.profile, "party_ws_port", 8765) or 8765)
            member = bool(getattr(self.profile, "party_member_enabled", False))
            host = str(getattr(self.profile, "party_leader_host", "") or "")
            self._append_log(
                f"Party role={role} member={'ON' if member else 'OFF'} "
                f"port={port} leader={host}"
            )
        except Exception as exc:
            self._append_log(f"Party settings overlay failed: {exc}")

    def _game_is_up(self) -> bool:
        try:
            return probe_game().lamp != Lamp.RED
        except Exception:
            return False

    def _task_by_id(self, task_id: str | None) -> ScheduleTask | None:
        if not task_id:
            return None
        return next((task for task in self.tasks if task.id == task_id), None)

    def _account_label(self, task: ScheduleTask | None) -> str:
        empty = self.t.get("value_empty", "—")
        if task is None:
            return empty
        try:
            account = AccountStore().get(task.account_id) if task.account_id else None
        except Exception:
            account = None
        if account is None:
            return empty
        return account.display_name or account.username or empty

    def _randomize_minutes(self) -> int:
        try:
            if not bool(self.schedule_list.randomize.isChecked()):
                return 0
            return max(0, min(120, int(self.schedule_list.random_minutes.value())))
        except Exception:
            return 0

    def apply_task(self, task: ScheduleTask, *, interactive: bool = True) -> bool:
        """Apply a schedule task onto the live profile (classic Start path)."""
        if self.bridge.arming or self.bridge.controller.state != RunState.STOPPED:
            if interactive:
                QMessageBox.warning(
                    self,
                    self.t.get("title", self.t.get("console_title", "ZF")),
                    self.t.get("stop_to_apply", "Stop the bot before applying."),
                )
            return False
        count = len(self.editor.bag.apply_task(task))
        try:
            valid_account = (
                task.account_id
                if task.account_id and AccountStore().get(task.account_id) is not None
                else None
            )
        except Exception:
            valid_account = None
        if valid_account and self.profile.selected_account_id != valid_account:
            self.profile.selected_account_id = valid_account
            save_profile(self.profile)
            count += 1
        if self.editor.move_tab is not None:
            try:
                self.editor.move_tab.apply_to_profile()
            except Exception:
                pass
        self.bridge.invalidate_map_probe()
        self.bridge.profile = self.profile
        self.bridge.coordinator.profile = self.profile
        self.footer.showMessage(
            self.t.get("applied", "Applied ({count})").format(count=count)
        )
        self._refresh_operator(force=True)
        return True

    def _sync_routine_from_editor(self) -> None:
        """Copy the open editor routine into ``profile`` when non-empty."""
        try:
            settings = self.editor.collect_settings()
        except Exception:
            return
        move = settings.get("move") or {}
        routine = normalize_routine(move.get("routine"))
        if not routine:
            return
        self.profile.routine = list(routine)
        primary = next(
            (row for row in routine if str(row.get("kind") or "") == "battle"),
            routine[0],
        )
        pack = str(primary.get("map_id") or "").strip()
        if pack:
            self.profile.active_map = pack
            style = str(move.get("map_style") or getattr(self.profile, "map_style", "normal"))
            dungeon = style.strip().lower() == "dungeon"
            self.profile.map_style = "dungeon" if dungeon else "normal"
            if dungeon:
                self.profile.selected_farms = []
                self.profile.farm_stays_s = {}
            else:
                names = [
                    str(n) for n in (primary.get("selected_farms") or []) if str(n).strip()
                ]
                stays = dict(primary.get("farm_stays_s") or {})
                self.profile.selected_farms = names
                self.profile.farm_stays_s = stays

    def _start_error_text(self, error: str) -> str:
        key = str(error or "").strip()
        if not key:
            return ""
        return self.t.get(key) or START_FAIL.get(key) or key

    def _report_start_error(self, error: str) -> None:
        text = self._start_error_text(error)
        self._append_log(text)
        self.footer.showMessage(text)

    def _routine_summary_lines(self, routine: list) -> str:
        rows = normalize_routine(routine)
        if not rows:
            return self.t.get("routine_summary_empty", "(no routine)")
        labels = getattr(self.schedule_list, "_map_labels", {}) or {}
        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            map_id = str(row.get("map_id") or "")
            name = labels.get(map_id) or map_id
            kind = (
                self.t.get("routine_break", "Break")
                if row.get("kind") == "break"
                else self.t.get("routine_battle", "Battle")
            )
            minutes = int(row.get("duration_minutes") or 0)
            lines.append(
                f"{index}. {name} — {kind} — {minutes} "
                f"{self.t.get('minutes', 'min')}"
            )
        return "\n".join(lines)

    def _start_summary_text(self) -> str:
        enabled = [task for task in self.tasks if task.enabled]
        blocks: list[str] = []
        if not enabled:
            blocks.append(self.t.get("start_confirm_empty", "No enabled schedule."))
            try:
                routine = self.editor.collect_settings().get("move", {}).get("routine")
            except Exception:
                routine = list(getattr(self.profile, "routine", None) or [])
            blocks.append(self._routine_summary_lines(routine or []))
            return "\n".join(blocks).strip()
        for task in enabled:
            character = self.t.get(task.character, task.character)
            when = f"{task.start_time}–{task.end_time}" if task.time_mode != "duration" else (
                f"{task.start_time} +{task.duration_minutes}m"
            )
            lines = [
                f"{self.t.get('accounts', 'Account')}: {self._account_label(task)}",
                f"{self.t.get('schedules', 'Schedule')}: {task.name}",
                f"{self.t.get('time', 'Time')}: {when}",
                f"{self.t.get('character', 'Class')}: {character}",
                self.t.get("routine_of_schedule", "Routine:"),
                self._routine_summary_lines(
                    normalize_routine((task.settings.get("move") or {}).get("routine"))
                ),
            ]
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks).strip()

    def _confirm_start(self) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t.get("start", "Start"))
        dialog.resize(560, 420)
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(self.t.get("start_confirm_intro", "Start with these schedules?"))
        )
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(self._start_summary_text())
        layout.addWidget(body, stretch=1)
        layout.addWidget(QLabel(self.t.get("start_confirm_now", "Start now?")))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText(
            self.t.get("start_confirm_yes", "Yes")
        )
        buttons.button(QDialogButtonBox.StandardButton.No).setText(
            self.t.get("start_confirm_no", "No")
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _start(self) -> None:
        """Classic Start: arm schedule clock, then unattended session prepare."""
        self._append_log(self.t.get("start", "Start"))
        if self._editing_id and self.editor.has_unsaved_changes():
            try:
                if not self._commit_editor():
                    self._refresh_operator(force=True)
                    return
            except OSError as exc:
                self._append_log(str(exc))
                QMessageBox.warning(self, self.t.get("title", self.t.get("console_title", "ZF")), str(exc))
                self._refresh_operator(force=True)
                return

        game_up = self._game_is_up()
        has_schedule = any(task.enabled for task in self.tasks)
        if not has_schedule:
            QMessageBox.warning(
                self,
                self.t.get("title", self.t.get("console_title", "ZF")),
                self.t.get("no_enabled_schedule", "Turn on at least one schedule before Start."),
            )
            return

        blocked = self._blocked_enabled_schedules()
        if blocked:
            sections = [
                (
                    (task.name or "").strip() or self._account_label(task),
                    gaps,
                )
                for task, gaps in blocked
            ]
            self._warn_incomplete_routine([], action="start", sections=sections)
            self._refresh_operator(force=True)
            return

        will_start = (
            self.bridge.controller.state == RunState.STOPPED
            and not self.bridge.arming
            and has_schedule
        )
        if will_start and not self._confirm_start():
            self._append_log(self.t.get("start_confirm_no", "Start cancelled"))
            self._refresh_operator(force=True)
            return

        if (
            has_schedule
            and self.bridge.controller.state == RunState.STOPPED
            and not self.bridge.arming
        ):
            self._session.arm()
            self._login_not_before = 0.0
            self._drive_schedule()
            if (
                game_up
                and self.bridge.controller.state == RunState.STOPPED
                and not self.bridge.arming
            ):
                task = (
                    self._task_by_id(self._session.active_id)
                    if self._session.active_id
                    else None
                )
                if task is None:
                    task = next((row for row in self.tasks if row.enabled), None)
                if task is not None:
                    if not self.apply_task(task, interactive=False):
                        self._refresh_operator(force=True)
                        return
                else:
                    self._sync_routine_from_editor()
                    save_profile(self.profile)
                # Schedule task may omit/clear party; keep the live Hunt checkbox.
                self._overlay_party_from_editor()
                if routine_is_break_only(getattr(self.profile, "routine", None)):
                    QMessageBox.warning(
                        self,
                        self.t.get("title", self.t.get("console_title", "ZF")),
                        self.t.get("start_break_only", "Routine is break-only."),
                    )
                    return
                try:
                    from settings.trial_store import mark_schedule_run

                    mark_schedule_run(str(task.id) if task is not None else "")
                except Exception:
                    pass
                error = self.bridge.start(unattended=True)
                if error:
                    self._report_start_error(error)
            else:
                self._append_log(
                    self.t.get("schedule_waiting", "Waiting for schedule")
                )
            self._refresh_operator(force=True)
            return

        self._append_log(
            "Start skipped "
            f"(game_up={game_up}, state={self.bridge.controller.state}, "
            f"arming={self.bridge.arming})"
        )
        self._refresh_operator(force=True)

    def _drive_schedule(self) -> None:
        if not self._session.armed or self._closing or self._session.switching:
            return
        for _ in range(max(2, len(self.tasks) + 2)):
            decision = self._session.tick(
                datetime.now(),
                self.tasks,
                randomize_minutes=self._randomize_minutes(),
            )
            if decision.kind == "notify":
                upcoming = self._session.next_task_id(self.tasks)
                self._show_switch_notice(decision.switch_at or datetime.now(), upcoming)
                self._show_schedule_status()
                return
            if decision.kind == "begin":
                if self._login_scheduled(decision.task_id) == "retry":
                    continue
                self._show_schedule_status()
                return
            if decision.kind == "handover":
                self._begin_handover(decision.task_id)
                return
            if (
                self._session.active_id
                and self.bridge.controller.state == RunState.STOPPED
                and not self.bridge.arming
            ):
                self._login_scheduled(self._session.active_id)
            self._show_schedule_status()
            return

    def _login_scheduled(self, task_id: str | None) -> str:
        if not self._session.armed or not task_id:
            return "done"
        if self.bridge.arming or self.bridge.controller.state != RunState.STOPPED:
            return "done"
        now = time.monotonic()
        if now < self._login_not_before:
            return "done"
        task = self._task_by_id(task_id)
        if task is None:
            self._session.skip_current()
            return "retry"
        try:
            account = AccountStore().get(task.account_id) if task.account_id else None
        except Exception:
            account = None
        game_up = self._game_is_up()
        if account is None and not game_up:
            self._append_log(
                self.t.get("schedule_missing_account", "Schedule account missing.")
            )
            self._session.skip_current()
            return "retry"
        if account is None:
            self._append_log(
                self.t.get("start_without_login", "Starting without login.")
            )
        self._login_not_before = now + 15.0
        if not self.apply_task(task, interactive=False):
            return "done"
        # Schedule disk settings used to drop ``party``; keep Hunt checkbox live.
        self._overlay_party_from_editor()
        error = self.bridge.start(unattended=True)
        if error:
            self._report_start_error(error)
        return "done"

    def _begin_handover(self, task_id: str | None) -> None:
        self._session.switching = True
        self.bridge.halt_for_switch()

        def work() -> None:
            try:
                self.bridge.controller.wait_stopped(timeout=5.0)
            except Exception:
                pass
            try:
                close_game_client()
            except Exception as exc:
                detail = str(exc)
                self.bridge.dispatch(lambda: self._append_log(detail))
            self.bridge.dispatch(lambda: self._finish_handover(task_id))

        threading.Thread(target=work, name="schedule-switch", daemon=True).start()
    def _finish_handover(self, task_id: str | None) -> None:
        self._session.switching = False
        self.bridge.coordinator.hold_recovery = False
        if self._closing or not self._session.armed:
            return
        if task_id:
            if self._login_scheduled(task_id) == "retry":
                self._drive_schedule()
        else:
            self._append_log(self.t.get("schedule_waiting", "Waiting for schedule"))
        self._show_schedule_status()
        self._refresh_operator(force=True)

    def _show_schedule_status(self) -> None:
        if not self._session.armed:
            return
        if self._session.active_id and self._session.switch_at:
            task = self._task_by_id(self._session.active_id)
            text = self.t.get(
                "schedule_active", "{account} until {time}"
            ).format(
                account=self._account_label(task),
                time=self._session.switch_at.strftime("%H:%M:%S"),
            )
        else:
            text = self.t.get("schedule_waiting", "Waiting for schedule")
        self.footer.showMessage(text)

    def _show_switch_notice(self, decision_time: datetime, task_id: str | None) -> None:
        when = decision_time.strftime("%H:%M:%S")
        nxt = self._task_by_id(task_id)
        if nxt is None:
            text = self.t.get("switch_notice_end", "Schedule ends at {time}").format(
                time=when
            )
        else:
            text = self.t.get(
                "switch_notice", "Switch to {account} at {time}"
            ).format(account=self._account_label(nxt), time=when)
        self._append_log(text)

    def _toggle_run(self) -> None:
        try:
            state = self.bridge.controller.state
            if state == RunState.RUNNING:
                self.bridge.controller.pause_user()
                self._refresh_operator(force=True)
            elif state == RunState.PAUSED:
                self.bridge.resume()
                self._refresh_operator(force=True)
            else:
                self._start()
        except Exception as exc:
            detail = f"Start/Pause failed: {exc}"
            self._append_log(detail)
            QMessageBox.critical(self, self.t.get("title", "ManmaBot"), detail)

    def _on_stop(self) -> None:
        self.bridge.stop()
        self._refresh_operator(force=True)

    def _live_routine_clock(self) -> dict | None:
        """Stay clock for the schedule list when that routine is the one running."""
        controller = self.bridge.controller
        if controller.state not in (RunState.RUNNING, RunState.PAUSED):
            return None
        clock = controller.routine_clock()
        if not clock:
            return None
        task = self.schedule_list.selected_task()
        if task is None:
            return None
        active_id = self._session.active_id
        if active_id and task.id == active_id:
            return clock
        painted = self.schedule_list.routine_entry_ids()
        clock_ids = [str(item) for item in clock.get("ids") or []]
        if painted and painted == clock_ids:
            if not self._session.armed or not active_id:
                return clock
        return None

    def _live_farm_clock(self) -> dict | None:
        """Stay clock for the open hunt-area list."""
        controller = self.bridge.controller
        if controller.state not in (RunState.RUNNING, RunState.PAUSED):
            return None
        return controller.farm_clock()

    def _on_poll(self) -> None:
        if self._closing:
            return
        self._drive_schedule()
        state = self.bridge.controller.state
        arming = self.bridge.arming
        active = (
            arming
            or self._session.armed
            or state in (RunState.RUNNING, RunState.PAUSED)
        )
        if active:
            self.bridge.poll()
            self._poll_timer.setInterval(250)
        else:
            self._poll_timer.setInterval(1000)
        self._refresh_operator(force=False)
        self.schedule_list.paint_routine_timers()
        if self.editor.move_tab is not None:
            self.editor.move_tab.paint_farm_timers()

    def _refresh_operator(self, force: bool = False) -> None:
        state = self.bridge.controller.state
        arming = self.bridge.arming
        reason = str(getattr(self.bridge.controller, "reason", "") or "").strip()
        op_sig = (state, arming, reason)
        op_changed = force or op_sig != self._op_sig
        if op_changed:
            self._op_sig = op_sig
            # Fatal stops: drop the armed schedule so Stop disables and the
            # header matches a dead worker (crash used to leave Stop lit).
            if state == RunState.STOPPED and reason in (
                "world_nav_cycle_failed",
                "worker_crashed",
            ):
                if self._session.armed or self._session.switching:
                    self._disarm_schedule()
            scheduled = bool(self._session.armed or self._session.switching)
            if state == RunState.RUNNING:
                label, glyph, enabled = self.t.get("pause", "Pause"), "pause", True
            elif state == RunState.PAUSED:
                label, glyph, enabled = self.t.get("resume", "Resume"), "resume", True
            else:
                label, glyph = self.t.get("start", "Start"), "start"
                enabled = not arming
            self.power_btn.setText(label)
            self.power_btn.setIcon(run_glyph(glyph))
            self.power_btn.setEnabled(enabled)
            self.stop_btn.setEnabled(
                state != RunState.STOPPED or arming or scheduled
            )

            state_text = self.t.get(state.value, state.value)
            if arming:
                state_text = self.t.get("preparing", "Preparing…") or "arming…"
                mode = "hold"
            elif state == RunState.STOPPED and reason and reason != "cancelled":
                pretty = self.bridge.start_error_text(reason, self.t)
                state_text = pretty or state_text
                mode = "off"
                if pretty and pretty != self._shown_start_reason:
                    self._shown_start_reason = pretty
                    self._append_log(pretty)
            else:
                if state != RunState.STOPPED:
                    self._shown_start_reason = ""
                if state == RunState.RUNNING:
                    mode = "on"
                elif state == RunState.PAUSED:
                    mode = "hold"
                else:
                    mode = "off"
            self._paint_status_chip(self.state_chip, state_text, mode)

        now = time.monotonic()
        due = force or op_changed or (now - self._probe_at) >= 1.0
        if not due and self._probe_sig is not None:
            return
        self._probe_at = now
        try:
            game, memory, map_probe = self.bridge.probes()
        except Exception:
            return
        probe_sig = (
            getattr(game, "lamp", None),
            getattr(game, "detail", ""),
            getattr(memory, "lamp", None),
            getattr(memory, "detail", ""),
            getattr(map_probe, "lamp", None),
            getattr(map_probe, "detail", ""),
            state,
        )
        if not force and probe_sig == self._probe_sig:
            return
        self._probe_sig = probe_sig
        self._paint_probe_chips(game, memory, map_probe)
        self.editor.show_status(game, memory, map_probe)

    def _paint_probe_chips(self, game, memory, map_probe) -> None:
        # Keep chip copy aligned with classic schedule_ui helpers without importing Tk.
        game_text = (
            self.t.get("chip_game_on", "Game")
            if game.lamp == Lamp.GREEN
            else self.t.get("chip_game_off", "Game")
        )
        mem_on = memory.lamp in (Lamp.GREEN, Lamp.YELLOW)
        if memory.lamp == Lamp.GREEN:
            mem_text = self.t.get("chip_mem_on", "Memory")
        elif memory.lamp == Lamp.YELLOW:
            mem_text = self.t.get("chip_mem_wait", "No position")
        else:
            mem_text = self.t.get("chip_mem_off", "Memory")
        if map_probe.lamp == Lamp.GREEN:
            title = str(getattr(map_probe, "map_name", "") or "").strip() or self.t.get(
                "chip_map_on", "Map"
            )
            if getattr(map_probe, "dungeon", False):
                count = int(getattr(map_probe, "patrol_count", 0) or 0)
            else:
                count = len(getattr(map_probe, "farm_names", None) or [])
            map_text = self.t.get("chip_place", "{title} · {n}").format(
                title=title, n=count
            )
        else:
            map_text = self.t.get("chip_map_off", "Map")
        self._paint_status_chip(
            self.game_lamp, game_text, "on" if game.lamp == Lamp.GREEN else "off"
        )
        self._paint_status_chip(
            self.memory_lamp, mem_text, "on" if mem_on else "off"
        )
        self._paint_status_chip(
            self.map_lamp, map_text, "on" if map_probe.lamp == Lamp.GREEN else "off"
        )

    def _append_log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"{stamp}  {message}"
        self._log_lines.append(line)
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with (LOG_DIR / "v1.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            pass
        self.editor.append_log_row(stamp, str(message))
        self.footer.showMessage(str(message)[:160])

    def _clear_shell_logs(self) -> None:
        self._log_lines = []

    def _on_profile_reloaded(self) -> None:
        self.bridge.profile = self.profile
        self.bridge.coordinator.profile = self.profile
        self.bridge.rebind_hotkeys()
        other = getattr(self.editor, "other_tab", None)
        if other is not None and hasattr(other, "refresh_hotbar_view"):
            other.refresh_hotbar_view()
            other._load_hotkey_fields()
        self._refresh_operator(force=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        bar = getattr(self.editor, "income_bar", None)
        if bar is not None:
            bar.shutdown()
        self._poll_timer.stop()
        self.schedule_list._clock.stop()
        self._close_debug()
        self._close_party_monitor()
        self.bridge.close()
        super().closeEvent(event)
