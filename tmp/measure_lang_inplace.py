"""Time the in-place language switch. Does not write the real profile."""

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

SAVES: list[str] = []


def _noop_save(*_args, **_kwargs) -> None:
    SAVES.append("save")


trial.save_trial = _noop_save
trial.save_app_state = _noop_save

from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget  # noqa: E402
from settings.profile import load_profile  # noqa: E402
from ui_qt.shell import schedule_shell as shell_mod  # noqa: E402

app = QApplication.instance() or QApplication([])
profile = load_profile()
profile.always_on_top = False
start = str(profile.language or "ko")
other = "ko" if start == "zh" else "zh"

real_theme = shell_mod.apply_classic_qt_theme
theme_log: list[dict] = []


def timed_theme(app_obj, language="en", *widgets, font_size=8, section_size=None, restyle=True):
    style_ms = {"v": 0.0}
    real_style = QApplication.setStyleSheet

    def style(self, text):
        t0 = time.perf_counter()
        try:
            return real_style(self, text)
        finally:
            style_ms["v"] += (time.perf_counter() - t0) * 1000

    QApplication.setStyleSheet = style
    t0 = time.perf_counter()
    try:
        return real_theme(
            app_obj,
            language,
            *widgets,
            font_size=font_size,
            section_size=section_size,
            restyle=restyle,
        )
    finally:
        QApplication.setStyleSheet = real_style
        theme_log.append(
            {
                "language": language,
                "restyle": restyle,
                "total_ms": round((time.perf_counter() - t0) * 1000, 1),
                "stylesheet_ms": round(style_ms["v"], 1),
            }
        )


shell_mod.apply_classic_qt_theme = timed_theme
shell_mod.ScheduleShell._warm_memory_monitor = lambda self: None

app_path = ROOT / "UserData" / "app.json"
settings_path = ROOT / "UserData" / "trial" / "settings.json"
routine_path = ROOT / "UserData" / "trial" / "routine.json"


def stamp(path: Path) -> int | None:
    return path.stat().st_mtime_ns if path.is_file() else None


before_stamp = {name: stamp(path) for name, path in {
    "app": app_path, "settings": settings_path, "routine": routine_path
}.items()}

shell = shell_mod.ScheduleShell(profile)
shell.show()
app.processEvents()
shell.editor.party_tab.roster_name.setText("keep-this-name")
selected_before = shell.schedule_list.selected_index()
rows = []


def hangul_count() -> int:
    count = 0
    for widget in shell.findChildren(QWidget):
        text = ""
        if isinstance(widget, (QLabel, QAbstractButton)):
            text = widget.text()
        if any("\uac00" <= ch <= "\ud7a3" for ch in text):
            count += 1
    return count


def switch(label: str, language: str) -> None:
    combo = shell.language_combo
    combo.blockSignals(True)
    for index in range(combo.count()):
        if combo.itemData(index) == language:
            combo.setCurrentIndex(index)
            break
    combo.blockSignals(False)
    before = len(shell.findChildren(QWidget))
    theme_at = len(theme_log)
    t0 = time.perf_counter()
    shell._on_language_changed()
    handler = (time.perf_counter() - t0) * 1000
    app.processEvents()
    button = shell._solo_mode_btn
    row = {
        "label": label,
        "language": language,
        "title": shell.windowTitle(),
        "handler_ms": round(handler, 1),
        "widgets_before": before,
        "widgets_after": len(shell.findChildren(QWidget)),
        "selected": shell.schedule_list.selected_index(),
        "typed": shell.editor.party_tab.roster_name.text(),
        "solo_button": button.text(),
        "font": button.font().family(),
        "hangul_labels": hangul_count(),
        "theme": theme_log[theme_at:],
        "saves": len(SAVES),
    }
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)


print("start", start, "widgets", len(shell.findChildren(QWidget)), flush=True)
switch("to-other", other)
switch("back", start)
switch("to-other-again", other)
after_stamp = {name: stamp(path) for name, path in {
    "app": app_path, "settings": settings_path, "routine": routine_path
}.items()}
(OUT / "inplace_runs.json").write_text(
    json.dumps({"before": before_stamp, "after": after_stamp, "rows": rows}, indent=2),
    encoding="utf-8",
)
shell.close()
app.processEvents()
print("stamps", before_stamp == after_stamp, flush=True)
print("done", flush=True)
