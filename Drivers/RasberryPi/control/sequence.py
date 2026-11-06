# -*- coding: utf-8 -*-
"""
control.sequence — 시퀀스 스텝 실행 (UI / 테스트 공용)

스텝(dict) 예:
  {"t":0.0, "kind":"click", "x":100,"y":200, "mask":1, "hold":30}
  {"t":0.5, "kind":"drag", "x":..,"y":..,"x2":..,"y2":..,"duration":300}
  {"t":1.0, "kind":"hotkey","hotkey":"ctrl+shift+s"}
  {"t":1.2, "kind":"text","text":"hello","cps":8}

c 는 ControlClient / GuardedController / FeedbackController 어느 것이어도 된다.
"""

import time

from . import keys as K


def execute_step(c, s):
    k = s.get("kind")
    if k == "move":
        c.move_abs(s["x"], s["y"])
    elif k == "click":
        c.move_abs(s["x"], s["y"])
        c.click(s.get("mask", 1), s.get("hold", 30))
    elif k == "dclick":
        c.move_abs(s["x"], s["y"])
        c.click(s.get("mask", 1), 25)
        time.sleep(0.06)
        c.click(s.get("mask", 1), 25)
    elif k == "drag":
        c.move_abs(s["x"], s["y"])
        c.button_down(s.get("mask", 1))
        dur = max(1, int(s.get("duration", 300)))
        n = max(2, int(dur // 16))
        for i in range(1, n + 1):
            f = i / float(n)
            c.move_abs(int(s["x"] + (s["x2"] - s["x"]) * f),
                       int(s["y"] + (s["y2"] - s["y"]) * f))
            time.sleep(dur / 1000.0 / n)
        c.button_up(s.get("mask", 1))
    elif k == "wheel":
        c.wheel(s["dy"])
    elif k == "key":
        c.key(K.parse_key(s["key"]))
    elif k == "hotkey":
        codes = K.parse_hotkey(s["hotkey"])
        for code in codes:
            c.key_down(code)
        for code in reversed(codes):
            c.key_up(code)
    elif k == "text":
        c.type_text(s["text"], s.get("cps", 0))
    elif k == "wait":
        time.sleep(s.get("duration", 0) / 1000.0)
