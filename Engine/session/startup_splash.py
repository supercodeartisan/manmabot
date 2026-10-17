"""Floating loading card shown until the operator console has painted.

``run_entry`` opens this only after the UAC prompt has been answered. The
card is a layered window: one premultiplied frame is presented at a time,
so the spinner does not blink. The module name is not ``loader`` (that name
aborts Nuitka on Python 3.14).
"""
from __future__ import annotations

import ctypes
import math
import os
import threading
import traceback
from ctypes import wintypes

_CLASS = "ZFStartupSplash"
_BRAND_MARK = "纵锋"
_WIDTH = 400
_HEIGHT = 460
_MIN_UI_W = 480
_MIN_UI_H = 320
_FALLBACK_HITS = 8

_PIX_PARGB = 0x000E200B
_UNIT_PX = 2
_SMOOTH = 4
_QUALITY = 2
_TEXT_AA = 3
_INTERP = 7
_AC_SRC_ALPHA = 1
_ULW_ALPHA = 2
_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_TIMER = 0x0113
_WM_ERASEBKGND = 0x0014

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_gdiplus = ctypes.WinDLL("gdiplus", use_last_error=True)

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
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC,
    ctypes.POINTER(wintypes.POINT),
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_user32.UpdateLayeredWindow.restype = wintypes.BOOL
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_user32.ReleaseDC.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
_user32.SetTimer.restype = ctypes.c_size_t
_user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
_user32.LoadCursorW.restype = wintypes.HANDLE
_gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.c_void_p,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
_gdi32.CreateDIBSection.restype = wintypes.HBITMAP
_gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi32.CreateCompatibleDC.restype = wintypes.HDC
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_kernel32.GetTickCount.restype = wintypes.DWORD
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetUserDefaultUILanguage.restype = wintypes.WORD

_proc_ref: object | None = None
_enum_ref: object | None = None
_started = False
_hwnd = 0
_closing = False
_born = 0
_alpha = 0
_ui_hits = 0
_tick = 0
_loading_text = "正在加载"
_logo = ctypes.c_void_p()
_gdiplus_token = ctypes.c_ulong()
_bitmap = ctypes.c_void_p()
_graphics = ctypes.c_void_p()
_mem_dc = None
_dib = None
_old_bmp = None
_title_font = ctypes.c_void_p()
_body_font = ctypes.c_void_p()
_title_family = ctypes.c_void_p()
_body_family = ctypes.c_void_p()
_format = ctypes.c_void_p()


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


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class _GdiplusStartupInput(ctypes.Structure):
    _fields_ = [
        ("GdiplusVersion", ctypes.c_uint32),
        ("DebugEventCallback", ctypes.c_void_p),
        ("SuppressBackgroundThread", ctypes.c_int),
        ("SuppressExternalCodecs", ctypes.c_int),
    ]


class _RectF(ctypes.Structure):
    _fields_ = [
        ("X", ctypes.c_float),
        ("Y", ctypes.c_float),
        ("Width", ctypes.c_float),
        ("Height", ctypes.c_float),
    ]


def _argb(alpha: int, red: int, green: int, blue: int) -> int:
    return ((alpha & 255) << 24) | ((red & 255) << 16) | ((green & 255) << 8) | (blue & 255)


def _gp(name: str, restype, argtypes) -> None:
    fn = getattr(_gdiplus, name)
    fn.restype = restype
    fn.argtypes = argtypes


