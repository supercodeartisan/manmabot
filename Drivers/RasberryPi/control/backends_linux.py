# -*- coding: utf-8 -*-
"""
control.backends_linux — 라즈베리파이 OS(리눅스)용 커널 uinput 백엔드

  * '하드웨어 준위' 입력 주입: /dev/uinput 로 실제 입력장치를 생성 -> OS 는 진짜 마우스/키보드로 인식
  * 의존성: python-evdev  (예: sudo apt install python3-evdev  또는  pip install evdev)
  * 권한  : /dev/uinput 접근 필요 (root 또는 udev 규칙). 미충족 시 예외 안내.

키코드는 프로토콜 표준인 'USB HID usage id' 를 쓰고, 여기서 리눅스 keycode 로 변환한다.
  -> Pico(CircuitPython usb_hid) 와 동일한 지령을 그대로 사용 가능(결합성).
"""

from .backend import HidBackend, AbsoluteTracker

try:
    from evdev import UInput, ecodes as e
    _HAVE_EVDEV = True
except Exception:  # pragma: no cover
    _HAVE_EVDEV = False

# --- USB HID usage -> Linux keycode ---
_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_LCODES = [30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25,
           16, 19, 31, 20, 22, 47, 17, 45, 21, 44]
_DIGITS = "1234567890"
_DCODES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
_SHIFTED = "!@#$%^&*()"
_PUNCT = {"-": 12, "=": 13, "[": 26, "]": 27, "\\": 43, ";": 39, "'": 40,
          "`": 41, ",": 51, ".": 52, "/": 53}
_PUNCT_SHIFT = {"_": 12, "+": 13, "{": 26, "}": 27, "|": 43, ":": 39, '"': 40,
                "~": 41, "<": 51, ">": 52, "?": 53}

KEY_LEFTSHIFT = 42

HID_TO_LINUX = {
    0x28: 28, 0x29: 1, 0x2A: 14, 0x2B: 15, 0x2C: 57, 0x39: 58,
    0x4F: 106, 0x50: 105, 0x51: 108, 0x52: 103, 0x49: 110, 0x4A: 102,
    0x4B: 104, 0x4C: 111, 0x4D: 107, 0x4E: 109,
    0xE0: 29, 0xE1: 42, 0xE2: 56, 0xE3: 125, 0xE4: 97, 0xE5: 54, 0xE6: 100, 0xE7: 126,
}
for i, ch in enumerate(_LETTERS):
    HID_TO_LINUX[0x04 + i] = _LCODES[i]
for i, ch in enumerate(_DIGITS):
    HID_TO_LINUX[0x1E + i] = _DCODES[i]
HID_TO_LINUX.update({0x2D: 12, 0x2E: 13, 0x2F: 26, 0x30: 27, 0x31: 43, 0x33: 39,
                     0x34: 40, 0x35: 41, 0x36: 51, 0x37: 52, 0x38: 53})
for i in range(12):  # F1..F12
    HID_TO_LINUX[0x3A + i] = [59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 87, 88][i]

# 문자 -> (keycode, shift)
CHAR_MAP = {}
for i, ch in enumerate(_LETTERS):
    CHAR_MAP[ch] = (_LCODES[i], 0)
    CHAR_MAP[ch.upper()] = (_LCODES[i], 1)
for i, ch in enumerate(_DIGITS):
    CHAR_MAP[ch] = (_DCODES[i], 0)
for i, ch in enumerate(_SHIFTED):
    CHAR_MAP[ch] = (_DCODES[i], 1)
for ch, code in _PUNCT.items():
    CHAR_MAP[ch] = (code, 0)
for ch, code in _PUNCT_SHIFT.items():
    CHAR_MAP[ch] = (code, 1)
CHAR_MAP[" "] = (57, 0)
CHAR_MAP["\n"] = (28, 0)
CHAR_MAP["\t"] = (15, 0)

_BTN = {0x01: 272, 0x02: 273, 0x04: 274}  # BTN_LEFT/RIGHT/MIDDLE


