"""Minimal ctypes wrapper for the Interception input driver
(oblitum/Interception, v1.0.1). Provides unflagged device-level mouse
moves/clicks that bypass SendInput-based anti-cheat detection.

The installed driver is a keyboard/mouse class upper filter; interception.dll
talks to it via the \\\\.\\interception00..19 device objects.
"""

import ctypes
import os
import time

# DLL path can be overridden via environment variable or config
_DLL_PATH = os.environ.get("INTERCEPTION_DLL") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "interception.dll"
)

_INTERCEPTION_MAX_KEYBOARD = 10
_INTERCEPTION_MAX_MOUSE = 10

# Device ids: INTERCEPTION_KEYBOARD(i) = i + 1, so keyboards are 1..10;
# INTERCEPTION_MOUSE(i) = 10 + i + 1, so mice are 11..20.
INTERCEPTION_KEYBOARD_0 = 1
INTERCEPTION_MOUSE_0 = 11
_KB_MIN = 1
_KB_MAX = 10
_MOUSE_MIN = 11
_MOUSE_MAX = 20

# InterceptionMouseState
_STATE_MOVE = 0x000
_STATE_LEFT_BUTTON_DOWN = 0x001
_STATE_LEFT_BUTTON_UP = 0x002
_STATE_WHEEL = 0x007

_WHEEL_DELTA = 120

# InterceptionKeyStroke state
_KEY_DOWN = 0
_KEY_UP = 1
_KEY_E0 = 0x02  # extended prefix (arrows, Win, Insert, …)

# InterceptionMouseFlag
_FLAG_MOVE_RELATIVE = 0x000
_FLAG_MOVE_ABSOLUTE = 0x001

_FILTER_MOUSE_ALL = 0xFFFF
_STATE_RIGHT_BUTTON_UP = 0x004
_STATE_MIDDLE_BUTTON_UP = 0x006

# VK -> PS/2 "make" scancode for the keys the bot injects into the game.
# Values may be int (non-extended) or (scancode, extended:bool).
_VK_SCAN = {
    0x11: 0x1D,  # Ctrl
    0x56: 0x2F,  # V (paste)
    0x41: 0x1E,  # A (select-all)
    0x0D: 0x1C,  # Enter
    0x09: 0x0F,  # Tab
    0x20: 0x39,  # Space
    0x08: 0x0E,  # Backspace
    0x2A: 0x2A,  # Shift (left) - PS/2 Left Shift make = 0x2A
    0x10: 0x2A,  # Shift (VK code alias)
    0x2E: 0x53,  # Delete
    0x12: 0x38,  # Alt (left)
    0x1B: 0x01,  # Esc
    0x5B: (0x5B, True),  # Left Win (E0 5B)
    0x28: (0x50, True),  # Down arrow (E0 50) — Win+Down minimize
    # Digits
    0x30: 0x0B,  # 0
    0x31: 0x02,  # 1
    0x32: 0x03,  # 2
    0x33: 0x04,  # 3
    0x34: 0x05,  # 4
    0x35: 0x06,  # 5
    0x36: 0x07,  # 6
    0x37: 0x08,  # 7
    0x38: 0x09,  # 8
    0x39: 0x0A,  # 9
    # Letters (uppercase VK codes = same scancodes as lowercase)
    0x41: 0x1E,  # A/a
    0x42: 0x30,  # B/b
    0x43: 0x2E,  # C/c
    0x44: 0x20,  # D/d
    0x45: 0x12,  # E/e
    0x46: 0x21,  # F/f
    0x47: 0x22,  # G/g
    0x48: 0x23,  # H/h
    0x49: 0x17,  # I/i
    0x4A: 0x24,  # J/j
    0x4B: 0x25,  # K/k
    0x4C: 0x26,  # L/l
    0x4D: 0x32,  # M/m
    0x4E: 0x31,  # N/n
    0x4F: 0x18,  # O/o
    0x50: 0x19,  # P/p
    0x51: 0x10,  # Q/q
    0x52: 0x13,  # R/r
    0x53: 0x1F,  # S/s
    0x54: 0x14,  # T/t
    0x55: 0x16,  # U/u
    0x56: 0x2F,  # V/v
    0x57: 0x11,  # W/w
    0x58: 0x2D,  # X/x
    0x59: 0x15,  # Y/y
    0x5A: 0x2C,  # Z/z
    # Punctuation
    0xBD: 0x0C,  # - (minus/underscore)
    0xBB: 0x0D,  # = (plus/equals)
    0xDB: 0x1A,  # [ {
    0xDD: 0x1B,  # ] }
    0xDC: 0x2B,  # \ |
    0xBA: 0x27,  # ; :
    0xDE: 0x28,  # ' "
    0xBC: 0x33,  # , <
    0xBE: 0x34,  # . >
    0xBF: 0x35,  # / ?
    0xC0: 0x29,  # ` ~
}

