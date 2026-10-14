"""Small window shown until the real UI window is on screen.

Started from ``run.py`` before the compiled UI loads. A Win32 window is used
so the wait is visible before Qt is imported. The module name is not
``loader`` (that name aborts Nuitka on Python 3.14).
"""
from __future__ import annotations

import ctypes
import math
import os
import threading
from ctypes import wintypes

_CLASS = "ManmabotStartupSplash"
_WIDTH = 440
_HEIGHT = 200
_DOTS = 8
_MIN_UI_W = 480
_MIN_UI_H = 320

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)
_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
_user32.DefWindowProcW.restype = ctypes.c_ssize_t
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL

_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_PAINT = 0x000F
_WM_TIMER = 0x0113
_WS_POPUP = 0x80000000
_WS_VISIBLE = 0x10000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_DT_CENTER = 0x0001
_DT_VCENTER = 0x0004
_DT_SINGLELINE = 0x0020
_TRANSPARENT = 1

_proc_ref: object | None = None
_enum_ref: object | None = None
_brush = None
_title_font = None
_body_font = None
_frame = 0


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", wintypes.BYTE * 32),
    ]


def _ui_is_up(splash: wintypes.HWND) -> bool:
    found = False
    pid = os.getpid()

    def _visit(hwnd, _lparam):
        nonlocal found
        if hwnd == splash:
            return True
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) != pid or not _user32.IsWindowVisible(hwnd):
            return True
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width = int(rect.right) - int(rect.left)
        height = int(rect.bottom) - int(rect.top)
        if width >= _MIN_UI_W and height >= _MIN_UI_H:
            found = True
            return False
        return True

    global _enum_ref
    _enum_ref = _ENUM_PROC(_visit)
    _user32.EnumWindows(_enum_ref, 0)
    return found


def _fill_dot(hdc, x: int, y: int, radius: int, color: int) -> None:
    brush = _gdi32.CreateSolidBrush(color)
    pen = _gdi32.CreatePen(0, 1, color)
    old_brush = _gdi32.SelectObject(hdc, brush)
    old_pen = _gdi32.SelectObject(hdc, pen)
    _gdi32.Ellipse(hdc, x - radius, y - radius, x + radius, y + radius)
    _gdi32.SelectObject(hdc, old_brush)
    _gdi32.SelectObject(hdc, old_pen)
    _gdi32.DeleteObject(brush)
    _gdi32.DeleteObject(pen)


def _paint(hwnd) -> None:
    paint = _PAINTSTRUCT()
    hdc = _user32.BeginPaint(hwnd, ctypes.byref(paint))
    _gdi32.SetBkMode(hdc, _TRANSPARENT)
    _gdi32.SetTextColor(hdc, 0x00FFFFFF)
    cx = _WIDTH // 2
    cy = 52
    orbit = 18
    for index in range(_DOTS):
        angle = (index / _DOTS) * math.tau - (_frame / _DOTS) * math.tau
        age = (_frame - index) % _DOTS
        shade = 0x30 + int(((_DOTS - 1 - age) / (_DOTS - 1)) * 0xCF)
        color = shade | (shade << 8) | (shade << 16)
        radius = 5 if age == 0 else 3
        _fill_dot(
            hdc,
            int(cx + math.cos(angle) * orbit),
            int(cy + math.sin(angle) * orbit),
            radius,
            color,
        )
    title = wintypes.RECT(0, 88, _WIDTH, 132)
    body = wintypes.RECT(0, 132, _WIDTH, 176)
    _gdi32.SelectObject(hdc, _title_font)
    _user32.DrawTextW(hdc, "Manmabot", -1, ctypes.byref(title), _DT_CENTER | _DT_SINGLELINE | _DT_VCENTER)
    _gdi32.SelectObject(hdc, _body_font)
    _user32.DrawTextW(hdc, "Loading...", -1, ctypes.byref(body), _DT_CENTER | _DT_SINGLELINE | _DT_VCENTER)
    _user32.EndPaint(hwnd, ctypes.byref(paint))


def _wnd_proc(hwnd, msg, wparam, lparam):
    if msg == _WM_PAINT:
        _paint(hwnd)
        return 0
    if msg == _WM_TIMER:
        global _frame
        _frame = (_frame + 1) % _DOTS
        _user32.InvalidateRect(hwnd, None, True)
        if _ui_is_up(hwnd):
            _user32.KillTimer(hwnd, 1)
            _user32.DestroyWindow(hwnd)
        return 0
    if msg == _WM_CLOSE:
        _user32.DestroyWindow(hwnd)
        return 0
    if msg == _WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _run() -> None:
    global _proc_ref, _brush, _title_font, _body_font
    instance = _kernel32.GetModuleHandleW(None)
    _brush = _gdi32.CreateSolidBrush(0x00221C18)
    _title_font = _gdi32.CreateFontW(
        -28, 0, 0, 0, 600, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI"
    )
    _body_font = _gdi32.CreateFontW(
        -16, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI"
    )
    _proc_ref = _WNDPROC(_wnd_proc)
    klass = _WNDCLASSW()
    klass.lpfnWndProc = _proc_ref
    klass.hInstance = instance
    klass.hbrBackground = _brush
    klass.lpszClassName = _CLASS
    _user32.RegisterClassW(ctypes.byref(klass))
    screen_w = int(_user32.GetSystemMetrics(0))
    screen_h = int(_user32.GetSystemMetrics(1))
    hwnd = _user32.CreateWindowExW(
        _WS_EX_TOPMOST | _WS_EX_TOOLWINDOW,
        _CLASS,
        "Manmabot",
        _WS_POPUP | _WS_VISIBLE,
        (screen_w - _WIDTH) // 2,
        (screen_h - _HEIGHT) // 2,
        _WIDTH,
        _HEIGHT,
        None,
        None,
        instance,
        None,
    )
    if not hwnd:
        return
    _user32.SetTimer(hwnd, 1, 100, None)
    _user32.ShowWindow(hwnd, 5)
    _user32.UpdateWindow(hwnd)
    message = wintypes.MSG()
    while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        _user32.TranslateMessage(ctypes.byref(message))
        _user32.DispatchMessageW(ctypes.byref(message))


def open_until_main_window() -> None:
    """Show the loading window on a side thread until the main UI is visible."""
    if os.name != "nt":
        return
    threading.Thread(target=_run, name="startup-splash", daemon=True).start()
