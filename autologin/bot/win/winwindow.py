"""Window-targeted automation primitives (Option D).

Core idea: operate on the *target window's own client area*, not the screen.
  - find windows by process name (survives empty/blank titles during loading)
  - capture via PrintWindow (works even when the window is hidden or minimized)
  - map client coordinates -> screen coordinates via the window rect
"""
import ctypes
import ctypes.wintypes as wt
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import psutil
from PIL import Image
import numpy as np

log = logging.getLogger("winwindow")

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
SW_RESTORE = 9
SW_MINIMIZE = 6
PW_RENDERFULLCONTENT = 0x00000002


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def size(self) -> Tuple[int, int]:
        return self.width, self.height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2


class WindowFinder:
    """Find top-level windows by process name (most robust), title, or class."""

    @staticmethod
    def _enum_top_level() -> List[Tuple[int, str, str, wt.RECT]]:
        out = []

        def cb(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1) if length else None
            title = ""
            if buf:
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
            cn = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cn, 256)
            rc = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rc))
            out.append((hwnd, title, cn.value, rc))
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return out

    @staticmethod
    def find_by_process(process_names: List[str],
                        min_width: int = 0, min_height: int = 0,
                        prefer_visible: bool = True) -> Optional[int]:
        """Return the largest hwnd owned by one of the given process names."""
        names = {n.lower() for n in process_names}
        candidates = []
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                continue
            if pname not in names:
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            if w < min_width or h < min_height:
                continue
            if prefer_visible and not user32.IsWindowVisible(hwnd):
                continue
            visible = 1 if user32.IsWindowVisible(hwnd) else 0
            candidates.append((w * h, visible, hwnd, title, cls, rc))
        if not candidates:
            return None
        # Largest, most-visible first.
        candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
        return candidates[0][2]

    @staticmethod
    def find_by_process_title(process_names: List[str],
                              title_substrs: List[str],
                              min_width: int = 0, min_height: int = 0,
                              prefer_visible: bool = True,
                              exclude_title_substrs: List[str] = None) -> Optional[int]:
        """Return the largest hwnd whose process matches AND whose title
        contains any of the given substrings (case-insensitive), excluding
        titles that contain any of 'exclude_title_substrs' (e.g. phone/QR
        login windows whose title contains 'log in')."""
        names = {n.lower() for n in process_names}
        subs = [s.lower() for s in title_substrs]
        excludes = [s.lower() for s in (exclude_title_substrs or [])]
        candidates = []
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            if not title:
                continue
            tl = title.lower()
            if not any(s in tl for s in subs):
                continue
            if any(e in tl for e in excludes):
                continue
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                continue
            try:
                pname = psutil.Process(pid.value).name().lower()
            except Exception:
                continue
            if pname not in names:
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            if w < min_width or h < min_height:
                continue
            if prefer_visible and not user32.IsWindowVisible(hwnd):
                continue
            visible = 1 if user32.IsWindowVisible(hwnd) else 0
            candidates.append((w * h, visible, hwnd, title, cls, rc))
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
        return candidates[0][2]

    @staticmethod
    def find_by_title(substr: str, min_width: int = 0, min_height: int = 0,
                      exact: bool = False) -> Optional[int]:
        targets = []
        for hwnd, title, cls, rc in WindowFinder._enum_top_level():
            if not title:
                continue
            if exact and title.lower() != substr.lower():
                continue
            if not exact and substr.lower() not in title.lower():
                continue
            w = rc.right - rc.left
            h = rc.bottom - rc.top
            if w < min_width or h < min_height:
                continue
            if not user32.IsWindowVisible(hwnd):
                continue
            targets.append((w * h, hwnd))
        if not targets:
            return None
        targets.sort(reverse=True)
        return targets[0][1]

    @staticmethod
    def pids_for_process(name: str) -> List[int]:
        out = []
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and p.info["name"].lower() == name.lower():
                    out.append(p.pid)
            except Exception:
                pass
        return out