_GAP_MS = 0.012


class _MouseStroke(ctypes.Structure):
    _fields_ = [
        ("state", ctypes.c_ushort),
        ("flags", ctypes.c_ushort),
        ("rolling", ctypes.c_short),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("information", ctypes.c_uint),
    ]


class _KeyStroke(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("state", ctypes.c_ushort),
        ("information", ctypes.c_uint),
    ]


_lib = None
_ctx = None
_screen_w = 1920
_screen_h = 1080
_mouse_device = None      # probed device slot that actually accepts strokes
_keyboard_device = None


def _probe_devices():
    """Find the device slots that really exist on this machine.

    Interception reserves slots 1-10 for keyboards and 11-20 for mice, but
    which slot a physical device occupies varies per machine (e.g. the mouse
    on this PC answers on 12, not 11). Sending to an empty slot returns 0.

    Probes are harmless: a key-UP stroke for a key that is not pressed is
    ignored by the OS, and a mouse move to the CURRENT cursor position does
    not move anything."""
    global _mouse_device, _keyboard_device
    _keyboard_device = None
    _mouse_device = None
    for dev in range(_KB_MIN, _KB_MAX + 1):
        ks = _KeyStroke()
        ks.code = 0x04            # 'a' scancode, UP state -> no-op
        ks.state = _KEY_UP
        if _lib.interception_send(_ctx, dev, ctypes.byref(ks), 1) == 1:
            _keyboard_device = dev
            break
    cx, cy = _cursor_pos()
    nx, ny = _norm(cx, cy)
    for dev in range(_MOUSE_MIN, _MOUSE_MAX + 1):
        s = _MouseStroke()
        s.state = _STATE_MOVE
        s.flags = _FLAG_MOVE_ABSOLUTE
        s.x, s.y = nx, ny
        if _lib.interception_send(_ctx, dev, ctypes.byref(s), 1) == 1:
            _mouse_device = dev
            break
    import logging
    logging.getLogger(__name__).info(
        "interception devices: keyboard=%s mouse=%s",
        _keyboard_device, _mouse_device)


def init():
    global _lib, _ctx, _screen_w, _screen_h
    if _ctx:
        return True
    # Cache the failure so a missing/blocked driver is not re-loaded and
    # re-logged on every keystroke/click - that produced the repeated
    # 'interception_create_context returned 0' spam during credential entry.
    if init._failed:
        return False
    try:
        _lib = ctypes.WinDLL(_DLL_PATH)
        _lib.interception_create_context.restype = ctypes.c_void_p
        _lib.interception_create_context.argtypes = []
        _lib.interception_destroy_context.argtypes = [ctypes.c_void_p]
        _lib.interception_send.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        _lib.interception_send.restype = ctypes.c_int
        _lib.interception_wait_with_timeout.restype = ctypes.c_int
        _lib.interception_wait_with_timeout.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
        ]
        _lib.interception_receive.restype = ctypes.c_int
        _lib.interception_receive.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint,
        ]

        _ctx = _lib.interception_create_context()
        if not _ctx:
            import logging
            logging.getLogger(__name__).warning("interception_create_context returned 0")
            init._failed = True
            return False

        user32 = ctypes.windll.user32
        _screen_w = user32.GetSystemMetrics(0)
        _screen_h = user32.GetSystemMetrics(1)
        _probe_devices()
        return True
    except Exception as _ex:
        import logging
        logging.getLogger(__name__).warning("interception init failed: %r", _ex)
        _ctx = None
        init._failed = True
        return False


