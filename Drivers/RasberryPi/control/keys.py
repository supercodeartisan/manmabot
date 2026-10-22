# -*- coding: utf-8 -*-
"""
control.keys — 키 이름 <-> USB HID usage 코드 (UI/스크립트 입력용)

  parse_key("enter") -> 0x28
  parse_key("0x04")  -> 0x04
  parse_hotkey("ctrl+shift+s") -> [0xE0, 0xE1, 0x16]
"""

# 이름 -> HID usage id
KEYCODES = {
    "enter": 0x28, "return": 0x28, "esc": 0x29, "escape": 0x29,
    "backspace": 0x2A, "tab": 0x2B, "space": 0x2C, "capslock": 0x39,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B, "delete": 0x4C,
    "end": 0x4D, "pagedown": 0x4E, "right": 0x4F, "left": 0x50,
    "down": 0x51, "up": 0x52,
    # 수정자(단독/조합)
    "ctrl": 0xE0, "control": 0xE0, "leftctrl": 0xE0,
    "shift": 0xE1, "leftshift": 0xE1,
    "alt": 0xE2, "leftalt": 0xE2,
    "win": 0xE3, "gui": 0xE3, "meta": 0xE3, "leftgui": 0xE3,
    "rightctrl": 0xE4, "rightshift": 0xE5, "rightalt": 0xE6, "rightgui": 0xE7,
    # 기호
    "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31,
    ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEYCODES[_c] = 0x04 + _i
for _i, _c in enumerate("1234567890"):
    KEYCODES[_c] = 0x1E + _i
for _i in range(1, 13):
    KEYCODES["f%d" % _i] = 0x3A + (_i - 1)

MODIFIER_BITS = {
    0xE0: 0x01, 0xE1: 0x02, 0xE2: 0x04, 0xE3: 0x08,
    0xE4: 0x10, 0xE5: 0x20, 0xE6: 0x40, 0xE7: 0x80,
}


def parse_key(name):
    n = str(name).strip().lower()
    if n in KEYCODES:
        return KEYCODES[n]
    if n.startswith("0x"):
        return int(n, 16)
    if len(n) == 1:
        return KEYCODES.get(n, ord(n))
    raise ValueError("알 수 없는 키 이름: %r" % name)


def parse_hotkey(expr):
    """'ctrl+shift+s', 'ctrl-c', 'alt+F4' 등을 코드 리스트로."""
    out = []
    for part in str(expr).replace(" ", "").split("+"):
        if not part:
            continue
        # 'ctrl-c' 형태도 허용(수정자+키)
        if "-" in part and part.lower() not in KEYCODES:
            for sub in part.split("-"):
                if sub:
                    out.append(parse_key(sub))
        else:
            out.append(parse_key(part))
    return out


def modifier_mask(codes):
    m = 0
    for c in codes:
        m |= MODIFIER_BITS.get(c, 0)
    return m
