"""Live smoothness checks for Start and debug vision preview.

Run:
    python\\python.exe tests\\test_live_ui_smoothness.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MANMABOT_ROOT", str((ROOT / "engine").resolve()))
for path in (ROOT, ROOT / "engine"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def _assert(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def test_start_and_stop_stay_off_ui_thread() -> dict[str, float]:
    import manmabot_v1.bot_controller as bot_mod
    from manmabot_v1.bot_controller import BotController, RunState
    from manmabot_v1.profile import Profile

    slept: list[float] = []
    joined: list[float] = []
    original_sleep = time.sleep
    original_thread = bot_mod.threading.Thread
    original_probe = bot_mod.probe_game
    original_pause = bot_mod.pause_reason_from_game
    original_front = bot_mod.bring_game_to_front

    def fake_sleep(seconds: float) -> None:
        slept.append(float(seconds))

    class FakeThread:
        def __init__(self, *args, **kwargs) -> None:
            self._alive = True

        def start(self) -> None:
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:
            joined.append(0.0 if timeout is None else float(timeout))
            original_sleep(min(timeout or 0.0, 0.01))

    controller = BotController()
    profile = Profile(wizard_completed=True, selected_farms=["a"])
    controller.start_gates_ok = lambda _profile: None  # type: ignore[method-assign]
    bot_mod.probe_game = lambda: SimpleNamespace(lamp="green", hwnd=11)  # type: ignore[assignment]
    bot_mod.pause_reason_from_game = lambda *_a, **_k: None  # type: ignore[assignment]
    bot_mod.bring_game_to_front = lambda _hwnd: None  # type: ignore[assignment]
    bot_mod.threading.Thread = FakeThread  # type: ignore[assignment]
    time.sleep = fake_sleep  # type: ignore[assignment]
    try:
        t0 = time.perf_counter()
        err = controller.start(profile)
        start_ms = (time.perf_counter() - t0) * 1000.0
        _assert(err is None, f"start failed: {err}")
        _assert(controller.state is RunState.RUNNING, "start did not enter Running")
        _assert(slept == [], f"start slept on caller thread: {slept}")
        _assert(start_ms < 80.0, f"start blocked UI for {start_ms:.1f}ms")

        t1 = time.perf_counter()
        controller.stop()
        stop_ms = (time.perf_counter() - t1) * 1000.0
        _assert(joined == [], f"stop joined worker on caller thread: {joined}")
        _assert(stop_ms < 80.0, f"stop blocked UI for {stop_ms:.1f}ms")
        return {"start_ms": start_ms, "stop_ms": stop_ms}
    finally:
        time.sleep = original_sleep  # type: ignore[assignment]
        bot_mod.threading.Thread = original_thread
        bot_mod.probe_game = original_probe
        bot_mod.pause_reason_from_game = original_pause
        bot_mod.bring_game_to_front = original_front


def test_preview_only_when_section_open() -> None:
    from manmabot_v1.bot_controller import BotController

    controller = BotController()
    controller.add_debug_watcher()
    _assert(not controller._preview_enabled.is_set(), "debug watcher enabled preview")
    controller.add_preview_watcher()
    _assert(controller._preview_enabled.is_set(), "preview watcher did not enable preview")
    controller.remove_preview_watcher()
    _assert(not controller._preview_enabled.is_set(), "closing preview left encode on")
    controller.remove_debug_watcher()


def test_unread_preview_does_not_encode() -> None:
    from manmabot_v1.bot_controller import BotController

    controller = BotController()
    controller.set_preview_enabled(True)
    controller._preview_q.put(b"old")
    encoded: list[object] = []

    import app._02_vision.preview as preview

    original = preview.encode_preview_jpeg

    def fake_encode(image, **_kwargs):
        encoded.append(image)
        return b"new"

    preview.encode_preview_jpeg = fake_encode  # type: ignore[assignment]
    try:
        controller._push_preview_image(object())
        _assert(encoded == [], "encoded while UI still held a frame")
        _assert(controller.pop_preview_jpeg() == b"old", "lost unread preview")
        controller._push_preview_image(object())
        _assert(encoded, "did not encode after UI consumed the frame")
        _assert(controller.pop_preview_jpeg() == b"new", "missing new preview")
    finally:
        preview.encode_preview_jpeg = original  # type: ignore[assignment]


def _solid_jpeg(width: int = 640, height: int = 360) -> bytes:
    import numpy as np
    from app._02_vision.preview import encode_preview_jpeg

    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :] = (40, 180, 90)
    frame[20:40, 20:80] = (0, 255, 255)
    data = encode_preview_jpeg(frame, quality=55, max_width=720)
    _assert(bool(data), "failed to encode test jpeg")
    return data or b""


def test_debug_preview_ui_is_smooth() -> dict[str, float]:
    import tkinter as tk

    from manmabot_v1.bot_controller import BotController
    from manmabot_v1.ui.debug_ui import DebugPanel, DebugWindow
    from manmabot_v1.ui.design_system import apply_classic_style
    from manmabot_v1.ui.schedule_i18n import tr

    root = tk.Tk()
    root.withdraw()
    apply_classic_style(root, "en")
    controller = BotController()
    strings = tr("en")
    panel = DebugPanel(
        root,
        controller=controller,
        get_logs=lambda: ["09:00:00  ready"],
        t=strings,
    )
    panel.pack(fill="both", expand=True)
    root.update()

    _assert(not controller._preview_enabled.is_set(), "preview on before selecting it")
    preview_index = list(panel.listbox.get(0, "end")).index(strings["debug_preview"])
    panel.listbox.selection_clear(0, "end")
    panel.listbox.selection_set(preview_index)
    panel._on_select()
    root.update()
    _assert(panel._section == "preview", "did not switch to vision preview")
    _assert(controller._preview_enabled.is_set(), "preview section did not arm encode")

    jpeg = _solid_jpeg()
    apply_ms: list[float] = []
    for _ in range(12):
        controller._drain_preview_queue()
        controller._preview_q.put_nowait(jpeg)
        panel._photo = None
        t0 = time.perf_counter()
        panel.refresh()
        deadline = time.perf_counter() + 1.0
        while time.perf_counter() < deadline:
            root.update()
            panel.refresh()
            if panel._photo is not None and not panel._preview_busy:
                break
            time.sleep(0.005)
        apply_ms.append((time.perf_counter() - t0) * 1000.0)
    _assert(panel._photo is not None, "preview never painted a frame")

    window = DebugWindow(
        root,
        controller=controller,
        get_logs=lambda: [],
        t=strings,
    )
    root.update()
    t0 = time.perf_counter()
    window.panel.listbox.selection_clear(0, "end")
    window.panel.listbox.selection_set(preview_index)
    window.panel._on_select()
    root.update()
    select_ms = (time.perf_counter() - t0) * 1000.0
    _assert(window.panel._section == "preview", "debug window preview select failed")

    window._close()
    root.update()
    panel._set_previewing(False)
    root.destroy()
    worst = max(apply_ms)
    avg = sum(apply_ms) / len(apply_ms)
    _assert(worst < 250.0, f"preview apply hitch {worst:.1f}ms")
    return {
        "preview_apply_avg_ms": avg,
        "preview_apply_max_ms": worst,
        "preview_select_ms": select_ms,
    }


def test_start_button_click_stays_responsive() -> dict[str, float]:
    import tkinter as tk

    from manmabot_v1.bot_controller import RunState
    from manmabot_v1.ui.debug_ui import DebugPlayer

    clicks: list[str] = []

    app = DebugPlayer()
    app.withdraw()
    app.update()
    app.coordinator.start = lambda: clicks.append("start") or None  # type: ignore[method-assign]
    app.coordinator.resume = lambda: clicks.append("resume")  # type: ignore[method-assign]
    app.coordinator.close = lambda: None  # type: ignore[method-assign]
    app.coordinator.controller.pause_user = lambda: clicks.append("pause")  # type: ignore[method-assign]
    app.coordinator.controller.state = RunState.STOPPED
    app.stop_btn.configure(command=lambda: clicks.append("stop"))

    t0 = time.perf_counter()
    app.start_btn.invoke()
    app.update()
    click_ms = (time.perf_counter() - t0) * 1000.0
    _assert(clicks == ["start"], f"start button did not fire cleanly: {clicks}")
    _assert(click_ms < 80.0, f"start button click blocked {click_ms:.1f}ms")

    app.coordinator.controller.state = RunState.RUNNING
    app._refresh_controls()
    app.update()
    _assert(str(app.start_btn.cget("state")) == "disabled", "start stayed enabled while running")

    t1 = time.perf_counter()
    app.stop_btn.invoke()
    app.update()
    stop_click_ms = (time.perf_counter() - t1) * 1000.0
    _assert(clicks == ["start", "stop"], f"stop button did not fire cleanly: {clicks}")
    _assert(stop_click_ms < 80.0, f"stop button click blocked {stop_click_ms:.1f}ms")

    app._on_close()
    return {"start_click_ms": click_ms, "stop_click_ms": stop_click_ms}


def main() -> int:
    results: dict[str, float] = {}
    test_preview_only_when_section_open()
    test_unread_preview_does_not_encode()
    results.update(test_start_and_stop_stay_off_ui_thread())
    results.update(test_debug_preview_ui_is_smooth())
    results.update(test_start_button_click_stays_responsive())
    print("LIVE SMOOTHNESS OK")
    for key, value in results.items():
        print(f"  {key}={value:.2f}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
