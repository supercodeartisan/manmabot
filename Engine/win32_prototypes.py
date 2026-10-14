"""ctypes prototypes so 64-bit Win32 handles are not passed as c_int.

Untyped ``windll`` / ``WinDLL`` functions default to 32-bit ``c_int``
arguments. HCURSOR / HWND / HDC / HANDLE values from structures or
``restype=HANDLE`` then raise ``OverflowError: int too long to convert``.

``ctypes.windll.user32`` and ``WinDLL("user32", use_last_error=True)`` are
different DLL objects — bind each instance that you call.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_HDC = wintypes.HDC
_HWND = wintypes.HWND
_HANDLE = wintypes.HANDLE
_HICON = wintypes.HICON
_HGDIOBJ = wintypes.HGDIOBJ
_HBRUSH = getattr(wintypes, "HBRUSH", _HANDLE)
_HBITMAP = getattr(wintypes, "HBITMAP", _HANDLE)
_HINSTANCE = getattr(wintypes, "HINSTANCE", _HANDLE)
_HGLOBAL = getattr(wintypes, "HGLOBAL", _HANDLE)
_BOOL = wintypes.BOOL
_UINT = wintypes.UINT
_INT = ctypes.c_int
_DWORD = wintypes.DWORD
_UINT_PTR = getattr(wintypes, "WPARAM", ctypes.c_size_t)
_LONG_PTR = getattr(wintypes, "LPARAM", ctypes.c_ssize_t)
_ULONG_PTR = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)


def _proto(dll, name: str, restype, argtypes) -> None:
    try:
        fn = getattr(dll, name)
    except AttributeError:
        return
    fn.restype = restype
    fn.argtypes = list(argtypes)


def bind_user32(dll) -> None:
    _proto(dll, "GetCursorInfo", _BOOL, [ctypes.c_void_p])
    _proto(dll, "CopyIcon", _HICON, [_HICON])
    _proto(dll, "DestroyIcon", _BOOL, [_HICON])
    _proto(
        dll,
        "DrawIconEx",
        _BOOL,
        [_HDC, _INT, _INT, _HICON, _INT, _INT, _UINT, _HBRUSH, _UINT],
    )
    _proto(dll, "GetDC", _HDC, [_HWND])
    _proto(dll, "GetWindowDC", _HDC, [_HWND])
    _proto(dll, "ReleaseDC", _INT, [_HWND, _HDC])
    _proto(dll, "FillRect", _INT, [_HDC, ctypes.c_void_p, _HBRUSH])
    _proto(dll, "PrintWindow", _BOOL, [_HWND, _HDC, _UINT])
    _proto(dll, "GetCursorPos", _BOOL, [ctypes.POINTER(wintypes.POINT)])
    _proto(dll, "SetCursorPos", _BOOL, [_INT, _INT])
    _proto(dll, "GetSystemMetrics", _INT, [_INT])
    _proto(dll, "GetDpiForSystem", _UINT, [])
    _proto(dll, "SetProcessDPIAware", _BOOL, [])
    _proto(dll, "GetWindowTextLengthW", _INT, [_HWND])
    _proto(dll, "GetWindowTextW", _INT, [_HWND, wintypes.LPWSTR, _INT])
    _proto(dll, "GetClassNameW", _INT, [_HWND, wintypes.LPWSTR, _INT])
    _proto(dll, "IsWindowVisible", _BOOL, [_HWND])
    _proto(dll, "IsWindow", _BOOL, [_HWND])
    _proto(dll, "IsIconic", _BOOL, [_HWND])
    _proto(dll, "IsZoomed", _BOOL, [_HWND])
    _proto(
        dll,
        "GetWindowThreadProcessId",
        _DWORD,
        [_HWND, ctypes.POINTER(_DWORD)],
    )
    _proto(dll, "GetClientRect", _BOOL, [_HWND, ctypes.POINTER(wintypes.RECT)])
    _proto(dll, "GetWindowRect", _BOOL, [_HWND, ctypes.POINTER(wintypes.RECT)])
    _proto(dll, "ClientToScreen", _BOOL, [_HWND, ctypes.POINTER(wintypes.POINT)])
    _proto(dll, "GetForegroundWindow", _HWND, [])
    _proto(dll, "GetAncestor", _HWND, [_HWND, _UINT])
    _proto(dll, "AllowSetForegroundWindow", _BOOL, [_DWORD])
    _proto(dll, "ShowWindow", _BOOL, [_HWND, _INT])
    _proto(dll, "SetForegroundWindow", _BOOL, [_HWND])
    _proto(dll, "BringWindowToTop", _BOOL, [_HWND])
    _proto(dll, "SetActiveWindow", _HWND, [_HWND])
    _proto(
        dll,
        "SetWindowPos",
        _BOOL,
        [_HWND, _HWND, _INT, _INT, _INT, _INT, _UINT],
    )
    _proto(dll, "AttachThreadInput", _BOOL, [_DWORD, _DWORD, _BOOL])
    _proto(
        dll,
        "SystemParametersInfoW",
        _BOOL,
        [_UINT, _UINT, ctypes.c_void_p, _UINT],
    )
    _proto(dll, "PostMessageW", _BOOL, [_HWND, _UINT, _UINT_PTR, _LONG_PTR])
    _proto(dll, "WindowFromPoint", _HWND, [wintypes.POINT])
    _proto(dll, "OpenClipboard", _BOOL, [_HWND])
    _proto(dll, "EmptyClipboard", _BOOL, [])
    _proto(dll, "CloseClipboard", _BOOL, [])
    _proto(dll, "SetClipboardData", _HANDLE, [_UINT, _HANDLE])
    _proto(dll, "GetClipboardData", _HANDLE, [_UINT])
    _proto(dll, "keybd_event", None, [ctypes.c_ubyte, ctypes.c_ubyte, _DWORD, _ULONG_PTR])
    _proto(dll, "mouse_event", None, [_DWORD, _DWORD, _DWORD, _DWORD, _ULONG_PTR])


def bind_gdi32(dll) -> None:
    _proto(dll, "CreateCompatibleDC", _HDC, [_HDC])
    _proto(dll, "DeleteDC", _BOOL, [_HDC])
    _proto(dll, "SelectObject", _HGDIOBJ, [_HDC, _HGDIOBJ])
    _proto(dll, "DeleteObject", _BOOL, [_HGDIOBJ])
    _proto(dll, "CreateSolidBrush", _HBRUSH, [wintypes.COLORREF])
    _proto(
        dll,
        "CreateDIBSection",
        _HBITMAP,
        [_HDC, ctypes.c_void_p, _UINT, ctypes.c_void_p, _HANDLE, _DWORD],
    )
    _proto(dll, "CreateCompatibleBitmap", _HBITMAP, [_HDC, _INT, _INT])
    _proto(
        dll,
        "BitBlt",
        _BOOL,
        [_HDC, _INT, _INT, _INT, _INT, _HDC, _INT, _INT, _DWORD],
    )
    _proto(
        dll,
        "GetDIBits",
        _INT,
        [_HDC, _HBITMAP, _UINT, _UINT, ctypes.c_void_p, ctypes.c_void_p, _UINT],
    )
    _proto(dll, "GetDeviceCaps", _INT, [_HDC, _INT])


def bind_kernel32(dll) -> None:
    _proto(dll, "OpenProcess", _HANDLE, [_DWORD, _BOOL, _DWORD])
    _proto(dll, "CloseHandle", _BOOL, [_HANDLE])
    _proto(dll, "GetExitCodeProcess", _BOOL, [_HANDLE, ctypes.POINTER(_DWORD)])
    _proto(dll, "TerminateProcess", _BOOL, [_HANDLE, _UINT])
    _proto(
        dll,
        "QueryFullProcessImageNameW",
        _BOOL,
        [_HANDLE, _DWORD, wintypes.LPWSTR, ctypes.POINTER(_DWORD)],
    )
    _proto(dll, "GetCurrentThreadId", _DWORD, [])
    _proto(dll, "LocalFree", ctypes.c_void_p, [ctypes.c_void_p])
    _proto(dll, "GlobalAlloc", _HGLOBAL, [_UINT, ctypes.c_size_t])
    _proto(dll, "GlobalLock", ctypes.c_void_p, [_HGLOBAL])
    _proto(dll, "GlobalUnlock", _BOOL, [_HGLOBAL])
    _proto(dll, "GlobalFree", _HGLOBAL, [_HGLOBAL])


def bind_shell32(dll) -> None:
    _proto(dll, "IsUserAnAdmin", _BOOL, [])
    _proto(
        dll,
        "ShellExecuteW",
        _HINSTANCE,
        [_HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, _INT],
    )
    _proto(dll, "ShellExecuteExW", _BOOL, [ctypes.c_void_p])


def bind_crypt32(dll) -> None:
    _proto(
        dll,
        "CryptProtectData",
        _BOOL,
        [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            _DWORD,
            ctypes.c_void_p,
        ],
    )
    _proto(
        dll,
        "CryptUnprotectData",
        _BOOL,
        [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            _DWORD,
            ctypes.c_void_p,
        ],
    )


def bind_shcore(dll) -> None:
    # restype must not be HRESULT: ctypes then raises on E_ACCESSDENIED
    # (already DPI-aware / UIPI). dxcam calls this at import time.
    _proto(dll, "SetProcessDpiAwareness", ctypes.c_long, [_INT])


def bind_all(
    *,
    user32=None,
    gdi32=None,
    kernel32=None,
    shell32=None,
    crypt32=None,
    shcore=None,
) -> None:
    """Bind the given DLL objects, or the cached ``ctypes.windll`` copies."""
    if sys.platform != "win32":
        return
    bind_user32(user32 if user32 is not None else ctypes.windll.user32)
    bind_gdi32(gdi32 if gdi32 is not None else ctypes.windll.gdi32)
    bind_kernel32(kernel32 if kernel32 is not None else ctypes.windll.kernel32)
    bind_shell32(shell32 if shell32 is not None else ctypes.windll.shell32)
    bind_crypt32(crypt32 if crypt32 is not None else ctypes.windll.crypt32)
    try:
        bind_shcore(shcore if shcore is not None else ctypes.windll.shcore)
    except (AttributeError, OSError):
        pass


if sys.platform == "win32":
    bind_all()
