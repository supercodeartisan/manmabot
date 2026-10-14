"""Bridge ``OperatorCoordinator`` onto the Qt UI thread via signals."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from i18n.strings import START_FAIL
from settings.profile import Profile
from ui.operator_coordinator import OperatorCoordinator


class QtBridge(QObject):
    """Owns the coordinator; never runs bot work on the GUI thread itself."""

    stateChanged = Signal()
    logLine = Signal(str)
    hotbarUpdated = Signal(object, object)
    userStopped = Signal()
    # Arming / hotkey / handover threads must not touch QTimer from foreign threads.
    _dispatchCall = Signal(object)

    def __init__(self, profile: Profile, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.profile = profile
        self._dispatchCall.connect(
            self._run_dispatched, Qt.ConnectionType.QueuedConnection
        )
        self.coordinator = OperatorCoordinator(
            profile,
            dispatch=self.dispatch,
            on_change=lambda: self.stateChanged.emit(),
            on_log=lambda message: self.logLine.emit(str(message)),
            on_hotbar=lambda layout, slots: self.hotbarUpdated.emit(layout, slots),
        )
        self.coordinator.on_user_stop = self._on_user_stop

    def _on_user_stop(self) -> None:
        self.userStopped.emit()

    @Slot(object)
    def _run_dispatched(self, fn: object) -> None:
        if callable(fn):
            fn()

    def dispatch(self, fn: Callable[[], None]) -> None:
        """Queue ``fn`` onto the Qt main thread (Tk ``after(0, fn)`` equivalent).

        Safe from worker threads. ``QTimer.singleShot`` from a non-Qt thread
        is dropped, which left Start stuck on “Preparing session…”.
        """
        self._dispatchCall.emit(fn)

    def start(self, unattended: bool = False) -> str | None:
        return self.coordinator.start(unattended=unattended)

    def stop(self) -> None:
        self.coordinator.stop()

    def resume(self) -> None:
        self.coordinator.resume()

    def halt_for_switch(self) -> None:
        self.coordinator.halt_for_switch()

    def poll(self) -> None:
        self.coordinator.poll()

    def probes(self) -> Any:
        return self.coordinator.probes()

    def rebind_hotkeys(self) -> str | None:
        return self.coordinator.rebind_hotkeys()

    def invalidate_map_probe(self) -> None:
        self.coordinator.invalidate_map_probe()

    def start_error_text(self, code: str, strings: dict[str, str] | None = None) -> str:
        key = str(code or "").strip()
        if not key:
            return ""
        table = strings or {}
        return str(table.get(key) or START_FAIL.get(key) or key)

    @property
    def arming(self) -> bool:
        return bool(self.coordinator.arming)

    @property
    def controller(self):
        return self.coordinator.controller

    def close(self) -> None:
        self.coordinator.close()