class WinWindow:
    """A live target window: knows its rect, can capture and be activated."""

    def __init__(self, hwnd: int):
        self.hwnd = int(hwnd)

    # ---- metadata ------------------------------------------------------
    @property
    def valid(self) -> bool:
        return bool(user32.IsWindow(self.hwnd))

    @property
    def visible(self) -> bool:
        return bool(user32.IsWindowVisible(self.hwnd))

    @property
    def title(self) -> str:
        length = user32.GetWindowTextLengthW(self.hwnd)
        if not length:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(self.hwnd, buf, length + 1)
        return buf.value

    @property
    def rect(self) -> Rect:
        rc = wt.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rc))
        return Rect(rc.left, rc.top, rc.right, rc.bottom)

    @property
    def client_rect(self) -> Rect:
        rc = wt.RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rc))
        return Rect(0, 0, rc.right, rc.bottom)

    def activate(self):
        user32.ShowWindow(self.hwnd, SW_RESTORE)
        time.sleep(0.1)
        try:
            target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            attached = user32.AttachThreadInput(current_thread, target_thread, True)
            try:
                user32.SetForegroundWindow(self.hwnd)
                user32.BringWindowToTop(self.hwnd)
                user32.SetActiveWindow(self.hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, target_thread, False)
        except Exception:
            user32.SetForegroundWindow(self.hwnd)
        time.sleep(0.2)

    def minimize(self):
        user32.ShowWindow(self.hwnd, SW_MINIMIZE)

    def resize(self, width: int, height: int,
               left: Optional[int] = None, top: Optional[int] = None) -> bool:
        """Force outer window size (and optional position). Needs matching
        integrity vs elevated targets (UIPI otherwise silently ignores)."""
        if width <= 0 or height <= 0:
            return False
        r = self.rect
        x = r.left if left is None else int(left)
        y = r.top if top is None else int(top)
        try:
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            # SWP_NOZORDER | SWP_SHOWWINDOW — keep z-order, show if needed
            SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
            ok = bool(user32.SetWindowPos(
                self.hwnd, 0, x, y, int(width), int(height),
                SWP_NOZORDER | SWP_SHOWWINDOW))
            time.sleep(0.12)
            return ok
        except Exception as e:
            log.warning("resize failed: %r", e)
            return False

    # ---- capture -------------------------------------------------------
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
        ]

    def capture(self) -> Optional[Image.Image]:
        """PrintWindow the window's client area. Works when hidden/minimized."""
        rect = self.rect
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            log.debug(f"capture: degenerate rect {w}x{h}")
            return None
        hdc = user32.GetWindowDC(self.hwnd)
        if not hdc:
            log.warning(f"capture: GetWindowDC failed for hwnd {self.hwnd}")
            return None
        mdc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mdc, bmp)
        try:
            user32.PrintWindow(self.hwnd, mdc, PW_RENDERFULLCONTENT)
            class BIH(ctypes.Structure):
                _fields_ = [
                    ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
                ]
            class BI(ctypes.Structure):
                _fields_ = [("bmiHeader", BIH)]
            bmi = BI()
            bmi.bmiHeader.biSize = ctypes.sizeof(BIH)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
            img = Image.fromarray(arr[:, :, :3][:, :, ::-1].copy())
            return img
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(self.hwnd, hdc)

    def capture_content(self) -> Optional[Image.Image]:
        """Capture for OCR. Tries PrintWindow first (works for DirectX/OpenGL
        game windows where screen BitBlt only sees the title bar). Falls back
        to screen BitBlt for Chromium/GPU-rendered windows like Purple.

        Occlusion guard: Chromium STOPS RENDERING fully covered windows, so
        PrintWindow then returns a stale/blank frame and a screen BitBlt
        would grab whatever covers the window. Before falling back, the
        window is raised TOPMOST briefly so it renders again, and the screen
        capture is taken while it is guaranteed on top."""
        img = self.capture()
        if img is not None:
            import numpy as _np
            arr = _np.asarray(img)
            if arr.mean() > 5:
                return img
        if not self.visible:
            return None
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        try:
            time.sleep(0.35)          # let Chromium produce a fresh frame
            img = self.capture()
            if img is not None:
                import numpy as _np
                if _np.asarray(img).mean() > 5:
                    return img
            return self.capture_screen()
        finally:
            user32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # ---- coordinate mapping --------------------------------------------
    def client_to_screen(self, x: int, y: int) -> Tuple[int, int]:
        """Map a client-area point to absolute screen coordinates."""
        rect = self.rect
        return rect.left + x, rect.top + y

    def screen_to_client(self, x: int, y: int) -> Tuple[int, int]:
        """Map an absolute screen point to client-area coordinates."""
        rect = self.rect
        return x - rect.left, y - rect.top

    def find_child(self, class_substr: str) -> Optional[int]:
        """Find a descendant window whose class name contains class_substr."""
        found = []
        EnumChildProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def cb(hwnd, _):
            cn = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cn, 256)
            if class_substr.lower() in cn.value.lower():
                found.append(hwnd)
            return True

        user32.EnumChildWindows(self.hwnd, EnumChildProc(cb), 0)
        return found[0] if found else None

    def child_offset(self, class_substr: str) -> Optional[Tuple[int, int]]:
        """Return (dx, dy) offset of a child window's client area relative to
        this window's client origin (0,0). Used to translate OCR coords from
        the form-window capture into the child's coordinate space."""
        child = self.find_child(class_substr)
        if child is None:
            return None
        rc = wt.RECT()
        user32.GetWindowRect(child, ctypes.byref(rc))
        prc = wt.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(prc))
        return rc.left - prc.left, rc.top - prc.top

    def capture_screen(self) -> Optional[Image.Image]:
        """Capture the window's on-screen region (works for DirectX/HWND-less
        content that PrintWindow returns black for). Window must be visible."""
        rect = self.rect
        w, h = rect.width, rect.height
        if w <= 0 or h <= 0:
            return None
        hdc = user32.GetDC(None)  # screen DC
        if not hdc:
            log.warning("capture_screen: GetDC(NULL) failed")
            return None
        mdc = gdi32.CreateCompatibleDC(hdc)
        bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
        gdi32.SelectObject(mdc, bmp)
        try:
            gdi32.BitBlt(mdc, 0, 0, w, h, hdc, rect.left, rect.top, 0x00CC0020)  # SRCCOPY
            class BIH(ctypes.Structure):
                _fields_ = [
                    ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                    ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
                ]
            class BI(ctypes.Structure):
                _fields_ = [("bmiHeader", BIH)]
            bmi = BI()
            bmi.bmiHeader.biSize = ctypes.sizeof(BIH)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            buf = ctypes.create_string_buffer(w * h * 4)
            gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
            return Image.fromarray(arr[:, :, :3][:, :, ::-1].copy())
        finally:
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mdc)
            user32.ReleaseDC(None, hdc)


def capture_to_file(win: WinWindow, path: str) -> Optional[Image.Image]:
    img = win.capture()
    if img is None:
        return None
    img.save(path)
    log.info(f"saved capture {img.size} -> {path}")
    return img


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Find all visible windows and their process names for debugging.
    for hwnd, title, cls, rc in WindowFinder._enum_top_level():
        if not title:
            continue
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            pname = psutil.Process(pid.value).name()
        except Exception:
            pname = "?"
        w = rc.right - rc.left
        h = rc.bottom - rc.top
        if w > 300 and h > 200:
            print(f"{hwnd:>10} {pname:<16} {w}x{h} visible={user32.IsWindowVisible(hwnd)} title={title!r}")