init._failed = False


def ready() -> bool:
    return bool(_ctx)


def _norm(x: int, y: int):
    nx = int(x * 65535 // max(_screen_w - 1, 1))
    ny = int(y * 65535 // max(_screen_h - 1, 1))
    nx = min(max(nx, 0), 65535)
    ny = min(max(ny, 0), 65535)
    return nx, ny


def _send(state: int, nx: int, ny: int) -> bool:
    if not _ctx or _lib is None or _mouse_device is None:
        return False
    stroke = _MouseStroke()
    stroke.state = state
    stroke.flags = _FLAG_MOVE_ABSOLUTE
    stroke.x = nx
    stroke.y = ny
    n = _lib.interception_send(
        _ctx, _mouse_device, ctypes.byref(stroke), 1)
    return n == 1


def move(x: int, y: int):
    """Absolute mouse move to screen pixel (x, y)."""
    nx, ny = _norm(x, y)
    if _send(_STATE_MOVE, nx, ny):
        time.sleep(_GAP_MS)


def _cursor_pos():
    class _Pt(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = _Pt()
    user32 = ctypes.windll.user32
    if user32.GetCursorPos(ctypes.byref(pt)):
        return pt.x, pt.y
    return 0, 0


def click(x: int, y: int, steps: int = 3):
    """Absolute mouse move (with small interpolation for realism) then a
    left click, all via the Interception driver at screen pixels (x, y)."""
    if not _ctx:
        return False
    nx, ny = _norm(x, y)
    cx, cy = _cursor_pos()
    cx, cy = _norm(cx, cy)
    for i in range(1, steps + 1):
        t = i / steps
        ix = int(cx + t * (nx - cx))
        iy = int(cy + t * (ny - cy))
        if not _send(_STATE_MOVE, ix, iy):
            return False
        time.sleep(_GAP_MS)
    if not _send(_STATE_LEFT_BUTTON_DOWN, nx, ny):
        return False
    time.sleep(_GAP_MS)
    if not _send(_STATE_LEFT_BUTTON_UP, nx, ny):
        return False
    time.sleep(_GAP_MS)
    return True


def double_click(x: int, y: int, steps: int = 3, gap: float = 0.09) -> bool:
    """Two left clicks at the same screen point, inside the double-click window.

    The second click stays in place so the game treats it as a double-click
    on the character portrait instead of a second hover-then-click.
    """
    if not click(x, y, steps=steps):
        return False
    time.sleep(gap)
    nx, ny = _norm(x, y)
    if not _send(_STATE_LEFT_BUTTON_DOWN, nx, ny):
        return False
    time.sleep(_GAP_MS)
    if not _send(_STATE_LEFT_BUTTON_UP, nx, ny):
        return False
    time.sleep(_GAP_MS)
    return True


def button_down(x: int, y: int) -> bool:
    """Device-level left-button press at screen pixel (x, y). Used for drags:
    move() to the grab point, button_down(), move() along the path, button_up()."""
    if not _ctx:
        return False
    nx, ny = _norm(x, y)
    if not _send(_STATE_LEFT_BUTTON_DOWN, nx, ny):
        return False
    time.sleep(_GAP_MS)
    return True


def button_up(x: int, y: int) -> bool:
    """Device-level left-button release at screen pixel (x, y)."""
    if not _ctx:
        return False
    nx, ny = _norm(x, y)
    if not _send(_STATE_LEFT_BUTTON_UP, nx, ny):
        return False
    time.sleep(_GAP_MS)
    return True


def wheel(notches: float, x: int = None, y: int = None) -> bool:
    """Device-level vertical wheel scroll via the Interception driver.

    Positive `notches` scrolls up (away from the user), negative scrolls
    down (standard Windows wheel delta convention: +120 per notch). When
    (x, y) is given the cursor is moved there first so the event lands on
    the window under that point."""
    if not _ctx:
        return False
    if x is not None and y is not None:
        move(x, y)
    if _mouse_device is None:
        return False
    stroke = _MouseStroke()
    stroke.state = _STATE_WHEEL
    stroke.flags = _FLAG_MOVE_ABSOLUTE
    stroke.rolling = int(_WHEEL_DELTA * notches)
    if x is not None and y is not None:
        stroke.x, stroke.y = _norm(x, y)
    n = _lib.interception_send(
        _ctx, _mouse_device, ctypes.byref(stroke), 1)
    time.sleep(_GAP_MS)
    return n == 1


def _key_send(code: int, state: int) -> bool:
    """Send one keyboard stroke (scancode `code`, down/up) on the probed
    keyboard device via the Interception driver. True if accepted."""
    if not _ctx or _lib is None or _keyboard_device is None:
        return False
    stroke = _KeyStroke()
    stroke.code = code
    stroke.state = state
    n = _lib.interception_send(
        _ctx, _keyboard_device, ctypes.byref(stroke), 1)
    return n == 1


def _vk_stroke(vk: int):
    """Return (scancode, base_state_flags) or None if VK unknown."""
    entry = _VK_SCAN.get(vk)
    if entry is None:
        return None
    if isinstance(entry, tuple):
        code, extended = entry
        return int(code), (_KEY_E0 if extended else 0)
    return int(entry), 0


def key_down(vk: int) -> bool:
    stroke = _vk_stroke(vk)
    if stroke is None or not _ctx:
        return False
    code, eflags = stroke
    if not _key_send(code, _KEY_DOWN | eflags):
        return False
    time.sleep(_GAP_MS)
    return True


def key_up(vk: int) -> bool:
    stroke = _vk_stroke(vk)
    if stroke is None or not _ctx:
        return False
    code, eflags = stroke
    if not _key_send(code, _KEY_UP | eflags):
        return False
    time.sleep(_GAP_MS)
    return True


def tap(vk: int) -> bool:
    """Press and release a virtual key via the driver (device-level input)."""
    if not key_down(vk):
        return False
    key_up(vk)
    time.sleep(0.03)
    return True


# ---- character-level typing via Interception ----------------------------
# Maps each printable character to (needs_shift, vk_code) for US layout.
_CHAR_MAP = {}
_shift_chars = r'~!@#$%^&*()_+{}|:"<>?ABCDEFGHIJKLMNOPQRSTUVWXYZ'
_normal_chars = r"`1234567890-=[]\;',./abcdefghijklmnopqrstuvwxyz "
_vk_for = {
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
    '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39, '0': 0x30,
    '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
    '`': 0xC0, ' ': 0x20,
}
for _c, _vk in _vk_for.items():
    _CHAR_MAP[_c] = (False, _vk)
    if _c.isalpha():
        _CHAR_MAP[_c.upper()] = (True, _vk)
# shift-row symbols
_shift_map = {
    '!': 0x31, '@': 0x32, '#': 0x33, '$': 0x34, '%': 0x35,
    '^': 0x36, '&': 0x37, '*': 0x38, '(': 0x39, ')': 0x30,
    '_': 0xBD, '+': 0xBB, '{': 0xDB, '}': 0xDD, '|': 0xDC,
    ':': 0xBA, '"': 0xDE, '<': 0xBC, '>': 0xBE, '?': 0xBF,
    '~': 0xC0,
}
for _c, _vk in _shift_map.items():
    _CHAR_MAP[_c] = (True, _vk)


def type_char(ch: str) -> bool:
    """Type a single ASCII character via the Interception driver."""
    entry = _CHAR_MAP.get(ch)
    if entry is None:
        return False
    need_shift, vk = entry
    if need_shift:
        key_down(0x2A)  # Shift
    key_down(vk)
    key_up(vk)
    if need_shift:
        key_up(0x2A)
    time.sleep(0.02)
    return True


def type_string(text: str) -> bool:
    """Type a string character-by-character via the Interception driver.
    Completely bypasses UIPI — device-level keyboard input."""
    if not _ctx:
        return False
    for ch in text:
        if not type_char(ch):
            return False
    return True


# ---- input capture (recording real hardware events) ---------------------
# The driver delivers a copy of every REAL keyboard/mouse stroke to any open
# context while the original still reaches the OS, so reading events here
# never blocks or duplicates the user's own input. Injected (SendInput)
# events are NOT visible on this channel — only physical hardware.

MOUSE_STATE_NAMES = {
    0x000: "move",
    0x001: "left_down",
    0x002: "left_up",
    0x003: "right_down",
    0x004: "right_up",
    0x005: "middle_down",
    0x006: "middle_up",
    0x007: "wheel",
    0x008: "hwheel",
}

FLAG_MOVE_ABSOLUTE = 0x001
FLAG_VIRTUAL_DESKTOP = 0x002


def next_event(timeout_ms: int = 25):
    """Wait up to timeout_ms for one hardware input event.

    Returns a dict:
      {"kind": "key",  "device", "code" (scancode), "state" (0 down/1 up),
       "information"}
      {"kind": "mouse","device", "state", "flags", "rolling",
       "x", "y" (raw), "information"}
    or None on timeout / when the driver is not initialized."""
    if not (_ctx and _lib):
        return None
    dev = int(_lib.interception_wait_with_timeout(_ctx, timeout_ms))
    if not 1 <= dev <= 20:
        return None
    if dev <= 10:
        stroke = _KeyStroke()
        if _lib.interception_receive(_ctx, dev, ctypes.byref(stroke), 1) != 1:
            return None
        return {"kind": "key", "device": dev, "code": int(stroke.code),
                "state": int(stroke.state),
                "information": int(stroke.information)}
    stroke = _MouseStroke()
    if _lib.interception_receive(_ctx, dev, ctypes.byref(stroke), 1) != 1:
        return None
    return {"kind": "mouse", "device": dev, "state": int(stroke.state),
            "flags": int(stroke.flags), "rolling": int(stroke.rolling),
            "x": int(stroke.x), "y": int(stroke.y),
            "information": int(stroke.information)}


def neutralize() -> None:
    """Lift modifiers and mouse buttons this context may have left down."""
    if not _ctx:
        return
    for vk in (0x12, 0x11, 0x10, 0x5B, 0x5C):
        try:
            key_up(vk)
        except Exception:
            pass
    if _lib is None or _mouse_device is None:
        return
    cx, cy = _cursor_pos()
    nx, ny = _norm(cx, cy)
    for state in (_STATE_LEFT_BUTTON_UP, _STATE_RIGHT_BUTTON_UP, _STATE_MIDDLE_BUTTON_UP):
        try:
            _send(state, nx, ny)
        except Exception:
            pass


def shutdown():
    """Destroy the capture context (safe to call multiple times)."""
    global _ctx, _mouse_device, _keyboard_device
    neutralize()
    if _ctx and _lib is not None:
        try:
            _lib.interception_destroy_context(_ctx)
        except Exception:
            pass
    _ctx = None
    _mouse_device = None
    _keyboard_device = None
    init._failed = False
