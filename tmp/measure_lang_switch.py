"""Temporary language-switch timing. Does not edit product source.

save_trial / save_app_state are redirected to tmp so the real profile is not written.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "UI"), str(ROOT / "Engine")]
os.environ["QT_QPA_PLATFORM"] = "windows"

OUT = ROOT / "tmp" / "lang_measure_out"
OUT.mkdir(parents=True, exist_ok=True)
_LOG = (OUT / "progress.txt").open("w", encoding="utf-8")


def log(message: str) -> None:
    _LOG.write(message + "\n")
    _LOG.flush()


import faulthandler

faulthandler.enable(_LOG)

from session.paths import APP_PATH, TRIAL_ROUTINE_PATH, TRIAL_SETTINGS_PATH  # noqa: E402

BEFORE = {
    "app": APP_PATH.read_bytes() if APP_PATH.is_file() else b"",
    "settings": TRIAL_SETTINGS_PATH.read_bytes() if TRIAL_SETTINGS_PATH.is_file() else b"",
    "routine": TRIAL_ROUTINE_PATH.read_bytes() if TRIAL_ROUTINE_PATH.is_file() else b"",
}


def _guard_writes() -> None:
    import settings.trial_store as trial

    def save_trial(settings=None, routine=None) -> None:
        (OUT / "trial_settings.json").write_text(
            json.dumps({"settings": bool(settings), "routine": bool(routine)}, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_app_state(state) -> None:
        (OUT / "app_state.json").write_text(
            json.dumps(state, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    trial.save_trial = save_trial
    trial.save_app_state = save_app_state


_guard_writes()

from PySide6.QtCore import QEvent, QObject, QTimer  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.schedule_i18n import tr  # noqa: E402
from ui_qt.i18n_overlay import merge_ui_strings  # noqa: E402
from ui_qt.theme.apply import apply_classic_qt_theme  # noqa: E402
from ui_qt.theme.fonts import load_qt_fonts  # noqa: E402

SPANS: list[dict] = []
_STACK: list[str] = []


def _wrap(obj, attr: str, name: str):
    orig = getattr(obj, attr)

    def inner(*args, **kwargs):
        _STACK.append(name)
        start = time.perf_counter()
        try:
            return orig(*args, **kwargs)
        finally:
            end = time.perf_counter()
            _STACK.pop()
            SPANS.append(
                {
                    "name": name,
                    "start": start,
                    "end": end,
                    "parent": _STACK[-1] if _STACK else "",
                }
            )

    setattr(obj, attr, inner)
    return orig


def _exclusive(rows: list[dict]) -> list[dict]:
    for row in rows:
        contained = [
            other
            for other in rows
            if other is not row
            and other["start"] >= row["start"] - 1e-9
            and other["end"] <= row["end"] + 1e-9
        ]
        direct = []
        for child in contained:
            if any(
                child is not other
                and other["start"] <= child["start"]
                and other["end"] >= child["end"]
                and (other["end"] - other["start"]) < (row["end"] - row["start"]) - 1e-9
                for other in contained
            ):
                continue
            direct.append(child)
        row["incl"] = row["end"] - row["start"]
        row["excl"] = row["incl"] - sum(item["end"] - item["start"] for item in direct)
        row["direct"] = [item["name"] for item in direct]
    return rows


def _summary(values: list[float]) -> str:
    if not values:
        return "n=0"
    ordered = sorted(values)
    mid = ordered[len(ordered) // 2]
    return (
        f"n={len(values)} median={mid*1000:.0f}ms "
        f"max={max(values)*1000:.0f}ms min={min(values)*1000:.0f}ms"
    )


def main() -> int:
    app = QApplication.instance() or QApplication([])
    log(f"platform {app.platformName()}")
    print("platform", app.platformName(), flush=True)

    def bench(label: str, fn) -> None:
        samples = []
        for _ in range(5):
            t0 = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - t0)
        line = f"micro {label}: {_summary(samples)}"
        log(line)
        print(line, flush=True)

    bench("tr ko", lambda: tr("ko"))
    bench("tr zh", lambda: tr("zh"))
    bench("merge ko", lambda: merge_ui_strings("ko", tr("ko")))
    bench("merge zh", lambda: merge_ui_strings("zh", tr("zh")))

    t0 = time.perf_counter()
    load_qt_fonts("ko")
    log(f"font cold ko: {(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"font cold ko: {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
    t0 = time.perf_counter()
    load_qt_fonts("ko")
    log(f"font warm ko: {(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"font warm ko: {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
    t0 = time.perf_counter()
    load_qt_fonts("zh")
    log(f"font cold zh: {(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"font cold zh: {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
    t0 = time.perf_counter()
    load_qt_fonts("zh")
    log(f"font warm zh: {(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"font warm zh: {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)

    import settings.profile as profile_mod
    from settings.profile import load_profile

    profile = load_profile()
    profile.always_on_top = False
    start_lang = str(profile.language or "ko")
    other = "zh" if start_lang != "zh" else "ko"
    print("start_language", start_lang, "other", other)

    t0 = time.perf_counter()
    profile_mod.save_profile(profile)
    print(f"save_profile redirected: {(time.perf_counter()-t0)*1000:.0f}ms")

    from ui_qt.editors.party_tab import PartyTab
    from ui_qt.editors.party_workspace import PartyWorkspace
    from ui_qt.editors.task_editor import TaskEditor
    from ui_qt.shell.schedule_list import ScheduleListPane
    from ui_qt.shell.schedule_shell import ScheduleShell
    from ui_qt.theme import fonts as font_mod
    import session.probes as probes

    _wrap(font_mod, "load_qt_fonts", "load_qt_fonts")
    _wrap(QFontDatabase, "addApplicationFont", "addApplicationFont")
    _wrap(probes, "probe_game", "probe_game")
    _wrap(probes, "probe_memory", "probe_memory")
    _wrap(probes, "probe_map", "probe_map")
    _wrap(ScheduleListPane, "__init__", "ScheduleListPane")
    _wrap(TaskEditor, "__init__", "TaskEditor")
    _wrap(PartyTab, "__init__", "PartyTab")
    _wrap(PartyWorkspace, "__init__", "PartyWorkspace")
    _wrap(ScheduleShell, "_build", "_build")
    _wrap(ScheduleShell, "_edit_selected", "_edit_selected")
    _wrap(ScheduleShell, "_begin_new", "_begin_new")
    _wrap(ScheduleShell, "_refresh_operator", "_refresh_operator")
    _wrap(sys.modules["ui_qt.theme.apply"], "apply_classic_qt_theme", "apply_theme")

    ScheduleShell._warm_memory_monitor = lambda self: None  # type: ignore[method-assign]

    paint_marks: list[float] = []

    class PaintWatch(QObject):
        def eventFilter(self, obj, event) -> bool:  # noqa: N802
            if event.type() == QEvent.Type.Paint and obj is shell:
                paint_marks.append(time.perf_counter())
            return False

    log("constructing shell")
    t0 = time.perf_counter()
    shell = ScheduleShell(profile)
    shell.show()
    app.processEvents()
    log(f"shell construct+show+events: {(time.perf_counter()-t0)*1000:.0f}ms")
    print(f"shell construct+show+events: {(time.perf_counter()-t0)*1000:.0f}ms", flush=True)
    print("tasks", len(shell.tasks), "mode", getattr(shell, "_settings_mode", "solo"))
    watch = PaintWatch()
    shell.installEventFilter(watch)

    runs: list[dict] = []

    def one(label: str, language: str, mode: str) -> None:
        log(f"begin {label} {mode} {language}")
        shell._settings_mode = mode
        mark = {"loop": None}
        start = time.perf_counter()
        paint_before = len(paint_marks)
        span_before = len(SPANS)
        shell._rebuild_for_language(language)
        handler = time.perf_counter()
        QTimer.singleShot(0, lambda: mark.__setitem__("loop", time.perf_counter()))
        app.processEvents()
        after_events = time.perf_counter()
        shell.repaint()
        after_repaint = time.perf_counter()
        paints = paint_marks[paint_before:]
        first_paint = paints[0] if paints else None
        rows = _exclusive(SPANS[span_before:])
        interesting = [
            "load_qt_fonts",
            "addApplicationFont",
            "apply_theme",
            "_build",
            "ScheduleListPane",
            "TaskEditor",
            "PartyTab",
            "PartyWorkspace",
            "_edit_selected",
            "_begin_new",
            "_refresh_operator",
            "probe_game",
            "probe_memory",
            "probe_map",
        ]
        parts = {}
        for name in interesting:
            incl = [row["incl"] for row in rows if row["name"] == name]
            excl = [row["excl"] for row in rows if row["name"] == name]
            if incl:
                parts[name] = {
                    "incl_ms": round(sum(incl) * 1000, 1),
                    "excl_ms": round(sum(excl) * 1000, 1),
                    "calls": len(incl),
                }
        theme_calls = parts.get("apply_theme", {}).get("calls", 0)
        run = {
            "label": label,
            "language": language,
            "mode": mode,
            "title": shell.windowTitle(),
            "handler_ms": round((handler - start) * 1000, 1),
            "processEvents_ms": round((after_events - handler) * 1000, 1),
            "singleShot0_ms": (
                None
                if mark["loop"] is None
                else round((mark["loop"] - start) * 1000, 1)
            ),
            "first_paint_ms": (
                None if first_paint is None else round((first_paint - start) * 1000, 1)
            ),
            "repaint_call_ms": round((after_repaint - after_events) * 1000, 1),
            "until_repaint_ms": round((after_repaint - start) * 1000, 1),
            "theme_calls": theme_calls,
            "parts": parts,
        }
        runs.append(run)
        log(
            f"done {label} handler={run['handler_ms']} events={run['processEvents_ms']} "
            f"paint={run['first_paint_ms']} parts={parts}"
        )
        print(
            f"{label} {mode} -> {language} handler={run['handler_ms']}ms "
            f"events={run['processEvents_ms']}ms paint={run['first_paint_ms']} "
            f"repaint={run['repaint_call_ms']}ms theme_calls={theme_calls} "
            f"title={run['title']}",
            flush=True,
        )

    one("first-other", other, "solo")
    one("first-back", start_lang, "solo")
    for index in range(4):
        one(f"repeat-other-{index}", other, "solo")
        one(f"repeat-back-{index}", start_lang, "solo")
    one("party-picker", other, "party")
    one("party-picker-back", start_lang, "party")
    # Role pages are built inside the same PartyTab. Show each, then rebuild.
    shell.editor.party_workspace._on_role_chosen("leader")
    app.processEvents()
    one("party-leader", other, "party")
    shell.editor.party_workspace.set_locked(False, "")
    shell.editor.party_workspace.show_picker()
    shell.editor.party_workspace._on_role_chosen("member")
    app.processEvents()
    one("party-member", start_lang, "party")

    def group(prefix: str, key: str) -> None:
        values = [row[key] for row in runs if row["label"].startswith(prefix) and row[key] is not None]
        print(f"group {prefix} {key}: {_summary([value/1000 for value in values])}")

    group("first-", "handler_ms")
    group("repeat-", "handler_ms")
    group("repeat-", "until_repaint_ms")
    group("party-", "handler_ms")

    (OUT / "runs.json").write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    shell.close()
    app.processEvents()

    after = {
        "app": APP_PATH.read_bytes() if APP_PATH.is_file() else b"",
        "settings": TRIAL_SETTINGS_PATH.read_bytes() if TRIAL_SETTINGS_PATH.is_file() else b"",
        "routine": TRIAL_ROUTINE_PATH.read_bytes() if TRIAL_ROUTINE_PATH.is_file() else b"",
    }
    print("userdata_unchanged", before_same(BEFORE, after))
    return 0


def before_same(before: dict, after: dict) -> bool:
    return before == after


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        after = {
            "app": APP_PATH.read_bytes() if APP_PATH.is_file() else b"",
            "settings": TRIAL_SETTINGS_PATH.read_bytes() if TRIAL_SETTINGS_PATH.is_file() else b"",
            "routine": TRIAL_ROUTINE_PATH.read_bytes() if TRIAL_ROUTINE_PATH.is_file() else b"",
        }
        print("userdata_unchanged", BEFORE == after)
        raise SystemExit(1)
