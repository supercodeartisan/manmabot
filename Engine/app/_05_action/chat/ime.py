"""Game window IME mode: hold the Korean IME in English for one key press.

In 한글 mode the Y key becomes the jamo ``ㅛ`` (an IME composition), so the
invite popup never sees Y. Same channel as enter_chat's ``ec_hangul``: the
game thread's default IME window with ``WM_IME_CONTROL`` (cross-process
``ImmGetContext`` usually fails).
"""
from __future__ import annotations

import ctypes
import time
from contextlib import contextmanager
from ctypes import wintypes
from typing import Iterator, Optional

WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_SETCONVERSIONMODE = 0x0002
IME_CMODE_NATIVE = 0x0001
_SMTO = 0x0001 | 0x0002  # SMTO_BLOCK | SMTO_ABORTIFHUNG
_TIMEOUT_MS = 400

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_imm32 = ctypes.WinDLL("imm32", use_last_error=True)

_imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]
_imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
_user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
_user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t


def _ime_window(hwnd: int) -> Optional[int]:
    try:
        ime = _imm32.ImmGetDefaultIMEWnd(wintypes.HWND(int(hwnd)))
    except Exception:
        return None
    return int(ime) if ime else None


def _control(ime: int, cmd: int, value: int = 0) -> Optional[int]:
    out = ctypes.c_size_t(0)
    ok = _user32.SendMessageTimeoutW(
        wintypes.HWND(ime), WM_IME_CONTROL, cmd, value, _SMTO, _TIMEOUT_MS, ctypes.byref(out)
    )
    return int(out.value) if ok else None


def conversion_mode(hwnd: int) -> Optional[int]:
    """IME conversion mode of the game thread, None when it cannot be read."""
    ime = _ime_window(hwnd)
    return _control(ime, IMC_GETCONVERSIONMODE) if ime else None


@contextmanager
def english_ime(hwnd: int, *, settle_s: float = 0.05) -> Iterator[str]:
    """Clear 한글 mode for the block, restore it after. Yields what was done:
    ``english`` (already), ``switched``, ``switch_failed`` or ``unknown``."""
    ime = _ime_window(hwnd)
    mode = _control(ime, IMC_GETCONVERSIONMODE) if ime else None
    if mode is None:
        yield "unknown"
        return
    if not mode & IME_CMODE_NATIVE:
        yield "english"
        return
    _control(ime, IMC_SETCONVERSIONMODE, mode & ~IME_CMODE_NATIVE)
    time.sleep(settle_s)
    now = _control(ime, IMC_GETCONVERSIONMODE)
    try:
        yield "switched" if now is not None and not now & IME_CMODE_NATIVE else "switch_failed"
    finally:
        _control(ime, IMC_SETCONVERSIONMODE, mode)


__all__ = ["IME_CMODE_NATIVE", "conversion_mode", "english_ime"]
