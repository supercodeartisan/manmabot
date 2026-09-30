"""Toolkit-independent ownership of bot lifecycle, recovery, and hotkeys."""
from __future__ import annotations

import threading
import time
from typing import Callable

from manmabot_v1.accounts import AccountStore
from manmabot_v1.autologin_service import AutoLoginRequest, AutoLoginService
from manmabot_v1.bot_controller import BotController, RunState
from manmabot_v1.hotkeys import HotkeyManager
from manmabot_v1.monitor_launch import ensure_monitor_connected, is_monitor_process_running, stop_monitor_process
from manmabot_v1.probes import Lamp, probe_game, probe_map, probe_memory
from manmabot_v1.profile import Profile
from manmabot_v1.recovery import RecoveryBudget, prepare_session


class OperatorCoordinator:
    """Single owner for resources previously owned by ``MainWindow``."""

    def __init__(
        self,
        profile: Profile,
        *,
        dispatch: Callable[[Callable[[], None]], None],
        on_change: Callable[[], None] = lambda: None,
        on_log: Callable[[str], None] = lambda _message: None,
        on_hotbar: Callable[[dict, dict], None] = lambda _layout, _slots: None,
    ) -> None:
        self.profile = profile
        self.dispatch = dispatch
        self.on_change = on_change
        self.on_log = on_log
        self._closing = False
        self._arming = False
        self._arming_token = 0
        self.hold_recovery = False
        self.on_user_stop = lambda: None
        self._cancel = threading.Event()
        self._arming_thread: threading.Thread | None = None
        self._map_probe = None
        self._map_probe_at = 0.0
        self._unattended = False
        self._budget = RecoveryBudget(max_attempts=3, window_s=600.0)
        self._sync_recovery_budget()
        self.controller = BotController(
            on_log=on_log, on_state=lambda _state, _reason: self.dispatch(on_change),
            on_hotbar=on_hotbar,
        )
        self.hotkeys = HotkeyManager()
        self.rebind_hotkeys()

    def _sync_recovery_budget(self) -> None:
        try:
            attempts = max(1, min(20, int(getattr(self.profile, "max_retries", 3))))
        except (TypeError, ValueError):
            attempts = 3
        self._budget.max_attempts = attempts

    @property
    def arming(self) -> bool:
        return self._arming

    def rebind_hotkeys(self) -> str | None:
        return self.hotkeys.bind(
            self.profile.hotkeys,
            on_pause_resume=lambda: self.dispatch(self._hotkey_pause_resume),
            on_stop=lambda: self.dispatch(self._hotkey_stop),
        )

    def _hotkey_pause_resume(self) -> None:
        """Pause or resume, then refresh the header status on this same turn."""
        self.controller.toggle_pause_hotkey()
        self.on_change()

    def _hotkey_stop(self) -> None:
        """Stop, then refresh the header status on this same turn."""
        self.stop()
        self.on_change()

    def invalidate_map_probe(self) -> None:
        self._map_probe = None
        self._map_probe_at = 0.0

    def probes(self):
        now = time.monotonic()
        if self._map_probe is None or now - self._map_probe_at >= 2.0:
            self._map_probe = probe_map(
                self.profile.selected_farms,
                map_id=self.profile.active_map,
                language=self.profile.language,
                map_style=getattr(self.profile, "map_style", None),
            )
            self._map_probe_at = now
        return (
            probe_game(),
            probe_memory(),
            self._map_probe,
        )

    def _selected_account(self):
        try:
            return AccountStore().get(self.profile.selected_account_id)
        except Exception:
            return None

    def start(self, unattended: bool = False) -> str | None:
        if self._arming or self.controller.state != RunState.STOPPED:
            return None
        account = self._selected_account()
        game_up = probe_game().lamp != Lamp.RED
        if account is None and not game_up:
            return "account_required"
        self._unattended = bool(unattended)
        self._sync_recovery_budget()
        self._begin_arming(account, recovery=False)
        return None

    def _begin_arming(self, account, *, recovery: bool) -> None:
        if self._closing or self._arming:
            return
        if recovery and not self._budget.claim():
            self.controller.reason = "Recovery attempt limit reached."
            self.on_log(self.controller.reason)
            self.on_change()
            return
        self._arming = True
        self._arming_token += 1
        token = self._arming_token
        self._cancel = threading.Event()
        self.on_change()

        def runner() -> None:
            deadline = time.monotonic() + 12.0
            while not self.controller.worker_stopped() and not self._cancel.is_set():
                if time.monotonic() >= deadline:
                    self.dispatch(lambda: self._finish(token, False, "Previous worker did not stop."))
                    return
                time.sleep(0.1)

            def login(selected, cancel):
                request = AutoLoginRequest(
                    user_id=selected.username, password=selected.password,
                    server=selected.server, character_number=selected.character_number,
                    language=selected.locale, purple_launcher_path=selected.purple_launcher_path,
                    game_path=selected.game_path, click_mode=selected.click_mode,
                )
                return AutoLoginService().run(request, cancel_event=cancel, on_status=self.on_log)

            prepared = prepare_session(
                account=account, cancel_event=self._cancel,
                game_ready=lambda: probe_game().lamp != Lamp.RED,
                run_login=login,
                ensure_memory=lambda: ensure_monitor_connected(
                    elevate=True, start_driver=True, timeout_s=20.0, log=self.on_log
                ),
            )
            try:
                from manmabot_v1.input_release import restore_desktop_input

                restore_desktop_input()
            except Exception:
                pass
            self.dispatch(lambda: self._finish(token, prepared.ok, prepared.detail))

        self._arming_thread = threading.Thread(target=runner, name="unified-console-arming", daemon=True)
        self._arming_thread.start()

    def _finish(self, token: int, ok: bool, detail: str) -> None:
        if token != self._arming_token or self._closing:
            return
        self._arming = False
        self._arming_thread = None
        if ok:
            error = self.controller.start(self.profile, unattended=self._unattended)
            if error:
                self.controller.reason = error
        else:
            self.controller.reason = detail or "Could not prepare game session."
        self.on_change()

    def resume(self) -> None:
        self.controller.resume()
        self.on_change()

    def stop(self) -> None:
        """User stop. Also disarms the schedule via ``on_user_stop``."""
        self.on_user_stop()
        self.hold_recovery = False
        self._halt()

    def halt_for_switch(self) -> None:
        """Stop the bot without disarming the schedule or logging back in."""
        self.hold_recovery = True
        self._halt()

    def _halt(self) -> None:
        if self._arming:
            self._cancel.set()
            self._arming = False
            self._arming_token += 1
        armed = self.controller.state in (RunState.RUNNING, RunState.PAUSED)
        self.controller.stop()
        if armed and is_monitor_process_running():
            stop_monitor_process(log=self.on_log)
        self.on_change()

    def poll(self) -> None:
        if self.hold_recovery:
            return
        if self.controller.state in (RunState.RUNNING, RunState.PAUSED):
            if self.controller.auto_pause_tick() == "game_closed":
                if not bool(getattr(self.profile, "resume_after_relogin", True)):
                    self.controller.reason = "Game closed; resume after relogin is off."
                    self.on_change()
                    return
                account = self._selected_account()
                if account is not None:
                    self._sync_recovery_budget()
                    self._begin_arming(account, recovery=True)

    def close(self) -> None:
        self._closing = True
        self._arming_token += 1
        self._cancel.set()
        self.controller.stop()
        if is_monitor_process_running():
            stop_monitor_process(log=self.on_log)
        try:
            self.controller.wait_stopped(timeout=6.0)
        except Exception:
            pass
        thread = self._arming_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=6.0)
        self.hotkeys.clear()
