from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from manmabot_v1.bot_controller import BotController, RunState
from manmabot_v1.probes import GameProbe, Lamp
from manmabot_v1.input_release import restore_desktop_input
from manmabot_v1.recovery import RecoveryBudget, prepare_session
from manmabot_v1.ui.main_window import MainWindow
from manmabot_v1.ui.operator_coordinator import OperatorCoordinator


class RecoveryBudgetTests(unittest.TestCase):
    def test_limits_attempts_inside_window(self) -> None:
        now = [100.0]
        budget = RecoveryBudget(
            max_attempts=2, window_s=60.0, clock=lambda: now[0]
        )

        self.assertTrue(budget.claim())
        self.assertTrue(budget.claim())
        self.assertFalse(budget.claim())
        self.assertEqual(budget.attempts_in_window, 2)

    def test_old_attempts_expire(self) -> None:
        now = [100.0]
        budget = RecoveryBudget(
            max_attempts=1, window_s=60.0, clock=lambda: now[0]
        )

        self.assertTrue(budget.claim())
        now[0] = 161.0
        self.assertTrue(budget.claim())

    def test_manual_reset_clears_budget(self) -> None:
        budget = RecoveryBudget(max_attempts=1)
        self.assertTrue(budget.claim())
        budget.reset()
        self.assertTrue(budget.claim())


class SessionPreparationTests(unittest.TestCase):
    def test_cancelled_start_does_not_login_or_start_memory(self) -> None:
        login = mock.Mock()
        monitor = mock.Mock()
        result = prepare_session(
            account=object(),
            cancel_event=mock.Mock(is_set=mock.Mock(return_value=True)),
            game_ready=lambda: False,
            run_login=login,
            ensure_memory=monitor,
        )
        self.assertTrue(result.cancelled)
        login.assert_not_called()
        monitor.assert_not_called()

    def test_healthy_game_skips_login_and_starts_memory(self) -> None:
        login = mock.Mock()
        monitor = mock.Mock(return_value=SimpleNamespace(ok=True, detail="ready"))
        result = prepare_session(
            account=object(),
            cancel_event=mock.Mock(is_set=mock.Mock(return_value=False)),
            game_ready=lambda: True,
            run_login=login,
            ensure_memory=monitor,
        )
        self.assertTrue(result.ok)
        login.assert_not_called()
        monitor.assert_called_once()

    def test_healthy_game_starts_memory_without_account(self) -> None:
        login = mock.Mock()
        monitor = mock.Mock(return_value=SimpleNamespace(ok=True, detail="ready"))
        result = prepare_session(
            account=None,
            cancel_event=mock.Mock(is_set=mock.Mock(return_value=False)),
            game_ready=lambda: True,
            run_login=login,
            ensure_memory=monitor,
        )
        self.assertTrue(result.ok)
        login.assert_not_called()
        monitor.assert_called_once()

    def test_missing_game_logs_in_before_memory(self) -> None:
        order: list[str] = []
        result = prepare_session(
            account=object(),
            cancel_event=mock.Mock(is_set=mock.Mock(return_value=False)),
            game_ready=lambda: False,
            run_login=lambda _account, _cancel: (
                order.append("login")
                or SimpleNamespace(succeeded=True, state="success", detail="")
            ),
            ensure_memory=lambda: (
                order.append("memory")
                or SimpleNamespace(ok=True, detail="ready")
            ),
        )
        self.assertTrue(result.ok)
        self.assertEqual(order, ["login", "memory"])

    def test_failed_login_never_starts_memory(self) -> None:
        monitor = mock.Mock()
        result = prepare_session(
            account=object(),
            cancel_event=mock.Mock(is_set=mock.Mock(return_value=False)),
            game_ready=lambda: False,
            run_login=lambda _account, _cancel: SimpleNamespace(
                succeeded=False, state="failed", detail="bad login"
            ),
            ensure_memory=monitor,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "bad login")
        monitor.assert_not_called()


