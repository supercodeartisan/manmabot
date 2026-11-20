"""Purple actions — the "hands".

Everything here operates on elements discovered *live* in the current UIA
tree and clicks/types at their current rectangle centers. No stored
coordinate, resized shell, or template is used. Input is sent with real
mouse/keyboard events (CEF ignores UIA InvokePattern for these controls).
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_unicode(text: str) -> None:
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    inputs = []
    for ch in text:
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inputs.append(_INPUT(type=1, u=_INPUTUNION(
                ki=_KEYBDINPUT(0, ord(ch), flags, 0, None))))
    arr = (_INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
    time.sleep(0.2)


def _activate(hwnd: int) -> None:
    if win32gui.GetForegroundWindow() == hwnd:
        return
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    except Exception:
        pass
    fg = win32gui.GetForegroundWindow()
    cur = win32api.GetCurrentThreadId()
    fg_tid = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
    tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
    try:
        if fg_tid and fg_tid != cur:
            win32process.AttachThreadInput(cur, fg_tid, True)
        if tgt_tid and tgt_tid != cur:
            win32process.AttachThreadInput(cur, tgt_tid, True)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    finally:
        for tid in (fg_tid, tgt_tid):
            try:
                if tid and tid != cur:
                    win32process.AttachThreadInput(cur, tid, False)
            except Exception:
                pass
    time.sleep(0.25)


def _screen_bounds() -> tuple[int, int, int, int]:
    x = win32api.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    y = win32api.GetSystemMetrics(77)
    w = win32api.GetSystemMetrics(78)
    h = win32api.GetSystemMetrics(79)
    return x, y, x + w, y + h


def _on_screen(x: int, y: int) -> bool:
    sx, sy, ex, ey = _screen_bounds()
    # Clamp to inside the screen (avoid the (0,0)//edge cases and the
    # Interception absolute-coordinate quirk that maps an edge point
    # incorrectly). Never send exactly on the boundary.
    cx = max(sx + 1, min(x, ex - 1))
    cy = max(sy + 1, min(y, ey - 1))
    return cx, cy


def _click_xy(x: int, y: int) -> bool:
    """Click via the Interception driver at screen pixels (x, y).

    Interception is device-level (works under UIPI/foreground lock, immune
    to the SetCursorPos/foreground quirks that freeze the Win32 path). If it
    is unavailable, fall back to Win32. Returns True when a click landed.
    """
    clamped = _on_screen(int(x), int(y))
    if clamped is False:
        return False
    cx, cy = clamped
    try:
        from win import interception
        if interception.init() and interception.click(cx, cy):
            time.sleep(0.2)
            return True
    except Exception:
        pass
    # Win32 fallback (only when Interception is absent/failed).
    try:
        win32api.SetCursorPos((cx, cy))
        time.sleep(0.1)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.25)
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "click failed at (%d,%d): %r", cx, cy, e)
        return False


def click_node(hwnd: int, node: dict, label: str = "") -> bool:
    """Click the *current* center of a live-discovered element.

    Returns False (and does nothing) when the element is off-screen, so the
    engine never triggers SetCursorPos on a bad coordinate.
    """
    center = node.get("center") or node.get("rel_center")
    if not center:
        raise RuntimeError("node has no center for %s" % label)
    clamped = _on_screen(center[0], center[1])
    if clamped is False:
        return False
    _activate(hwnd)
    return _click_xy(clamped[0], clamped[1])


def type_into(hwnd: int, node: dict, text: str, label: str = "") -> bool:
    """Focus a live element and type text via SendInput (UNICODE)."""
    center = node.get("center") or node.get("rel_center")
    if not center:
        raise RuntimeError("node has no center for %s" % label)
    clamped = _on_screen(center[0], center[1])
    if clamped is False:
        return False
    _activate(hwnd)
    if not _click_xy(clamped[0], clamped[1]):
        return False
    time.sleep(0.15)
    # select-all then type (requests a clean field)
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    win32api.keybd_event(ord("A"), 0, 0, 0)
    win32api.keybd_event(ord("A"), 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.12)
    _send_unicode(text)
    return True