class UinputBackend(HidBackend):
    def __init__(self, screen=(1920, 1080), absolute=False, name="control-hid"):
        if not _HAVE_EVDEV:
            raise ImportError(
                "python-evdev 가 필요합니다:  sudo apt install python3-evdev  (또는 pip install evdev)"
            )
        self.tracker = AbsoluteTracker(screen)
        self.absolute = absolute
        self.name = name
        self.ui = None

    def begin(self):
        keys = list(set(HID_TO_LINUX.values())) + list(_BTN.values()) + [KEY_LEFTSHIFT]
        caps = {e.EV_KEY: sorted(set(keys))}
        if self.absolute:
            try:
                from evdev import AbsInfo
            except Exception:                      # 일부 버전 경로
                from evdev.evdev import AbsInfo
            w, h = self.tracker.screen
            caps[e.EV_ABS] = [
                (e.ABS_X, AbsInfo(value=0, min=0, max=w - 1, fuzz=0, flat=0, resolution=0)),
                (e.ABS_Y, AbsInfo(value=0, min=0, max=h - 1, fuzz=0, flat=0, resolution=0)),
            ]
            caps[e.EV_REL] = [e.REL_WHEEL]         # 휠은 상대값 유지
        else:
            caps[e.EV_REL] = [e.REL_X, e.REL_Y, e.REL_WHEEL]
        self.ui = UInput(caps, name=self.name)

    def _syn(self):
        self.ui.syn()

    def move_rel(self, dx, dy):
        if dx:
            self.ui.write(e.EV_REL, e.REL_X, int(dx))
        if dy:
            self.ui.write(e.EV_REL, e.REL_Y, int(dy))
        self._syn()

    def move_abs(self, x, y):
        if self.absolute:
            w, h = self.tracker.screen
            x = max(0, min(w - 1, int(x)))
            y = max(0, min(h - 1, int(y)))
            self.ui.write(e.EV_ABS, e.ABS_X, x)
            self.ui.write(e.EV_ABS, e.ABS_Y, y)
            self._syn()
            self.tracker.pos = [x, y]
        else:
            self.move_rel(*self.tracker.to_rel(x, y))

    def button(self, mask, action, hold_ms=0):
        val = 1 if action != 0 else 0
        for bit, code in _BTN.items():
            if mask & bit:
                self.ui.write(e.EV_KEY, code, val)
        self._syn()

    def wheel(self, dy):
        self.ui.write(e.EV_REL, e.REL_WHEEL, int(dy))
        self._syn()

    def key(self, keycode, modifier=0, action=2, hold_ms=0):
        codes = []
        if modifier:
            for hid, lin in HID_TO_LINUX.items():
                if hid >= 0xE0 and (modifier & (1 << (hid - 0xE0))):
                    codes.append(lin)
        lin = HID_TO_LINUX.get(keycode)
        if lin:
            codes.append(lin)
        val = 1 if action != 0 else 0
        for c in codes:
            self.ui.write(e.EV_KEY, c, val)
        self._syn()

    def key_text(self, s):
        self.type_text(s, 0)

    def type_text(self, s, cps=0):
        import time as _t
        interval = (1.0 / cps) if cps and cps > 0 else 0.004
        for ch in s:
            code, shift = CHAR_MAP.get(ch, (None, 0))
            if code is None:
                continue
            t0 = _t.perf_counter()
            if shift:
                self.ui.write(e.EV_KEY, KEY_LEFTSHIFT, 1)
            self.ui.write(e.EV_KEY, code, 1)
            self._syn()
            _t.sleep(0.002)
            self.ui.write(e.EV_KEY, code, 0)
            if shift:
                self.ui.write(e.EV_KEY, KEY_LEFTSHIFT, 0)
            self._syn()
            rest = interval - (_t.perf_counter() - t0)
            if rest > 0:
                _t.sleep(rest)

    def set_screen(self, w, h):
        # 절대모드(absolute=True)에서는 begin() 전에 호출해야 absinfo 범위에 반영된다.
        self.tracker.set_screen(w, h)

    def close(self):
        try:
            if self.ui:
                self.ui.close()
        except Exception:
            pass
