"""Second timing pass: attribute the uncounted part of _rebuild_for_language.

Does not write the real profile. Three switches only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "UI"), str(ROOT / "Engine")]
os.environ["QT_QPA_PLATFORM"] = "windows"

OUT = ROOT / "tmp" / "lang_measure_out"
OUT.mkdir(parents=True, exist_ok=True)

import settings.trial_store as trial  # noqa: E402


def _noop_trial(*_args, **_kwargs) -> None:
    return None


trial.save_trial = _noop_trial
trial.save_app_state = _noop_trial

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from settings.profile import load_profile  # noqa: E402
from ui_qt.shell import schedule_shell as shell_mod  # noqa: E402

app = QApplication.instance() or QApplication([])
profile = load_profile()
profile.always_on_top = False
start = str(profile.language or "ko")
other = "ko" if start == "zh" else "zh"

real_theme = shell_mod.apply_classic_qt_theme
real_save = shell_mod.save_profile
theme_log: list[dict] = []
save_ms: list[float] = []


def timed_save(profile_obj, path=None):
    t0 = time.perf_counter()
    try:
        return real_save(profile_obj, path)
    finally:
        save_ms.append((time.perf_counter() - t0) * 1000)


def timed_theme(app_obj, language="en", *widgets, font_size=8, section_size=None):
    from PySide6.QtWidgets import QApplication as QA

    children = []
    for widget in widgets:
        children.append(len(widget.findChildren(QWidget)))
    style_ms = {"v": 0.0}
    font_ms = {"v": 0.0}
    font_n = {"v": 0}
    real_style = QA.setStyleSheet
    real_font = QWidget.setFont

    def style(self, text):
        t0 = time.perf_counter()
        try:
            return real_style(self, text)
        finally:
            style_ms["v"] += (time.perf_counter() - t0) * 1000

    def font(self, value):
        t0 = time.perf_counter()
        try:
            return real_font(self, value)
        finally:
            font_ms["v"] += (time.perf_counter() - t0) * 1000
            font_n["v"] += 1

    QA.setStyleSheet = style
    QWidget.setFont = font
    t0 = time.perf_counter()
    try:
        return real_theme(
            app_obj,
            language,
            *widgets,
            font_size=font_size,
            section_size=section_size,
        )
    finally:
        QA.setStyleSheet = real_style
        QWidget.setFont = real_font
        theme_log.append(
            {
                "language": language,
                "children": children,
                "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                "stylesheet_ms": round(style_ms["v"], 1),
                "setfont_ms": round(font_ms["v"], 1),
                "setfont_calls": font_n["v"],
            }
        )


shell_mod.apply_classic_qt_theme = timed_theme
shell_mod.save_profile = timed_save
shell_mod.ScheduleShell._warm_memory_monitor = lambda self: None

shell = shell_mod.ScheduleShell(profile)
shell.show()
app.processEvents()
rows = []


def switch(label: str, language: str, mode: str) -> None:
    before = len(shell.findChildren(QWidget))
    shell._settings_mode = mode
    t0 = time.perf_counter()
    shell._rebuild_for_language(language)
    handler = (time.perf_counter() - t0) * 1000
    app.processEvents()
    after = len(shell.findChildren(QWidget))
    row = {
        "label": label,
        "mode": mode,
        "language": language,
        "title": shell.windowTitle(),
        "handler_ms": round(handler, 1),
        "widgets_before": before,
        "widgets_after_events": after,
        "save_ms": round(save_ms[-1], 1) if save_ms else None,
        "theme": theme_log[-1] if theme_log else None,
    }
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


print("start", start, "widgets", len(shell.findChildren(QWidget)), flush=True)
switch("to-other", other, "solo")
switch("back", start, "solo")
switch("party", other, "party")
(OUT / "theme_runs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
shell.close()
app.processEvents()
print("done", flush=True)
