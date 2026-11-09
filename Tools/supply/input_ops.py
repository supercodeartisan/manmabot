"""Interception mouse helpers + qty typing for supply drops."""
from __future__ import annotations

import random
import time
from typing import Any, Optional

import ctypes

from app._05_action import mouse as mouse_mod
from app._05_action.keyboard import KeyboardController
from app._05_action.mouse import MouseController
from app._05_action.window_bounds import find_game_window

GAME_PROCESS = "LC.exe"


def ensure_input() -> None:
    mouse_mod.prepare_capture()


def focus_game() -> bool:
    """Bring LC.exe to the foreground so keys hit the game, not the GUI."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = find_game_window(GAME_PROCESS)
    if hwnd is None:
        return False
    hwnd = int(hwnd)
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    my_tid = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    attached_fg = False
    attached_tg = False
    try:
        if fg_tid and fg_tid != my_tid:
            attached_fg = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
        if target_tid and target_tid != my_tid and target_tid != fg_tid:
            attached_tg = bool(user32.AttachThreadInput(my_tid, target_tid, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
    finally:
        if attached_tg:
            user32.AttachThreadInput(my_tid, target_tid, False)
        if attached_fg:
            user32.AttachThreadInput(my_tid, fg_tid, False)
    time.sleep(0.08)
    return int(user32.GetForegroundWindow()) == hwnd


def open_inventory(keyboard: Optional[KeyboardController] = None) -> None:
    """Toggle inventory with Ctrl+I (must focus LC first — see focus_game)."""
    ensure_input()
    focus_game()
    keys = keyboard or KeyboardController()
    mod = "ctrlleft"
    try:
        keys.hold(mod)
    except Exception:
        mod = "ctrl"
        keys.hold(mod)
    time.sleep(0.04)
    try:
        keys.press("i", duration=0.05)
    finally:
        keys.release(mod)
    time.sleep(0.05)


def _type_quantity_engine_keyboard(
    text: str, keyboard: Optional[KeyboardController]
) -> dict[str, Any]:
    """Qty via Engine Interception (same capture as Shift-drag / Ctrl+I).

    This is the project-native injection path. enter_chat_cli uses a separate
    interception.dll context that often fails digit inject (EC_E_TEXT) while
    this path already owns a working keyboard device.
    """
    ensure_input()
    focused = focus_game()
    keys = keyboard or KeyboardController(humanize=False)
    sent_keys = 0
    failed = 0

    for _ in range(12):
        try:
            keys.press("backspace", duration=0.025)
            sent_keys += 1
        except Exception:
            failed += 1
            break
        time.sleep(0.012)
    time.sleep(0.05)

    for ch in text:
        try:
            keys.press(ch, duration=0.04)
            sent_keys += 1
        except Exception:
            failed += 1
        time.sleep(0.05)

    time.sleep(0.06)
    enter_ok = False
    try:
        keys.press("enter", duration=0.06)
        enter_ok = True
        sent_keys += 1
    except Exception:
        failed += 1

    ok = failed == 0 and enter_ok and bool(text)
    return {
        "ok": ok,
        "status": 0 if ok else 8,
        "status_name": "EC_OK" if ok else "ENGINE_KEY_FAIL",
        "method": "engine_keyboard",
        "chars": len(text) if failed == 0 else 0,
        "keys": sent_keys,
        "failed": failed,
        "enter": enter_ok,
        "focused": focused,
        "message": "" if ok else "engine keyboard inject failed",
    }


def type_quantity(
    qty: int,
    keyboard: Optional[KeyboardController] = None,
    *,
    return_payload: bool = False,
    raise_on_fail: bool = True,
) -> Optional[dict[str, Any]]:
    """Type digits then Enter into the LC qty prompt.

    Uses Engine Interception keyboard (proven with drag/hotkeys). Does not
    release the capture to spawn enter_chat — that competing context was the
    failure mode (EC_E_TEXT, chars=0).
    """
    text = str(max(0, int(qty)))
    if not text.isdigit():
        raise ValueError(f"qty must be digits, got {text!r}")

    payload = _type_quantity_engine_keyboard(text, keyboard)

    if raise_on_fail and not payload.get("ok"):
        raise RuntimeError(payload.get("message") or "type_quantity failed")
    if return_payload:
        return payload
    return None


def scroll_click(
    mouse: MouseController,
    xy: tuple[int, int],
    *,
    gap_s: float = 0.145,
    jitter_s: float = 0.030,
    rng: Optional[random.Random] = None,
) -> None:
    dice = rng or random.Random()
    mouse.click(float(xy[0]), float(xy[1]), snap=True)
    delay = max(0.05, float(gap_s) + dice.uniform(-float(jitter_s), float(jitter_s)))
    time.sleep(delay)


def _release_shift(keyboard: KeyboardController) -> None:
    for key in ("shiftleft", "shiftright", "shift"):
        try:
            keyboard.release(key)
        except Exception:
            pass


def select_bag_slot(
    mouse: MouseController,
    keyboard: KeyboardController,
    xy: tuple[int, int],
) -> None:
    """Plain click a bag slot (no Shift) so LC keeps only that item selected.

    Repeated Shift+drag otherwise accumulates multi-select highlights; clicking
    the next source without modifiers clears that sticky state first.
    """
    ensure_input()
    _release_shift(keyboard)
    time.sleep(0.03)
    mouse.click(float(xy[0]), float(xy[1]), snap=True)
    time.sleep(0.08)


def shift_drag(
    mouse: MouseController,
    keyboard: KeyboardController,
    src: tuple[int, int],
    dst: tuple[int, int],
    *,
    hold_s: float = 0.7,
    preselect: bool = True,
) -> None:
    """Hold Shift, drag left button from ``src`` to ``dst``, release after ``hold_s``.

    When ``preselect`` is True (default), first click ``src`` without Shift so
    the bag is not still in multi-select from the previous drop.
    """
    ensure_input()
    sx, sy = int(src[0]), int(src[1])
    dx, dy = int(dst[0]), int(dst[1])
    if preselect:
        select_bag_slot(mouse, keyboard, (sx, sy))
    _release_shift(keyboard)
    shift_key = "shiftleft"
    try:
        keyboard.hold(shift_key)
    except Exception:
        shift_key = "shift"
        keyboard.hold(shift_key)
    time.sleep(0.05)
    try:
        mouse.move(float(sx), float(sy), snap=True)
        time.sleep(0.04)
        mouse_mod._send_button("left", down=True, px=sx, py=sy)  # noqa: SLF001
        time.sleep(0.05)
        mouse.move(float(dx), float(dy), snap=False)
        time.sleep(max(0.05, float(hold_s)))
    finally:
        mouse_mod._send_button("left", down=False, px=dx, py=dy)  # noqa: SLF001
        time.sleep(0.12)
        _release_shift(keyboard)
        time.sleep(0.05)