def _bind_gdiplus() -> None:
    _gp("GdiplusStartup", ctypes.c_int, [
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(_GdiplusStartupInput), ctypes.c_void_p,
    ])
    _gp("GdipLoadImageFromFile", ctypes.c_int, [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)])
    _gp("GdipCreateBitmapFromScan0", ctypes.c_int, [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ])
    _gp("GdipGetImageGraphicsContext", ctypes.c_int, [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ])
    _gp("GdipGraphicsClear", ctypes.c_int, [ctypes.c_void_p, ctypes.c_uint])
    _gp("GdipSetSmoothingMode", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipSetCompositingQuality", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipSetInterpolationMode", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipSetTextRenderingHint", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipSetPixelOffsetMode", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipCreatePath", ctypes.c_int, [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)])
    _gp("GdipAddPathArc", ctypes.c_int, [
        ctypes.c_void_p, ctypes.c_float, ctypes.c_float, ctypes.c_float, ctypes.c_float,
        ctypes.c_float, ctypes.c_float,
    ])
    _gp("GdipClosePathFigure", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDeletePath", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipCreateSolidFill", ctypes.c_int, [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)])
    _gp("GdipFillPath", ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p])
    _gp("GdipDeleteBrush", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipSetClipPath", ctypes.c_int, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int])
    _gp("GdipResetClip", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDrawImageRect", ctypes.c_int, [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float, ctypes.c_float,
        ctypes.c_float, ctypes.c_float,
    ])
    _gp("GdipCreateFontFamilyFromName", ctypes.c_int, [
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ])
    _gp("GdipCreateFont", ctypes.c_int, [
        ctypes.c_void_p, ctypes.c_float, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ])
    _gp("GdipCreateStringFormat", ctypes.c_int, [
        ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ])
    _gp("GdipSetStringFormatAlign", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipSetStringFormatLineAlign", ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    _gp("GdipDrawString", ctypes.c_int, [
        ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p,
        ctypes.POINTER(_RectF), ctypes.c_void_p, ctypes.c_void_p,
    ])
    _gp("GdipDeleteFont", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDeleteFontFamily", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDeleteStringFormat", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDeleteGraphics", ctypes.c_int, [ctypes.c_void_p])
    _gp("GdipDisposeImage", ctypes.c_int, [ctypes.c_void_p])


def _round_path(x: float, y: float, w: float, h: float, radius: float):
    path = ctypes.c_void_p()
    if _gdiplus.GdipCreatePath(0, ctypes.byref(path)) != 0 or not path:
        return None
    diameter = radius * 2.0
    _gdiplus.GdipAddPathArc(path, x, y, diameter, diameter, 180.0, 90.0)
    _gdiplus.GdipAddPathArc(path, x + w - diameter, y, diameter, diameter, 270.0, 90.0)
    _gdiplus.GdipAddPathArc(path, x + w - diameter, y + h - diameter, diameter, diameter, 0.0, 90.0)
    _gdiplus.GdipAddPathArc(path, x, y + h - diameter, diameter, diameter, 90.0, 90.0)
    _gdiplus.GdipClosePathFigure(path)
    return path


def _fill_round(x: float, y: float, w: float, h: float, radius: float, color: int) -> None:
    path = _round_path(x, y, w, h, radius)
    brush = ctypes.c_void_p()
    if path is None or _gdiplus.GdipCreateSolidFill(color, ctypes.byref(brush)) != 0:
        if path:
            _gdiplus.GdipDeletePath(path)
        return
    _gdiplus.GdipFillPath(_graphics, brush, path)
    _gdiplus.GdipDeleteBrush(brush)
    _gdiplus.GdipDeletePath(path)


def _startup_gdiplus() -> bool:
    startup = _GdiplusStartupInput(1, None, 0, 0)
    return _gdiplus.GdiplusStartup(ctypes.byref(_gdiplus_token), ctypes.byref(startup), None) == 0


def _load_logo() -> None:
    global _logo
    try:
        from session.paths import data_root

        path = data_root() / "logo.png"
        if not path.is_file():
            return
    except Exception:
        return
    image = ctypes.c_void_p()
    if _gdiplus.GdipLoadImageFromFile(str(path), ctypes.byref(image)) == 0 and image:
        _logo = image


def _make_font(
    family_name: str,
    size: float,
    style: int,
    slot: str,
    *,
    fallback: str = "Segoe UI",
) -> None:
    family = ctypes.c_void_p()
    font = ctypes.c_void_p()
    if _gdiplus.GdipCreateFontFamilyFromName(family_name, None, ctypes.byref(family)) != 0:
        if not fallback or _gdiplus.GdipCreateFontFamilyFromName(
            fallback, None, ctypes.byref(family)
        ) != 0:
            return
    if _gdiplus.GdipCreateFont(family, size, style, _UNIT_PX, ctypes.byref(font)) != 0:
        _gdiplus.GdipDeleteFontFamily(family)
        return
    if slot == "title":
        global _title_family, _title_font
        _title_family = family
        _title_font = font
    else:
        global _body_family, _body_font
        _body_family = family
        _body_font = font


def _create_surface() -> bool:
    global _mem_dc, _dib, _bitmap, _graphics, _format
    info = _BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    info.biWidth = _WIDTH
    info.biHeight = -_HEIGHT
    info.biPlanes = 1
    info.biBitCount = 32
    info.biCompression = 0
    bits = ctypes.c_void_p()
    screen = _user32.GetDC(None)
    _dib = _gdi32.CreateDIBSection(screen, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    _mem_dc = _gdi32.CreateCompatibleDC(screen)
    _user32.ReleaseDC(None, screen)
    if not _dib or not _mem_dc or not bits:
        return False
    global _old_bmp
    _old_bmp = _gdi32.SelectObject(_mem_dc, _dib)
    if _gdiplus.GdipCreateBitmapFromScan0(
        _WIDTH, _HEIGHT, _WIDTH * 4, _PIX_PARGB, bits, ctypes.byref(_bitmap)
    ) != 0:
        return False
    if _gdiplus.GdipGetImageGraphicsContext(_bitmap, ctypes.byref(_graphics)) != 0:
        return False
    _gdiplus.GdipSetSmoothingMode(_graphics, _SMOOTH)
    _gdiplus.GdipSetCompositingQuality(_graphics, _QUALITY)
    _gdiplus.GdipSetInterpolationMode(_graphics, _INTERP)
    _gdiplus.GdipSetTextRenderingHint(_graphics, _TEXT_AA)
    _gdiplus.GdipSetPixelOffsetMode(_graphics, 4)
    if _gdiplus.GdipCreateStringFormat(0, 0, ctypes.byref(_format)) == 0 and _format:
        _gdiplus.GdipSetStringFormatAlign(_format, 1)
        _gdiplus.GdipSetStringFormatLineAlign(_format, 1)
    return True


def _draw_text(text: str, font, x: float, y: float, w: float, h: float, color: int) -> None:
    if not font or not _format:
        return
    brush = ctypes.c_void_p()
    if _gdiplus.GdipCreateSolidFill(color, ctypes.byref(brush)) != 0:
        return
    rect = _RectF(x, y, w, h)
    _gdiplus.GdipDrawString(_graphics, text, -1, font, ctypes.byref(rect), _format, brush)
    _gdiplus.GdipDeleteBrush(brush)


def _draw_frame(now_ms: int) -> None:
    _gdiplus.GdipGraphicsClear(_graphics, _argb(0, 0, 0, 0))
    card_x, card_y, card_w, card_h = 36.0, 28.0, 328.0, 400.0
    for shift, alpha in ((14, 16), (8, 24), (4, 34)):
        _fill_round(card_x, card_y + shift, card_w, card_h, 28.0, _argb(alpha, 31, 35, 40))
    _fill_round(card_x, card_y, card_w, card_h, 28.0, _argb(255, 255, 255, 255))

    logo = 120.0
    logo_x = card_x + (card_w - logo) / 2.0
    logo_y = card_y + 36.0
    if _logo:
        clip = _round_path(logo_x, logo_y, logo, logo, 22.0)
        if clip:
            _gdiplus.GdipSetClipPath(_graphics, clip, 0)
            _gdiplus.GdipDrawImageRect(_graphics, _logo, logo_x, logo_y, logo, logo)
            _gdiplus.GdipResetClip(_graphics)
            _gdiplus.GdipDeletePath(clip)

    _draw_text(
        _BRAND_MARK, _title_font, card_x, logo_y + logo + 6.0, card_w, 42.0, _argb(255, 31, 35, 40)
    )
    _draw_text(
        _loading_text, _body_font, card_x, logo_y + logo + 48.0, card_w, 22.0, _argb(255, 107, 114, 128)
    )

    track_w, track_h = 148.0, 3.0
    track_x = card_x + (card_w - track_w) / 2.0
    track_y = card_y + card_h - 42.0
    _fill_round(track_x, track_y, track_w, track_h, track_h, _argb(255, 232, 241, 254))
    phase = 0.5 - 0.5 * math.cos((now_ms - _born) / 420.0)
    span = 52.0
    glide = track_x + (track_w - span) * phase
    _fill_round(glide, track_y, span, track_h, track_h, _argb(255, 58, 130, 246))


def _present(now_ms: int) -> None:
    global _alpha
    if not _hwnd or not _graphics:
        return
    if _closing:
        _alpha = max(0, _alpha - 22)
    else:
        _alpha = min(255, _alpha + 18)
    _draw_frame(now_ms)
    origin = wintypes.POINT(0, 0)
    size = wintypes.SIZE(_WIDTH, _HEIGHT)
    dest = wintypes.POINT(
        (int(_user32.GetSystemMetrics(0)) - _WIDTH) // 2,
        (int(_user32.GetSystemMetrics(1)) - _HEIGHT) // 2,
    )
    blend = _BLENDFUNCTION(0, 0, max(0, min(255, _alpha)), _AC_SRC_ALPHA)
    _user32.UpdateLayeredWindow(
        _hwnd, None, ctypes.byref(dest), ctypes.byref(size),
        _mem_dc, ctypes.byref(origin), 0, ctypes.byref(blend), _ULW_ALPHA,
    )


def _ui_is_up(splash: int) -> bool:
    found = False
    pid = os.getpid()

    def _visit(hwnd, _lparam):
        nonlocal found
        if int(hwnd) == int(splash):
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


def _wnd_proc(hwnd, msg, wparam, lparam):
    global _closing, _ui_hits, _tick
    if msg == _WM_ERASEBKGND:
        return 1
    if msg == _WM_TIMER:
        now = int(_kernel32.GetTickCount() or 0)
        _tick += 1
        if _closing and _alpha <= 0:
            _user32.KillTimer(hwnd, 1)
            _user32.DestroyWindow(hwnd)
            return 0
        if not _closing and _tick % 6 == 0 and _ui_is_up(int(hwnd)):
            _ui_hits += 1
            if _ui_hits >= _FALLBACK_HITS:
                _closing = True
        else:
            if not _closing:
                _ui_hits = 0 if _tick % 6 == 0 else _ui_hits
        _present(now)
        return 0
    if msg == _WM_CLOSE:
        _closing = True
        return 0
    if msg == _WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _run() -> None:
    global _proc_ref, _hwnd, _born, _loading_text
    _bind_gdiplus()
    if not _startup_gdiplus():
        return
    _loading_text = "正在加载"
    _load_logo()
    for face_name in ("Microsoft YaHei", "SimSun", "DengXian", "Microsoft JhengHei"):
        _make_font(face_name, 30.0, 1, "title", fallback="")
        if _title_font.value:
            break
    if not _title_font.value:
        _make_font("Segoe UI", 30.0, 1, "title")
    for face_name in ("Microsoft YaHei", "SimSun", "DengXian", "Microsoft JhengHei"):
        _make_font(face_name, 13.0, 0, "body", fallback="")
        if _body_font.value:
            break
    if not _body_font.value:
        _make_font("Segoe UI", 13.0, 0, "body")
    if not _create_surface():
        return
    instance = _kernel32.GetModuleHandleW(None)
    _proc_ref = _WNDPROC(_wnd_proc)
    klass = _WNDCLASSW()
    klass.lpfnWndProc = _proc_ref
    klass.hInstance = instance
    klass.hCursor = _user32.LoadCursorW(None, ctypes.c_void_p(32512))
    klass.lpszClassName = _CLASS
    _user32.RegisterClassW(ctypes.byref(klass))
    _born = int(_kernel32.GetTickCount() or 0)
    _hwnd = _user32.CreateWindowExW(
        _WS_EX_LAYERED | _WS_EX_TOPMOST | _WS_EX_TOOLWINDOW,
        _CLASS,
        _BRAND_MARK,
        _WS_POPUP,
        0,
        0,
        _WIDTH,
        _HEIGHT,
        None,
        None,
        instance,
        None,
    )
    if not _hwnd:
        return
    _present(_born)
    _user32.ShowWindow(_hwnd, 8)
    _user32.SetTimer(_hwnd, 1, 16, None)
    message = wintypes.MSG()
    while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        _user32.TranslateMessage(ctypes.byref(message))
        _user32.DispatchMessageW(ctypes.byref(message))


def open_until_main_window() -> None:
    """Show the loading window until the main UI has painted."""
    global _started
    if os.name != "nt" or _started:
        return
    _started = True
    threading.Thread(target=_run_guarded, name="startup-splash", daemon=True).start()


def _run_guarded() -> None:
    try:
        _run()
    except Exception:
        traceback.print_exc()


def close_startup_splash() -> None:
    """Fade the loading window out. Safe when it was never opened."""
    if os.name != "nt":
        return
    hwnd = _user32.FindWindowW(_CLASS, None)
    if hwnd:
        _user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
