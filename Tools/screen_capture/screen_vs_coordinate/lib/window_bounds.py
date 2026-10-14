"""Find the game window and track its client-area bounds on screen."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass(frozen=True)
class WindowBounds:
    """Client area of the game window in desktop pixel coordinates."""

    left: int
    top: int
    width: int
    height: int
    hwnd: int = 0

    @property
    def valid(self) -> bool:
        return self.width > 0 and self.height > 0

    def as_region(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def _process_exe_path(pid: int) -> Optional[str]:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        ):
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_class(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(hwnd, buf, len(buf)):
        return ""
    return buf.value


def find_game_window(
    process_name: str,
    title_hint: Optional[str] = None,
) -> Optional[int]:
    """Return the HWND of a visible window owned by ``process_name``."""
    target = process_name.lower()
    if not target.endswith(".exe"):
        target = f"{target}.exe"

    matches: list[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe_path = _process_exe_path(pid.value)
        if not exe_path:
            return True

        exe_name = exe_path.rsplit("\\", 1)[-1].lower()
        if exe_name != target:
            return True

        # GameGuard exposes a visible LC.exe-owned dummy window. It must never
        # satisfy readiness or become the capture target.
        if _window_class(hwnd) == "$GIVEmeMINT":
            return True

        if title_hint:
            title = _window_title(hwnd).lower()
            if title_hint.lower() not in title:
                return True

        matches.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return matches[0] if matches else None


def get_client_bounds(hwnd: int) -> Optional[WindowBounds]:
    """Return the client area of ``hwnd`` in screen coordinates."""
    rect = _RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    origin = _POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    return WindowBounds(
        left=origin.x,
        top=origin.y,
        width=width,
        height=height,
        hwnd=hwnd,
    )


def is_window_minimized(hwnd: int) -> bool:
    """True when ``hwnd`` is minimized (iconic)."""
    if not hwnd:
        return False
    return bool(user32.IsIconic(hwnd))


class WindowTracker:
    """Refresh and cache the game window client bounds."""

    def __init__(
        self,
        process_name: Optional[str] = None,
        title_hint: Optional[str] = None,
        finder: Optional[Callable[[str, Optional[str]], Optional[int]]] = None,
    ) -> None:
        self.process_name = process_name
        self.title_hint = title_hint
        self._finder = finder or find_game_window
        self._hwnd: Optional[int] = None
        self._last_bounds: Optional[WindowBounds] = None

    def _resolve_hwnd(self) -> Optional[int]:
        if not self.process_name:
            return self._hwnd
        hwnd = self._hwnd
        if hwnd is not None and user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd):
            if _window_class(hwnd) != "$GIVEmeMINT":
                return hwnd
        hwnd = self._finder(self.process_name, self.title_hint)
        if hwnd is not None:
            self._hwnd = hwnd
        else:
            self._hwnd = None
            self._last_bounds = None
        return self._hwnd

    @property
    def is_minimized(self) -> bool:
        """True when the tracked game window is minimized."""
        hwnd = self._resolve_hwnd()
        if hwnd is None:
            return False
        return is_window_minimized(hwnd)

    def refresh(self) -> Optional[WindowBounds]:
        """Update bounds from the live window; cache the last good value."""
        if not self.process_name:
            return None

        hwnd = self._resolve_hwnd()
        if hwnd is None:
            return self._last_bounds

        if is_window_minimized(hwnd):
            # Client rect is useless while minimized; keep last good bounds.
            return self._last_bounds

        bounds = get_client_bounds(hwnd)
        if bounds is not None and bounds.valid:
            self._last_bounds = bounds
        return self._last_bounds
