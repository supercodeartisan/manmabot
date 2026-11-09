"""Exp and Adena cards share one sampler and reset independently."""

from __future__ import annotations

import inspect
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

from ui_qt.editors.task_editor import TaskEditor
from ui_qt.shell import live_income_bar as income
from ui_qt.shell.live_income_bar import LiveIncomeBar, _Meter
from ui_qt.shell.schedule_shell import ScheduleShell


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _hour(delta: float, elapsed: float) -> float:
    return delta / (elapsed / 3600.0)


def test_idle_sample_shows_holdings_without_rates() -> None:
    view = _Meter().push(
        running=False, buying=False, adena=9286, level=9, exp_percent=54.3, now=0
    )
    assert view["level"] == 9
    assert view["exp"] == 54.3
    assert view["adena"] == 9286
    assert view["exp_rate"] is None
    assert view["adena_rate"] is None
    assert view["adena_gained"] is None
    assert view["elapsed"] is None


def test_running_clock_starts_at_the_first_sample_and_waits_15_seconds() -> None:
    meter = _Meter()
    first = meter.push(
        running=True, buying=False, adena=1000, level=10, exp_percent=10.0, now=0
    )
    assert first["adena_gained"] == 0
    assert first["elapsed"] == 0
    assert first["exp_rate"] is None
    assert first["adena_rate"] is None
    early = meter.push(
        running=True, buying=False, adena=1100, level=10, exp_percent=12.0, now=14.9
    )
    assert early["exp_rate"] is None
    assert early["adena_rate"] is None
    later = meter.push(
        running=True, buying=False, adena=1100, level=10, exp_percent=12.0, now=15
    )
    assert later["exp_rate"] == _hour(2.0, 15)
    assert later["adena_rate"] == _hour(100, 15)
    assert later["elapsed"] == 15


def test_pause_keeps_totals_and_skips_manual_play() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=1000, level=10, exp_percent=10.0, now=0)
    meter.push(running=True, buying=False, adena=1100, level=10, exp_percent=20.0, now=30)
    paused = meter.push(
        running=False, buying=False, adena=1100, level=10, exp_percent=20.0, now=40
    )
    assert paused["adena_gained"] == 100
    assert paused["elapsed"] == 40
    assert paused["exp_rate"] == _hour(10.0, 40)
    skipped = meter.push(
        running=False, buying=False, adena=9000, level=12, exp_percent=80.0, now=90
    )
    assert skipped["adena_gained"] == 100
    assert skipped["exp_rate"] == _hour(10.0, 40)
    assert skipped["elapsed"] == 40
    meter.push(running=True, buying=False, adena=9000, level=12, exp_percent=80.0, now=100)
    resumed = meter.push(
        running=True, buying=False, adena=9050, level=12, exp_percent=85.0, now=130
    )
    assert resumed["adena_gained"] == 150
    assert resumed["exp_rate"] == _hour(15.0, 70)
    assert resumed["adena_rate"] == _hour(150, 70)
    assert resumed["elapsed"] == 70


def test_stop_keeps_totals_the_same_way_pause_does() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=500, level=4, exp_percent=1.0, now=0)
    running = meter.push(
        running=True, buying=False, adena=800, level=4, exp_percent=6.0, now=20
    )
    stopped = meter.push(
        running=False, buying=False, adena=800, level=4, exp_percent=6.0, now=20
    )
    assert stopped["adena_gained"] == running["adena_gained"] == 300
    assert stopped["exp_rate"] == running["exp_rate"] == _hour(5.0, 20)
    assert stopped["elapsed"] == 20
    later = meter.push(
        running=False, buying=False, adena=50, level=4, exp_percent=90.0, now=50
    )
    assert later["adena_gained"] == 300
    assert later["exp_rate"] == _hour(5.0, 20)
    assert later["elapsed"] == 20


def test_shop_purchase_is_ignored_and_a_sale_is_kept() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=5000, level=1, exp_percent=0.0, now=0)
    bought = meter.push(
        running=True, buying=True, adena=4000, level=1, exp_percent=0.0, now=20
    )
    assert bought["adena_gained"] == 0
    sold = meter.push(
        running=True, buying=True, adena=4600, level=1, exp_percent=0.0, now=40
    )
    assert sold["adena_gained"] == 600


