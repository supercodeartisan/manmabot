"""Put LC in front before party chat keys; drop this process's always-on-top.

The admin ``enter_chat`` CLI is a fresh elevated process, so Windows lets it
take the foreground. The long-running bot does not: Qt always-on-top and the
shell stay in front, and Interception types into the wrong window while
``enter_chat`` still logs ``typed``.
"""
from __future__ import annotations

import ctypes
import os
import time
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator, List

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

# After topmost drop + SetForegroundWindow, give the game a beat before keys.
FOCUS_SETTLE_S = 0.2


def _user32():
    return ctypes.windll.user32


def clear_process_topmost() -> List[int]:
    """Clear ``WS_EX_TOPMOST`` on visible windows of this process. Returns hwnds."""
    user32 = _user32()
    pid = os.getpid()
    found: List[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lparam: int) -> bool:
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if int(wpid.value) != pid:
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        try:
            get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            style = int(get_long(hwnd, GWL_EXSTYLE))
        except Exception:
            return True
        if style & WS_EX_TOPMOST:
            found.append(int(hwnd))
            user32.SetWindowPos(
                hwnd,
                HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        return True

    user32.EnumWindows(_enum, 0)
    return found


def restore_process_topmost(hwnds: List[int]) -> None:
    user32 = _user32()
    for hwnd in hwnds:
        if not hwnd or not user32.IsWindow(hwnd):
            continue
        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )


def focus_game_hwnd(hwnd: int) -> None:
    if not hwnd:
        return
    try:
        from session.probes import bring_game_to_front

        bring_game_to_front(int(hwnd))
        return
    except Exception:
        pass
    user32 = _user32()
    try:
        user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    user32.ShowWindow(int(hwnd), 9)
    user32.SetForegroundWindow(int(hwnd))
    try:
        user32.BringWindowToTop(int(hwnd))
    except Exception:
        pass


@contextmanager
def prepare_game_chat_focus(hwnd: int) -> Iterator[None]:
    """Drop bot always-on-top, focus LC, then restore topmost after the keys."""
    cleared = clear_process_topmost()
    try:
        focus_game_hwnd(int(hwnd))
        time.sleep(FOCUS_SETTLE_S)
        yield
    finally:
        restore_process_topmost(cleared)


__all__ = [
    "FOCUS_SETTLE_S",
    "clear_process_topmost",
    "focus_game_hwnd",
    "prepare_game_chat_focus",
    "restore_process_topmost",
]
