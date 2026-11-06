# -*- coding: utf-8 -*-
"""
control.pointer — 마우스 포인터 '가속' 제어 (정확한 이동용)

  Windows: SPI_GETMOUSE / SPI_SETMOUSE 로 '포인터 정밀도 향상' on/off
  Linux  : xset m (있으면) — 없으면 no-op

  with no_pointer_accel():
      ... 정확한 상대이동 ...

  * 가속이 켜져 있으면 상대 이동이 비선형(예: +100 → +150~+248)이라
    절대 위치가 매번 달라진다. 가속을 끄면 1:1 로 정확해진다.
"""

import contextlib
import subprocess
import sys

_SPI_GETMOUSE = 0x0003
_SPI_SETMOUSE = 0x0004
_SPIF_SENDCHANGE = 0x02


def _user32():
    if not sys.platform.startswith("win"):
        return None
    import ctypes
    return ctypes.windll.user32


def get_windows_accel():
    u = _user32()
    if u is None:
        return None
    import ctypes
    arr = (ctypes.c_int * 3)()
    u.SystemParametersInfoW(_SPI_GETMOUSE, 0, arr, 0)
    return (arr[0], arr[1], arr[2])


def set_windows_accel(v):
    u = _user32()
    if u is None:
        return False
    import ctypes
    u.SystemParametersInfoW(_SPI_SETMOUSE, 0, (ctypes.c_int * 3)(*v), _SPIF_SENDCHANGE)
    return True


def _xset(enable):
    try:
        subprocess.run(["xset", "m", "1" if enable else "0", "0"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


@contextlib.contextmanager
def no_pointer_accel():
    """컨텍스트 동안 포인터 가속을 끈다(끝나면 복원)."""
    if sys.platform.startswith("win"):
        saved = get_windows_accel()
        try:
            set_windows_accel((0, 0, 0))
            yield
        finally:
            if saved is not None:
                set_windows_accel(saved)
    else:
        try:
            _xset(False)
            yield
        finally:
            _xset(True)
