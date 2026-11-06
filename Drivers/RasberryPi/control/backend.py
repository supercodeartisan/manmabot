# -*- coding: utf-8 -*-
"""
control.backend — 하드웨어 준위 입력 주입 백엔드 인터페이스 (결합용)

HidBackend 만 구현하면 임의의 하드웨어/드라이버를 붙일 수 있다:
    NullBackend     : 로그만 남김(테스트/지연측정)
    UinputBackend   : 리눅스 커널 uinput (라즈베리파이 OS)  [backends_linux.py]
    (Pico)          : control/pico/main.py 가 usb_hid 로 동일 프로토콜 처리

HidBackend 는 '상대 이동'만 필수로 구현하면 되고, 절대좌표는
AbsoluteTracker 가 현재 커서 위치를 추적해 상대 델타로 변환해 준다.
"""

import time


class HidBackend(object):
    supports_absolute = False  # True 면 move_abs 를 직접 처리(예: 리눅스 EV_ABS)

    def begin(self):
        pass

    # --- 필수: 상대 이동/버튼/휠/키 ---
    def move_rel(self, dx, dy):
        raise NotImplementedError

    def button(self, mask, action, hold_ms=0):
        raise NotImplementedError

    def wheel(self, dy):
        pass

    def key(self, keycode, modifier=0, action=2, hold_ms=0):
        raise NotImplementedError

    def key_text(self, s):
        raise NotImplementedError

    def type_text(self, s, cps=0):
        """건별 타이핑 속도(cps) 지정 버전. 기본은 key_text 로 위임."""
        self.key_text(s)

    # --- 선택 ---
    def set_screen(self, w, h):
        pass

    def move_abs(self, x, y):
        # 기본: 상대 이동으로 변환
        raise NotImplementedError

    def sync(self):
        pass

    def close(self):
        pass


class AbsoluteTracker(object):
    """절대 픽셀좌표를 상대 델타로 변환하기 위한 위치 추적기."""
    def __init__(self, screen=(1920, 1080)):
        self.screen = tuple(screen)
        self.pos = [0, 0]

    def set_screen(self, w, h):
        self.screen = (int(w), int(h))

    def to_rel(self, x, y):
        x = max(0, min(self.screen[0] - 1, int(x)))
        y = max(0, min(self.screen[1] - 1, int(y)))
        dx = x - self.pos[0]
        dy = y - self.pos[1]
        self.pos = [x, y]
        return dx, dy


class NullBackend(HidBackend):
    """하드웨어 없이 동작 확인/지연측정용. 모든 동작을 history 에 기록."""
    def __init__(self, screen=(1920, 1080), verbose=False, max_history=1000,
                 on_action=None):
        self.tracker = AbsoluteTracker(screen)
        self.verbose = verbose
        self.max_history = max_history
        self.on_action = on_action
        self.history = []
        self.last = None
        self.count = 0

    def _rec(self, item):
        self.count += 1
        self.last = item
        if len(self.history) < self.max_history:
            self.history.append(item)
        if self.on_action is not None:
            try:
                self.on_action(item)
            except Exception:
                pass

    def move_abs(self, x, y):
        dx, dy = self.tracker.to_rel(x, y)
        self.move_rel(dx, dy)
        self.history[-1] = ("move_abs", x, y)

    def move_rel(self, dx, dy):
        self._rec(("move_rel", dx, dy))

    def button(self, mask, action, hold_ms=0):
        self._rec(("button", mask, ["up", "down", "press"][action] if action < 3 else action))

    def wheel(self, dy):
        self._rec(("wheel", dy))

    def key(self, keycode, modifier=0, action=2, hold_ms=0):
        self._rec(("key", hex(keycode), "mod=%d" % modifier,
                   ["up", "down", "press"][action] if action < 3 else action))

    def key_text(self, s):
        self._rec(("text", s))

    def type_text(self, s, cps=0):
        self._rec(("type", s, cps))

    def set_screen(self, w, h):
        self.tracker.set_screen(w, h)
        self._rec(("screen", w, h))

    def sync(self):
        self._rec(("sync",))