def test_level_up_keeps_the_rest_of_the_previous_bar() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=1, level=10, exp_percent=90.0, now=0)
    view = meter.push(
        running=True, buying=False, adena=1, level=11, exp_percent=10.0, now=30
    )
    assert view["exp_rate"] == _hour(20.0, 30)


def test_exp_reset_while_running_restarts_only_the_exp_clock() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=1000, level=10, exp_percent=10.0, now=0)
    before = meter.push(
        running=True, buying=False, adena=1300, level=10, exp_percent=25.0, now=100
    )
    reset = meter.reset_exp(level=10, exp_percent=25.0, running=True, now=100)
    assert reset["exp_rate"] is None
    assert reset["adena_gained"] == before["adena_gained"] == 300
    assert reset["elapsed"] == 100
    assert reset["adena_rate"] == _hour(300, 100)
    hidden = meter.push(
        running=True, buying=False, adena=1300, level=10, exp_percent=26.0, now=114
    )
    assert hidden["exp_rate"] is None
    shown = meter.push(
        running=True, buying=False, adena=1300, level=10, exp_percent=26.0, now=116
    )
    assert shown["exp_rate"] == _hour(1.0, 16)
    assert shown["adena_gained"] == 300
    assert shown["adena_rate"] == _hour(300, 116)
    assert shown["elapsed"] == 116


def test_adena_reset_while_running_restarts_only_the_adena_clock() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=1000, level=8, exp_percent=40.0, now=0)
    meter.push(running=True, buying=False, adena=1800, level=8, exp_percent=46.0, now=30)
    reset = meter.reset_adena(adena=1800, running=True, now=30)
    assert reset["adena_gained"] == 0
    assert reset["elapsed"] == 0
    assert reset["adena_rate"] is None
    assert reset["exp_rate"] == _hour(6.0, 30)
    meter.push(running=True, buying=True, adena=1000, level=8, exp_percent=47.0, now=50)
    after_buy = meter.push(
        running=True, buying=False, adena=1250, level=8, exp_percent=48.0, now=60
    )
    assert after_buy["adena_gained"] == 250
    assert after_buy["adena_rate"] == _hour(250, 30)
    assert after_buy["exp_rate"] == _hour(8.0, 60)
    assert after_buy["elapsed"] == 30


def test_exp_reset_while_paused_ignores_play_until_the_next_run() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=1000, level=10, exp_percent=10.0, now=0)
    meter.push(running=True, buying=False, adena=1100, level=10, exp_percent=20.0, now=40)
    meter.push(running=False, buying=False, adena=1100, level=10, exp_percent=20.0, now=40)
    meter.reset_exp(level=20, exp_percent=50.0, running=False, now=40)
    held = meter.push(
        running=False, buying=False, adena=8000, level=15, exp_percent=90.0, now=80
    )
    assert held["exp_rate"] is None
    assert held["adena_gained"] == 100
    assert held["elapsed"] == 40
    meter.push(running=True, buying=False, adena=8000, level=15, exp_percent=90.0, now=100)
    resumed = meter.push(
        running=True, buying=False, adena=8000, level=15, exp_percent=91.0, now=120
    )
    assert resumed["exp_rate"] == _hour(1.0, 20)
    assert resumed["adena_gained"] == 100
    assert resumed["elapsed"] == 60


def test_adena_reset_while_stopped_ignores_play_until_the_next_run() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=2000, level=3, exp_percent=5.0, now=0)
    meter.push(running=True, buying=False, adena=2600, level=3, exp_percent=9.0, now=30)
    meter.push(running=False, buying=False, adena=2600, level=3, exp_percent=9.0, now=30)
    meter.reset_adena(adena=2600, running=False, now=30)
    held = meter.push(
        running=False, buying=False, adena=100, level=3, exp_percent=40.0, now=70
    )
    assert held["adena_gained"] == 0
    assert held["elapsed"] == 0
    assert held["adena_rate"] is None
    assert held["exp_rate"] == _hour(4.0, 30)
    meter.push(running=True, buying=False, adena=100, level=3, exp_percent=40.0, now=80)
    resumed = meter.push(
        running=True, buying=False, adena=180, level=3, exp_percent=41.0, now=100
    )
    assert resumed["adena_gained"] == 80
    assert resumed["adena_rate"] == _hour(80, 20)
    assert resumed["exp_rate"] == _hour(5.0, 50)


