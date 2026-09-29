"""Restore real mouse/keyboard after Interception login or farm input."""
from __future__ import annotations

import ctypes
import sys
from typing import Optional


_KEYEVENTF_KEYUP = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEUP = 0x0040
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010

# Left/right Alt, Ctrl, Shift, Win.
_STUCK_VKS = (0x12, 0xA4, 0xA5, 0x11, 0xA2, 0xA3, 0x10, 0xA0, 0xA1, 0x5B, 0x5C)


def release_stuck_modifiers() -> None:
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        for vk in _STUCK_VKS:
            user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def release_mouse_buttons() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.mouse_event(
            _MOUSEEVENTF_LEFTUP | _MOUSEEVENTF_RIGHTUP | _MOUSEEVENTF_MIDDLEUP,
            0, 0, 0, 0,
        )
    except Exception:
        pass


def drop_game_topmost(hwnd: Optional[int] = None) -> None:
    if sys.platform != "win32":
        return
    handle = int(hwnd or 0)
    if handle <= 0:
        try:
            from manmabot_v1.probes import probe_game

            game = probe_game("LC.exe")
            handle = int(getattr(game, "hwnd", 0) or 0)
        except Exception:
            handle = 0
    if handle <= 0:
        return
    try:
        ctypes.windll.user32.SetWindowPos(
            handle, _HWND_NOTOPMOST, 0, 0, 0, 0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
        )
    except Exception:
        pass


def restore_desktop_input(*, hwnd: Optional[int] = None) -> None:
    """Undo leftover TOPMOST / held keys so the desktop is usable again."""
    drop_game_topmost(hwnd)
    release_stuck_modifiers()
    release_mouse_buttons()