class ControllerRecoveryEventTests(unittest.TestCase):
    def test_game_closure_emits_one_event_and_stops(self) -> None:
        controller = BotController()
        controller.state = RunState.RUNNING
        closed = GameProbe(Lamp.RED, "closed")
        with mock.patch(
            "manmabot_v1.bot_controller.probe_game", return_value=closed
        ):
            self.assertEqual(controller.auto_pause_tick(), "game_closed")
            self.assertEqual(controller.state, RunState.STOPPED)
            self.assertIsNone(controller.auto_pause_tick())

    def test_unattended_start_runs_without_game_focus(self) -> None:
        controller = BotController()
        unfocused = GameProbe(
            Lamp.YELLOW, "Game is not in focus", hwnd=1, focused=False
        )
        with mock.patch.object(controller, "start_gates_ok", return_value=None), \
                mock.patch(
                    "manmabot_v1.bot_controller.probe_game",
                    return_value=unfocused,
                ), \
                mock.patch("manmabot_v1.bot_controller.bring_game_to_front"):
            err = controller.start(SimpleNamespace(), unattended=True)
        self.assertIsNone(err)
        self.assertEqual(controller.state, RunState.RUNNING)
        self.assertTrue(controller._unattended)
        controller.stop()

    def test_unattended_run_does_not_pause_on_focus_loss(self) -> None:
        controller = BotController()
        controller.state = RunState.RUNNING
        controller._unattended = True
        controller._pause_gate.set()
        unfocused = GameProbe(
            Lamp.YELLOW, "Game is not in focus", hwnd=1, focused=False
        )
        with mock.patch(
            "manmabot_v1.bot_controller.probe_game", return_value=unfocused
        ):
            self.assertIsNone(controller.auto_pause_tick())
        self.assertEqual(controller.state, RunState.RUNNING)


class MainWindowRecoveryCompletionTests(unittest.TestCase):
    def test_success_starts_a_fresh_worker(self) -> None:
        fake = SimpleNamespace(
            _arming_token=7,
            _closing=False,
            _arming=True,
            _arming_thread=object(),
            controller=SimpleNamespace(
                reason="old",
                start=mock.Mock(return_value=None),
            ),
            profile=object(),
            s=SimpleNamespace(
                autologin_cancelled="cancelled",
                autologin_failed="failed: {detail}",
                cannot_start="cannot",
                start_fail={},
                recovery_completed="recovered",
            ),
            append_log=mock.Mock(),
            _close_memory_monitor=mock.Mock(),
            _refresh_lamps=mock.Mock(),
            _refresh_buttons=mock.Mock(),
        )

        MainWindow._finish_arming(
            fake, 7, {"ok": True, "cancelled": False, "detail": "ready"},
            recovery=True,
        )

        fake.controller.start.assert_called_once_with(fake.profile)
        fake.append_log.assert_called_with("recovered")
        self.assertFalse(fake._arming)


class CoordinatorStartTests(unittest.TestCase):
    def test_start_accepts_unattended(self) -> None:
        self.assertIn("unattended", inspect.signature(OperatorCoordinator.start).parameters)

    def test_finish_forwards_unattended_to_controller(self) -> None:
        fake = SimpleNamespace(
            _arming_token=1,
            _closing=False,
            _arming=True,
            _arming_thread=object(),
            _unattended=True,
            controller=SimpleNamespace(reason="", start=mock.Mock(return_value=None)),
            profile=object(),
            on_change=mock.Mock(),
        )
        OperatorCoordinator._finish(fake, 1, True, "ready")
        fake.controller.start.assert_called_once_with(fake.profile, unattended=True)
        self.assertFalse(fake._arming)

    def test_start_skips_account_when_game_is_already_up(self) -> None:
        fake = SimpleNamespace(
            _arming=False,
            controller=SimpleNamespace(state=RunState.STOPPED),
            profile=SimpleNamespace(selected_account_id="missing"),
            _unattended=False,
            _sync_recovery_budget=mock.Mock(),
            _begin_arming=mock.Mock(),
            _selected_account=mock.Mock(return_value=None),
        )
        game = SimpleNamespace(lamp=Lamp.YELLOW)
        with mock.patch("manmabot_v1.ui.operator_coordinator.probe_game", return_value=game):
            error = OperatorCoordinator.start(fake, unattended=True)
        self.assertIsNone(error)
        fake._begin_arming.assert_called_once_with(None, recovery=False)

    def test_start_still_requires_account_when_game_is_down(self) -> None:
        fake = SimpleNamespace(
            _arming=False,
            controller=SimpleNamespace(state=RunState.STOPPED),
            profile=SimpleNamespace(selected_account_id=None),
            _begin_arming=mock.Mock(),
            _selected_account=mock.Mock(return_value=None),
        )
        game = SimpleNamespace(lamp=Lamp.RED)
        with mock.patch("manmabot_v1.ui.operator_coordinator.probe_game", return_value=game):
            error = OperatorCoordinator.start(fake)
        self.assertEqual(error, "account_required")
        fake._begin_arming.assert_not_called()


class DesktopInputReleaseTests(unittest.TestCase):
    def test_restore_desktop_input_is_safe_without_game(self) -> None:
        restore_desktop_input(hwnd=0)


if __name__ == "__main__":
    unittest.main()