def test_level_up_after_exp_reset_uses_the_new_baseline() -> None:
    meter = _Meter()
    meter.push(running=True, buying=False, adena=10, level=10, exp_percent=90.0, now=0)
    meter.push(running=True, buying=False, adena=10, level=11, exp_percent=10.0, now=20)
    meter.reset_exp(level=11, exp_percent=10.0, running=True, now=20)
    view = meter.push(
        running=True, buying=False, adena=10, level=12, exp_percent=4.0, now=40
    )
    assert view["exp_rate"] == _hour(94.0, 20)
    assert view["adena_gained"] == 0


def test_continued_running_does_not_move_the_baseline_by_itself() -> None:
    """Solo and party both publish samples here. Switching mode is not a reset."""
    meter = _Meter()
    meter.push(running=True, buying=False, adena=100, level=2, exp_percent=1.0, now=0)
    kept = meter.push(
        running=True, buying=False, adena=140, level=2, exp_percent=3.0, now=20
    )
    assert kept["adena_gained"] == 40
    assert kept["exp_rate"] == _hour(2.0, 20)
    assert "party" not in inspect.signature(_Meter.push).parameters


def test_mode_switch_does_not_call_the_income_reset() -> None:
    mode = inspect.getsource(TaskEditor.set_settings_mode)
    button = inspect.getsource(ScheduleShell._on_mode_button)
    assert "reset_" not in mode
    assert "income" not in mode
    assert "reset_" not in button
    assert "income_bar" not in button


def test_reset_buttons_sit_in_the_card_corners_and_reset_one_card() -> None:
    _app()
    income._read_sample = lambda: (9286, 9, 54.3)  # type: ignore[assignment]
    bar = LiveIncomeBar(language="ko", running=lambda: True, buying=lambda: False)
    try:
        bar.resize(1200, 88)
        bar.show()
        app = QApplication.instance()
        assert app is not None
        bar.repaint()
        app.processEvents()
        assert bar.height() == 88
        exp = bar.findChild(type(bar._exp_reset), "income_exp_reset")
        adena = bar.findChild(type(bar._adena_reset), "income_adena_reset")
        assert exp is not None and adena is not None
        assert exp.toolTip() == "경험치 측정 초기화"
        assert adena.toolTip() == "아데나 측정 초기화"
        assert exp.pos() == bar._exp_reset.pos()
        assert adena.pos() == bar._adena_reset.pos()
        margin = 9
        assert exp.y() == margin and adena.y() == margin
        assert exp.size().width() == 16 and adena.size().width() == 16
        assert adena.x() + adena.width() + margin == bar.width() - 1
        assert exp.x() + exp.width() + margin < adena.x()
        for button in (exp, adena):
            assert bar.rect().contains(button.geometry())
        calls: dict[str, object] = {}

        def reset_exp(level, exp_percent):
            calls["exp"] = (level, exp_percent)
            return dict(bar._view)

        def reset_adena(amount):
            calls["adena"] = amount
            return dict(bar._view)

        bar._session.reset_exp = reset_exp  # type: ignore[method-assign]
        bar._session.reset_adena = reset_adena  # type: ignore[method-assign]
        exp.click()
        assert calls["exp"] == (9, 54.3)
        assert "adena" not in calls
        adena.click()
        assert calls["adena"] == 9286
        assert calls["exp"] == (9, 54.3)
        bar._language = "zh"
        bar.update()
        app.processEvents()
        assert exp.toolTip() == "重置经验值统计"
        assert adena.toolTip() == "重置金币统计"
        bar.shutdown()
    finally:
        income._read_sample = lambda: (None, None, None)  # type: ignore[assignment]
