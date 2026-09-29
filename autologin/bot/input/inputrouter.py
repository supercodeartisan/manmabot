"""Input routing for Option D.

Mouse click modes, primary first:
  - interception: the Interception kernel driver emits device-level
    unflagged input (bypasses SendInput-based anti-cheat detection). This is
    the main mouse method; Win32/SendInput is the fallback.
  - foreground: bring the target window to the front and use SendInput at
    absolute screen coords (works for any window that accepts real input).
  - background: PostMessage WM_LBUTTONDOWN/UP to the window's client area
    (works even when the window is hidden/behind others, for windows that
    accept posted messages).
"""
import ctypes
import ctypes.wintypes as wt
import logging
import time
from typing import Optional, Tuple

from win import interception
from win.winwindow import WinWindow

log = logging.getLogger("inputrouter")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
SM_CXSCREEN = 0
SM_CYSCREEN = 1
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_CONTROL = 0x11
VK_V = 0x56
VK_RETURN = 0x0D
VK_TAB = 0x09
VK_SPACE = 0x20
VK_BACK = 0x08
VK_DELETE = 0x2E
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD), ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUT_UNION)]


_SendInput = user32.SendInput
_SendInput.argtypes = [wt.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_SendInput.restype = wt.UINT

# Proper ctypes signatures for clipboard APIs so 64-bit HGLOBAL handles
# are not truncated (GlobalLock was failing with error 6 "invalid handle").
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalFree.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
user32.SetClipboardData.restype = wt.HGLOBAL
user32.SetClipboardData.argtypes = [wt.UINT, wt.HGLOBAL]


class InputRouter:
    @staticmethod
    def activate(win: WinWindow):
        """Bring a window to the foreground. Physical input injected by the
        Interception driver is never subject to Windows' foreground lock or
        UIPI, so clicking the window's own title bar is the most reliable way
        to give it focus (a background process calling SetForegroundWindow
        alone is often ignored). Falls back to the Win32 method when the
        driver is unavailable."""
        win.activate()
        if interception.init():
            r = win.rect
            cx = r.left + r.width // 2
            cy = r.top + max(8, min(22, r.height // 25))
            interception.click(cx, cy)
            time.sleep(0.15)

    @staticmethod
    def click_screen(x: int, y: int, delay: float = 0.05, hover: float = 0.0):
        # Primary method: Interception driver (device-level, unflagged input).
        # interception.init() is idempotent; on failure we fall back to
        # SendInput below.
        if interception.init() and interception.click(x, y):
            if hover > 0:
                # Let the UI register a hover state before the click registers
                # (game modals often ignore a click with no hover dwell).
                time.sleep(hover)
            if delay > 0:
                time.sleep(delay)
            return

        # Fallback: SendInput (unlike the legacy mouse_event) does NOT stamp
        # the 0xFF515700 "synthetic input" mark that anti-cheats read via
        # GetMessageExtraInfo(); games that silently drop marked clicks
        # accept SendInput events. Move the real cursor first for feedback.
        user32.SetCursorPos(x, y)
        time.sleep(0.03)
        sw = max(1, user32.GetSystemMetrics(SM_CXSCREEN) - 1)
        sh = max(1, user32.GetSystemMetrics(SM_CYSCREEN) - 1)

        def _mouse(flags):
            mi = _INPUT()
            mi.type = INPUT_MOUSE
            mi.union.mi.dx = int(x * 65535 // sw)
            mi.union.mi.dy = int(y * 65535 // sh)
            mi.union.mi.mouseData = 0
            mi.union.mi.dwFlags = MOUSEEVENTF_ABSOLUTE | flags
            mi.union.mi.time = 0
            mi.union.mi.dwExtraInfo = 0
            _SendInput(1, ctypes.byref(mi), ctypes.sizeof(_INPUT))

        _mouse(MOUSEEVENTF_MOVE)
        time.sleep(0.03)
        if hover > 0:
            # Let the UI register a hover state before pressing down (game
            # modals often ignore a click that arrives with no hover dwell).
            time.sleep(hover)
        _mouse(MOUSEEVENTF_LEFTDOWN)
        time.sleep(0.03)
        _mouse(MOUSEEVENTF_LEFTUP)
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def double_click_screen(x: int, y: int, delay: float = 0.08,
                            interval: float = 0.1):
        """Two SendInput clicks at the point (some game UI accepts only a
        double-click)."""
        InputRouter.click_screen(x, y, delay=interval)
        InputRouter.click_screen(x, y, delay=delay)

    @staticmethod
    def press_tab():
        InputRouter._send_vk(VK_TAB, True)
        time.sleep(0.03)
        InputRouter._send_vk(VK_TAB, False)
        time.sleep(0.1)

    @staticmethod
    def press_space():
        InputRouter._send_vk(VK_SPACE, True)
        time.sleep(0.03)
        InputRouter._send_vk(VK_SPACE, False)
        time.sleep(0.1)

    @staticmethod
    def wake_window(win: WinWindow, cycles: int = 8, amp: int = 15,
                    interval: float = 0.05):
        """Programmatic replacement for the drag-shake. Emits the SAME window
        event stream a real title-bar drag produces (WM_ENTERSIZEMOVE -> real
        rect changes -> WM_EXITSIZEMOVE) WITHOUT touching the mouse or visibly
        dragging. Real rect changes via SetWindowPos force the game thread to
        pump WM_MOVE / WM_WINDOWPOSCHANGED synchronously, which wakes the
        stuck embedded-webview device check. The window is returned to its
        original spot. NOTE: no WM_ACTIVATEAPP/WM_ACTIVATE fakes are posted —
        lying to the game about its activation state caused it to drop focus
        and, on GameGuard builds, made the client exit.

        Safety: never nudge from a maximized / off-screen origin — that was
        observed to fight GLFW into 1936x1056 @ (-8,-8). Clamp to work area.
        """
        hwnd = win.hwnd
        try:
            if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.12)
        except Exception:
            pass
        r = win.rect
        WM_ENTERSIZEMOVE, WM_EXITSIZEMOVE = 0x0231, 0x0232
        SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
        amp = max(2, min(int(amp), 12))
        # Work-area clamp so nudge never drives the shell into Aero snap.
        try:
            wa = wt.RECT()
            user32.SystemParametersInfoW(48, 0, ctypes.byref(wa), 0)
            min_x, min_y = int(wa.left), int(wa.top)
            max_x = int(wa.right - r.width)
            max_y = int(wa.bottom - r.height)
        except Exception:
            min_x = min_y = 0
            max_x = max(0, user32.GetSystemMetrics(0) - r.width)
            max_y = max(0, user32.GetSystemMetrics(1) - r.height)
        origin_x = max(min_x, min(max_x, max(0, r.left)))
        origin_y = max(min_y, min(max_y, max(0, r.top)))
        if origin_x != r.left or origin_y != r.top:
            user32.SetWindowPos(hwnd, 0, origin_x, origin_y, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            time.sleep(0.05)
        user32.PostMessageW(hwnd, WM_ENTERSIZEMOVE, 0, 0)
        x, y = origin_x, origin_y
        for i in range(cycles):
            dx = amp if i % 2 == 0 else -amp
            dy = amp if (i // 2) % 2 == 0 else -amp
            x = max(min_x, min(max_x, x + dx))
            y = max(min_y, min(max_y, y + dy))
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            time.sleep(interval)
        user32.SetWindowPos(hwnd, 0, origin_x, origin_y, 0, 0,
                            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        time.sleep(interval)
        user32.PostMessageW(hwnd, WM_EXITSIZEMOVE, 0, 0)

    @staticmethod
    def shake_window(win: WinWindow, duration: float = 3.0, amp: int = 6):
        """Focus the window's title/menu bar and jitter it with tiny, very fast
        drag movements (default ~6px, ~5ms/step) so the move flood is almost
        invisible on screen but still re-triggers the embedded Security
        Setting / device-verification check. The drag runs through the
        Interception driver (device-level input); the legacy SendInput drag
        is only used when the driver is unavailable."""
        r = win.rect
        cx = r.left + (r.right - r.left) // 2
        cy = r.top + max(8, min(22, (r.bottom - r.top) // 25))
        sw = max(1, user32.GetSystemMetrics(SM_CXSCREEN) - 1)
        sh = max(1, user32.GetSystemMetrics(SM_CYSCREEN) - 1)
        pattern = [(0, -amp), (0, amp), (-amp, 0), (amp, 0)]

        if interception.init():
            interception.move(cx, cy)
            time.sleep(0.15)
            if interception.button_down(cx, cy):
                time.sleep(0.2)
                x, y = cx, cy
                i = 0
                start = time.time()
                while time.time() - start < duration:
                    mx, my = pattern[i % 4]
                    i += 1
                    x = max(0, min(sw, x + mx))
                    y = max(0, min(sh, y + my))
                    interception.move(x, y)
                    time.sleep(0.005)
                interception.button_up(x, y)
                time.sleep(0.3)
                return

        # Fallback: legacy SendInput drag.
        user32.SetCursorPos(cx, cy)
        time.sleep(0.15)

        def _mouse(flags, x, y):
            mi = _INPUT()
            mi.type = INPUT_MOUSE
            mi.union.mi.dx = int(x * 65535 // sw)
            mi.union.mi.dy = int(y * 65535 // sh)
            mi.union.mi.mouseData = 0
            mi.union.mi.dwFlags = MOUSEEVENTF_ABSOLUTE | flags
            mi.union.mi.time = 0
            mi.union.mi.dwExtraInfo = 0
            _SendInput(1, ctypes.byref(mi), ctypes.sizeof(_INPUT))

        _mouse(MOUSEEVENTF_LEFTDOWN, cx, cy)
        time.sleep(0.2)
        x, y = cx, cy
        i = 0
        start = time.time()
        while time.time() - start < duration:
            mx, my = pattern[i % 4]
            i += 1
            x = max(0, min(sw, x + mx))
            y = max(0, min(sh, y + my))
            _mouse(MOUSEEVENTF_MOVE, x, y)
            time.sleep(0.005)
        _mouse(MOUSEEVENTF_LEFTUP, x, y)
        time.sleep(0.3)

    @staticmethod
    def focus_menubar(win: WinWindow, duration: float = 9.0, click: bool = True):
        """Gently focus the game window's menu bar and HOLD the cursor there
        (no violent shaking). For the embedded Security Setting / device-
        verification webview, simply parking the mouse on the menubar and
        waiting lets the deferred device check complete on its own. After
        `duration` seconds the cursor is released (moved away) — which is what
        kicks the verification to finish."""
        r = win.rect
        cx = r.left + (r.right - r.left) // 2
        cy = r.top + max(8, min(22, (r.bottom - r.top) // 25))
        if interception.init():
            interception.move(cx, cy)
        else:
            user32.SetCursorPos(cx, cy)
        time.sleep(0.3)
        if click:
            # One soft click gives the menubar focus; the window stays put.
            InputRouter.click_screen(cx, cy, 0.05)
            time.sleep(0.4)
        # Hold the cursor focused on the menubar for the requested time.
        end = time.time() + duration
        while time.time() < end:
            if interception.init():
                interception.move(cx, cy)
            else:
                user32.SetCursorPos(cx, cy)
            time.sleep(0.5)
        # Cancel focus: move the cursor away from the menubar.
        if interception.init():
            interception.move(4, 4)
        else:
            user32.SetCursorPos(4, 4)
        time.sleep(0.3)

    @staticmethod
    def click_client(win: WinWindow, cx: int, cy: int,
                     foreground: bool = True, delay: float = 0.05):
        """Click at client-area coords (cx, cy) inside the window."""
        if foreground:
            win.activate()
            sx, sy = win.client_to_screen(cx, cy)
            InputRouter.click_screen(sx, sy, delay)
        else:
            lparam = (cy << 16) | (cx & 0xFFFF)
            user32.PostMessageW(win.hwnd, WM_LBUTTONDOWN, 0x0001, lparam)
            time.sleep(0.02)
            user32.PostMessageW(win.hwnd, WM_LBUTTONUP, 0, lparam)
            time.sleep(delay)

    @staticmethod
    def click_screen_top(sx: int, sy: int, delay: float = 0.05):
        """SendInput click at absolute screen coords WITHOUT any activation
        or foreground manipulation. The OS routes it to whichever window is
        topmost at (sx, sy) — use when an overlay dialog sits above the game
        window and activating the game would cover it."""
        InputRouter.click_screen(sx, sy, delay)

    @staticmethod
    def topmost_hwnd_at(sx: int, sy: int) -> int:
        """The real window (including child windows) at a screen point."""
        return user32.WindowFromPoint(wt.POINT(sx, sy))

    @staticmethod
    def window_rect(hwnd: int) -> Tuple[int, int, int, int]:
        """(left, top, width, height) of a window."""
        rc = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top

    @staticmethod
    def postmessage_click(hwnd: int, cx: int, cy: int, delay: float = 0.1):
        """Background click: PostMessage mouse messages to a window in its
        client coords. Works for windows that accept posted input (CEF
        webviews, embedded dialogs) and never touches the foreground."""
        if not hwnd:
            return
        lparam = (cy << 16) | (cx & 0xFFFF)
        user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, 0x0001, lparam)
        time.sleep(0.02)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
        if delay > 0:
            time.sleep(delay)

    # ---- typing -------------------------------------------------------
    @staticmethod
    def _send_unicode(ch: str):
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            ki = _INPUT()
            ki.type = INPUT_KEYBOARD
            ki.union.ki.wVk = 0
            ki.union.ki.wScan = ord(ch)
            ki.union.ki.dwFlags = flags
            ki.union.ki.time = 0
            ki.union.ki.dwExtraInfo = None
            _SendInput(1, ctypes.byref(ki), ctypes.sizeof(_INPUT))

    @staticmethod
    def _send_vk(vk: int, down: bool):
        ki = _INPUT()
        ki.type = INPUT_KEYBOARD
        ki.union.ki.wVk = vk
        ki.union.ki.dwFlags = 0 if down else KEYEVENTF_KEYUP
        ki.union.ki.time = 0
        ki.union.ki.dwExtraInfo = None
        _SendInput(1, ctypes.byref(ki), ctypes.sizeof(_INPUT))

    @staticmethod
    def _clipboard_set(text: str, retries: int = 5) -> bool:
        for attempt in range(retries):
            try:
                data = text.encode("utf-16-le") + b"\x00\x00"
                if not user32.OpenClipboard(None):
                    time.sleep(0.05)
                    continue
                try:
                    if not user32.EmptyClipboard():
                        time.sleep(0.05)
                        continue
                    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if not h:
                        time.sleep(0.05)
                        continue
                    p = kernel32.GlobalLock(h)
                    if not p:
                        kernel32.GlobalFree(h)
                        time.sleep(0.05)
                        continue
                    try:
                        ctypes.memmove(p, data, len(data))
                    finally:
                        kernel32.GlobalUnlock(h)
                    if not user32.SetClipboardData(CF_UNICODETEXT, h):
                        kernel32.GlobalFree(h)
                        time.sleep(0.05)
                        continue
                    return True
                finally:
                    user32.CloseClipboard()
            except Exception:
                time.sleep(0.05)
        return False

    @staticmethod
    def _ctrl_v():
        InputRouter._send_vk(VK_CONTROL, True)
        time.sleep(0.03)
        InputRouter._send_vk(VK_V, True)
        time.sleep(0.03)
        InputRouter._send_vk(VK_V, False)
        time.sleep(0.03)
        InputRouter._send_vk(VK_CONTROL, False)
        time.sleep(0.2)

    @staticmethod
    def type_text(text: str, delay: float = 0.03):
        """Paste text into the focused field (reliable for CEF/Chromium UI)."""
        if not InputRouter._clipboard_set(text):
            log.warning("clipboard set failed, fallback to unicode keys")
            for ch in text:
                InputRouter._send_unicode(ch)
                time.sleep(delay)
            return
        InputRouter._ctrl_v()

    @staticmethod
    def press_enter():
        InputRouter._send_vk(VK_RETURN, True)
        time.sleep(0.03)
        InputRouter._send_vk(VK_RETURN, False)
        time.sleep(0.1)

    # ---- device-level keyboard (Interception, bypasses SendInput blocks) --
    @staticmethod
    def physical_press_enter():
        if interception.init():
            interception.tap(VK_RETURN)
            return True
        return False

    @staticmethod
    def physical_press_tab():
        if interception.init():
            interception.tap(VK_TAB)
            return True
        return False

    @staticmethod
    def physical_press_space():
        if interception.init():
            interception.tap(VK_SPACE)
            return True
        return False

    @staticmethod
    def physical_select_all():
        if interception.init():
            interception.key_down(VK_CONTROL)
            interception.tap(0x41)
            interception.key_up(VK_CONTROL)
            return True
        return False

    @staticmethod
    def physical_paste():
        if interception.init():
            interception.key_down(VK_CONTROL)
            interception.tap(VK_V)
            interception.key_up(VK_CONTROL)
            return True
        return False

    @staticmethod
    def physical_type_text(text: str, retries: int = 3) -> bool:
        """Paste text into the focused field entirely at device level:
        the text is placed on the clipboard by us, then Ctrl+V is injected
        through the Interception driver (immune to SendInput/anti-cheat
        blocking). Falls back to regular SendInput typing if unavailable."""
        if not interception.init():
            # Device-level driver unavailable: fall back to SendInput typing,
            # which already deposited the text into the focused field. RETURN
            # True so callers (e.g. type_cef) do NOT fall through and type the
            # same text a second time via WM_CHAR — that double-entry showed up
            # as a doubled first character and the email being pasted twice.
            InputRouter.type_text(text)
            return True
        for _ in range(retries):
            if InputRouter._clipboard_set(text) and InputRouter.physical_paste():
                time.sleep(0.2)
                return True
            time.sleep(0.1)
        return False

    @staticmethod
    def click_cef(win: WinWindow, cx: int, cy: int, delay: float = 0.1):
        """Click inside the window's CEF/Chromium child (used by Purple's
        embedded login form). Coordinates are in the CEF child's client space.

        Uses Interception driver for BOTH activation and click: clicks the
        title bar to bring the window to foreground (bypasses UIPI), then
        clicks the target field."""
        # Physical clicks hit whatever is visually on top. Raise the target
        # before moving the cursor so another window cannot steal them.
        try:
            user32.SetWindowPos(win.hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)
            time.sleep(0.2)
        except Exception:
            pass
        cef = win.find_child("Chrome_RenderWidgetHostHWND")
        if cef is not None:
            # Interception-based activation: click title bar to bring window forward
            if interception.init():
                rect = win.rect
                title_x = rect.left + rect.width // 2
                title_y = rect.top + 15
                interception.move(title_x, title_y)
                time.sleep(0.05)
                interception.click(title_x, title_y)
                time.sleep(0.2)
            else:
                win.activate()
            rc = wt.RECT()
            user32.GetWindowRect(cef, ctypes.byref(rc))
            InputRouter.click_screen(rc.left + cx, rc.top + cy, delay=delay)
            return
        InputRouter.click_client(win, cx, cy, delay=delay)

    @staticmethod
    def type_cef(win: WinWindow, text: str, delay: float = 0.02):
        """Type text into the CEF child via Interception driver (device-level
        character-by-character typing, bypasses UIPI/SendInput blocks on
        elevated windows)."""
        cef = win.find_child("Chrome_RenderWidgetHostHWND")
        if cef is None:
            InputRouter.physical_type_text(text)
            return
        # Interception char-by-char is US-layout only and garbles '@'
        # / mixed case on Korean IME. Prefer clipboard paste.
        if InputRouter.physical_type_text(text):
            time.sleep(0.3)
            return
        if interception.init() and interception.type_string(text):
            return
        # Last resort: WM_CHAR (blocked by UIPI on elevated windows)
        for ch in text:
            user32.PostMessageW(cef, WM_CHAR, ord(ch), 0)
            time.sleep(delay)
        time.sleep(0.3)

    @staticmethod
    def select_all_cef(win: WinWindow):
        cef = win.find_child("Chrome_RenderWidgetHostHWND")
        if cef is None:
            InputRouter.select_all()
            return
        # Ctrl+A via key messages to the CEF window.
        user32.PostMessageW(cef, WM_KEYDOWN, VK_CONTROL, 0)
        user32.PostMessageW(cef, WM_KEYDOWN, 0x41, 0)
        user32.PostMessageW(cef, WM_KEYUP, 0x41, 0)
        user32.PostMessageW(cef, WM_KEYUP, VK_CONTROL, 0)
        time.sleep(0.2)

    @staticmethod
    def clear_cef(win: WinWindow, max_chars: int = 60):
        """Clear the focused CEF input field.

        Tries, in order: Interception select-all + Delete (bypasses UIPI on
        elevated windows), then a WM_CTRL+A + Delete posted straight to the CEF
        child (works without the driver), then a Backspace fallback. The
        select-all-first approach guarantees the field is emptied instead of
        deleting the last max_chars with trailing text left over - the cause of
        the email/password 'copying again and again' duplication."""
        cef = win.find_child("Chrome_RenderWidgetHostHWND")
        if cef is None:
            return
        # Prefer device-level select-all + delete (bypasses UIPI).
        if InputRouter.physical_select_all():
            interception.tap(0x2E)  # VK_DELETE
            time.sleep(0.3)
            return
        # No driver: use SYNCHRONOUS SendInput select-all + Delete. This must
        # complete before the following paste - the old async PostMessage
        # Ctrl+A/Delete could be processed by the CEF child AFTER the SendInput
        # paste landed, which deleted part of the freshly-typed text and showed
        # a doubled/garbled leading character ("double a").
        InputRouter.select_all()
        InputRouter._send_vk(VK_DELETE, True)
        InputRouter._send_vk(VK_DELETE, False)
        time.sleep(0.3)
        # Last-resort backspace flood (only if select-all produced no effect,
        # e.g. the field was not actually focused).
        for _ in range(max_chars):
            user32.PostMessageW(cef, WM_KEYDOWN, VK_BACK, 0)
            time.sleep(0.01)
            user32.PostMessageW(cef, WM_KEYUP, VK_BACK, 0)
            time.sleep(0.01)
        time.sleep(0.3)

    @staticmethod
    def select_all():
        InputRouter._send_vk(VK_CONTROL, True)
        time.sleep(0.01)
        InputRouter._send_vk(0x41, True)
        time.sleep(0.01)
        InputRouter._send_vk(0x41, False)
        time.sleep(0.01)
        InputRouter._send_vk(VK_CONTROL, False)
        time.sleep(0.05)

    # ---- UI Automation click (accessibility, not input injection) --------
    @staticmethod
    def click_uia(sx: int, sy: int, delay: float = 0.1) -> bool:
        """Click at screen coordinates using UI Automation (accessibility API).
        This invokes the UI element programmatically without sending input events,
        bypassing the LLMHF_INJECTED flag that NC Guard blocks."""
        try:
            import comtypes
            import comtypes.client
            from comtypes import GUID, IUnknown, HRESULT, COMMETHOD
            from comtypes.automation import VARIANT, VT_EMPTY
        except Exception:
            log.warning("comtypes not available for UIA click")
            return False

        # UIA interface definitions
        UIA_InvokePatternId = 10000
        UIA_LegacyIAccessiblePatternId = 10018

        class IUIAutomationElement(IUnknown):
            _iid_ = GUID("{d22108aa-8ac5-49a5-837b-37bbb3d7591e}")
            _methods_ = [
                COMMETHOD([], HRESULT, "GetCurrentPattern",
                          (["in"], ctypes.c_int, "patternId"),
                          (["out", "retval"], ctypes.POINTER(ctypes.c_void_p), "pattern")),
                COMMETHOD([], HRESULT, "GetCachedPattern",
                          (["in"], ctypes.c_int, "patternId"),
                          (["out", "retval"], ctypes.POINTER(ctypes.c_void_p), "pattern")),
            ]

        class IInvokeProvider(IUnknown):
            _iid_ = GUID("{fb377fbe-8ea6-46d5-9c73-6499642d3059}")
            _methods_ = [
                COMMETHOD([], HRESULT, "Invoke"),
            ]

        class ILegacyIAccessibleProvider(IUnknown):
            _iid_ = GUID("{828055ad-355b-443d-8213-f57c6c73c6d0}")
            _methods_ = [
                COMMETHOD([], HRESULT, "DoDefaultAction"),
            ]

        try:
            # Initialize COM
            comtypes.CoInitialize()
            try:
                # Create UIA automation
                uia = comtypes.client.CreateObject("UIAutomationClient.CUIAutomation", interface=comtypes.gen.UIAutomationClient.IUIAutomation)
                
                # Get element at screen point
                pt = comtypes.gen.UIAutomationClient.tagPOINT(sx, sy)
                element = uia.ElementFromPoint(pt)
                if not element:
                    return False

                # Try InvokePattern (for buttons)
                invoke_pattern = ctypes.c_void_p()
                hr = element.GetCurrentPattern(UIA_InvokePatternId, ctypes.byref(invoke_pattern))
                if hr == 0 and invoke_pattern.value:
                    provider = ctypes.cast(invoke_pattern, ctypes.POINTER(IInvokeProvider))
                    provider.contents.Invoke()
                    time.sleep(delay)
                    return True

                # Fallback: LegacyIAccessible (MSAA) - DoDefaultAction
                legacy_pattern = ctypes.c_void_p()
                hr = element.GetCurrentPattern(UIA_LegacyIAccessiblePatternId, ctypes.byref(legacy_pattern))
                if hr == 0 and legacy_pattern.value:
                    provider = ctypes.cast(legacy_pattern, ctypes.POINTER(ILegacyIAccessibleProvider))
                    provider.contents.DoDefaultAction()
                    time.sleep(delay)
                    return True

                return False
            finally:
                comtypes.CoUninitialize()
        except Exception as e:
            log.warning(f"UIA click failed: {e}")
            return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    from win.winwindow import WindowFinder

    # Type into the focused window (used for testing only).
    if len(sys.argv) > 1:
        InputRouter.type_text(" ".join(sys.argv[1:]))
        print("typed")
