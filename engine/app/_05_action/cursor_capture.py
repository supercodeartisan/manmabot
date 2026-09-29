"""Win32 cursor rasterization (transparent BGRA)."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import numpy as np

if sys.platform != "win32":  # pragma: no cover
    def capture_cursor_bgra(size: int = 64) -> np.ndarray | None:
        return None

    def get_cursor_handle() -> int:
        return 0
else:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class CURSORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hCursor", wintypes.HANDLE),
            ("ptScreenPos", POINT),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
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

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    CURSOR_SHOWING = 0x00000001
    DI_NORMAL = 0x0003
    _CHROMA_BGR = (255, 0, 255)

    def get_cursor_handle() -> int:
        ci = CURSORINFO()
        ci.cbSize = ctypes.sizeof(CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(ci)):
            return 0
        if not (ci.flags & CURSOR_SHOWING):
            return 0
        return int(ci.hCursor or 0)

    def _crop_alpha_bbox(bgra: np.ndarray, pad: int = 1) -> np.ndarray:
        alpha = bgra[:, :, 3]
        ys, xs = np.where(alpha > 0)
        if len(xs) == 0:
            return bgra
        y0 = max(0, int(ys.min()) - pad)
        y1 = min(bgra.shape[0], int(ys.max()) + 1 + pad)
        x0 = max(0, int(xs.min()) - pad)
        x1 = min(bgra.shape[1], int(xs.max()) + 1 + pad)
        return bgra[y0:y1, x0:x1].copy()

    def capture_cursor_bgra(size: int = 64) -> np.ndarray | None:
        """Rasterize the OS cursor to BGRA (transparent outside the glyph)."""
        hcursor = get_cursor_handle()
        if not hcursor:
            return None

        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = size
        bmi.bmiHeader.biHeight = -size
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0

        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_screen,
            ctypes.byref(bmi),
            0,
            ctypes.byref(bits_ptr),
            None,
            0,
        )
        if not hbmp or not bits_ptr.value:
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            return None

        old = gdi32.SelectObject(hdc_mem, hbmp)
        brush = gdi32.CreateSolidBrush(0x00FF00FF)
        rect = wintypes.RECT(0, 0, size, size)
        user32.FillRect(hdc_mem, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

        copied = user32.CopyIcon(hcursor)
        ok = False
        if copied:
            ok = bool(
                user32.DrawIconEx(
                    hdc_mem, 0, 0, copied, size, size, 0, None, DI_NORMAL
                )
            )
            user32.DestroyIcon(copied)

        nbytes = size * size * 4
        raw = (ctypes.c_ubyte * nbytes).from_address(bits_ptr.value)
        bgra = np.frombuffer(raw, dtype=np.uint8).reshape(size, size, 4).copy()

        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        if not ok:
            return None

        b, g, r = _CHROMA_BGR
        if int(bgra[:, :, 3].max()) == 0:
            chroma = (
                (bgra[:, :, 0] == b)
                & (bgra[:, :, 1] == g)
                & (bgra[:, :, 2] == r)
            )
            bgra[:, :, 3] = np.where(chroma, 0, 255).astype(np.uint8)
            bgra[chroma, :3] = 0
        else:
            chroma = (
                (bgra[:, :, 0] == b)
                & (bgra[:, :, 1] == g)
                & (bgra[:, :, 2] == r)
            )
            bgra[chroma, 3] = 0
            bgra[chroma, :3] = 0

        return _crop_alpha_bbox(bgra)


__all__ = ["capture_cursor_bgra", "get_cursor_handle"]
