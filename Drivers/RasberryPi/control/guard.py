# -*- coding: utf-8 -*-
"""
control.guard — 사용자 마우스 간섭 시 자동 일시정지/재개 (충돌 방지)

동작
  * 감시 스레드가 '실제 커서 위치'를 주기적으로 읽는다.
  * 우리가 명령한 예상 위치(expected)와 다르게 움직이면 = 사용자가 개입한 것 -> 일시정지.
  * 사용자가 멈춘 뒤 resume_idle 초가 지나고, 정지 시작 후 pause_hold 초가 지나면 재개.
  * 일시정지 동안에는 지령을 보내지 않고(대기), 눌려 있던 버튼/키는 자동 해제한다.

사용자가 설정하는 두 시간
  * pause_hold  : 사용자 개입 후 최소 이만큼은 멈춘다        (몇초간 중지)
  * resume_idle : 마우스가 멈춘 뒤 이만큼 지나면 재개한다      (몇초 후부터 진행)

탐지 방식
  기본은 '예상 대비 커서 이탈'이다. 정확한 위치보장(1방안 피드백/3방안 절대장치)과
  결합하면 가장 안정적이다. 클릭/키보드처럼 커서를 움직이지 않는 입력까지 잡고 싶으면
  activity_probe 훅(대상측 후킹/raw input)을 주입하면 된다.
"""

import contextlib
import threading
import time


class InputGuard(object):
    def __init__(self, cursor, pause_hold=1.0, resume_idle=3.0,
                 threshold=6, poll=0.02, on_pause=None, on_resume=None,
                 activity_probe=None):
        self.cursor = cursor
        self.pause_hold = float(pause_hold)      # 사용자 설정 1
        self.resume_idle = float(resume_idle)    # 사용자 설정 2
        self.threshold = int(threshold)
        self.poll = float(poll)
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.activity_probe = activity_probe     # optional: callable()->bool

        self._expected = None
        self._last_actual = None
        self._paused = False
        self._pause_start = None
        self._last_user_activity = None
        self._busy = False
        self._stop = False
        self._lock = threading.Lock()
        self._thread = None
        self.pause_count = 0
        self.resume_count = 0

    # ---------------- 컨트롤러가 명령 시 알려줌 ----------------
    def note_expected(self, x, y):
        with self._lock:
            self._expected = (int(x), int(y))

    def note_relative(self, dx, dy):
        with self._lock:
            base = self._expected or self._last_actual or (0, 0)
            self._expected = (base[0] + int(dx), base[1] + int(dy))

    def clear_expected(self):
        with self._lock:
            self._expected = None

    # ---------------- 상태 ----------------
    @property
    def paused(self):
        return self._paused

    def wait(self, timeout=None):
        """일시정지 중이면 풀릴 때까지 대기. (정지 상태로 시간초과 시 False)"""
        end = None if timeout is None else time.time() + timeout
        while self._paused and not self._stop:
            if end is not None and time.time() >= end:
                return False
            time.sleep(0.005)
        return not self._paused

    @contextlib.contextmanager
    def busy(self):
        """여러 단계 이동(피드백 등) 동안에는 우리 이동으로 간주해 오탐을 막는다."""
        with self._lock:
            self._busy = True
        try:
            yield
        finally:
            with self._lock:
                self._busy = False

    # ---------------- 감시 스레드 ----------------
    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop = True

    def _run(self):
        while not self._stop:
            try:
                self._poll_once()
            except Exception:
                pass
            time.sleep(self.poll)

    def _poll_once(self):
        now = time.time()
        cur = self.cursor.position()
        user = False
        with self._lock:
            exp = self._expected
            busy = self._busy
        if self.activity_probe is not None:
            try:
                user = bool(self.activity_probe())
            except Exception:
                user = False
        if not user and not busy:
            if exp is not None:
                # 우리 예상 위치에서 벗어난 '변화' = 사용자 개입
                moved = (abs(cur[0] - exp[0]) > self.threshold or
                         abs(cur[1] - exp[1]) > self.threshold)
                with self._lock:
                    prev = self._last_actual
                # 커서가 실제로 '변했는지'도 확인(정지 상태 오탐 방지)
                changed = (prev is None or abs(cur[0] - prev[0]) > self.threshold or
                           abs(cur[1] - prev[1]) > self.threshold)
                user = moved and changed
        with self._lock:
            self._last_actual = cur
            if user:
                self._last_user_activity = now
                if not self._paused:
                    self._paused = True
                    self._pause_start = now
                    self.pause_count += 1
                    cb = self.on_pause
                else:
                    cb = None
            else:
                cb = None
                if self._paused:
                    hold_ok = (now - self._pause_start) >= self.pause_hold
                    idle_ok = (self._last_user_activity is None or
                               (now - self._last_user_activity) >= self.resume_idle)
                    if hold_ok and idle_ok:
                        self._paused = False
                        self.resume_count += 1
                        cb = self.on_resume
        if cb:
            try:
                cb()
            except Exception:
                pass

    def note_user_pause(self):
        """외부에서 수동으로 '사용자 개입'을 알릴 때."""
        with self._lock:
            self._last_user_activity = time.time()
            if not self._paused:
                self._paused = True
                self._pause_start = time.time()
                self.pause_count += 1


class GuardedController(object):
    """ControlClient + InputGuard 결합.

      * 일시정지 중에는 지령을 보내지 않고 '재개될 때까지 대기'한다.
      * 정지로 들어가는 순간 눌려 있던 버튼/키를 자동 해제한다(키 눌림 방지).
      * 나머지 API 는 ControlClient 와 동일하지만 반환값으로 전송 여부(True/False)를 준다.
    """
    def __init__(self, client, guard, on_pause=None, on_resume=None):
        self.client = client
        self.guard = guard
        self._btns = 0
        self._keys = {}
        self._prev_pause = guard.on_pause
        self._prev_resume = guard.on_resume
        self._user_pause = on_pause
        self._user_resume = on_resume
        guard.on_pause = self._handle_pause
        guard.on_resume = self._handle_resume

    # ----- 정지/재개 콜백 -----
    def _handle_pause(self):
        self._release_all()
        for cb in (self._prev_pause, self._user_pause):
            if cb:
                try:
                    cb()
                except Exception:
                    pass

    def _handle_resume(self):
        for cb in (self._prev_resume, self._user_resume):
            if cb:
                try:
                    cb()
                except Exception:
                    pass

    def _release_all(self):
        try:
            if self._btns:
                self.client.button(self._btns, 0)
                self._btns = 0
            for code, mod in list(self._keys.keys()):
                self.client.key_up(code, mod)
            self._keys.clear()
        except Exception:
            pass

    def _go(self, timeout=None):
        return self.guard.wait(timeout)

    # ----- API (정지 중이면 대기) -----
    def move_abs(self, x, y, timeout=None):
        if not self._go(timeout):
            return False
        with self.guard.busy():
            self.client.move_abs(x, y)
            self.guard.note_expected(x, y)
        return True

    def move_rel(self, dx, dy, timeout=None):
        if not self._go(timeout):
            return False
        with self.guard.busy():
            self.client.move_rel(dx, dy)
            self.guard.note_relative(dx, dy)
        return True

    def set_screen(self, w, h, timeout=None):
        if not self._go(timeout):
            return False
        self.client.set_screen(w, h)
        return True

    def click(self, mask=1, hold_ms=30, timeout=None):
        if not self._go(timeout):
            return False
        self.client.click(mask, hold_ms)
        return True

    def move_click(self, x, y, mask=1, hold_ms=30, timeout=None):
        if not self._go(timeout):
            return False
        with self.guard.busy():
            self.client.move_abs(x, y)
            self.guard.note_expected(x, y)
            self.client.click(mask, hold_ms)
        return True

    def button_down(self, mask=1, timeout=None):
        if not self._go(timeout):
            return False
        self.client.button(mask, 1)
        self._btns |= mask
        return True

    def button_up(self, mask=1, timeout=None):
        self.client.button(mask, 0)
        self._btns &= ~mask
        return True

    def wheel(self, dy, timeout=None):
        if not self._go(timeout):
            return False
        self.client.wheel(dy)
        return True

    def key_down(self, code, modifier=0, timeout=None):
        if not self._go(timeout):
            return False
        self.client.key_down(code, modifier)
        self._keys[(code, modifier)] = True
        return True

    def key_up(self, code, modifier=0, timeout=None):
        self.client.key_up(code, modifier)
        self._keys.pop((code, modifier), None)
        return True

    def key(self, code, modifier=0, hold_ms=0, timeout=None):
        if not self._go(timeout):
            return False
        self.client.key(code, modifier, hold_ms)
        return True

    def hotkey(self, *keys, timeout=None):
        if not self._go(timeout):
            return False
        self.client.hotkey(*keys)
        return True

    def type_text(self, s, timeout=None):
        if not self._go(timeout):
            return False
        self.client.type_text(s)
        return True

    def sync(self):
        self.client.sync()

    def start(self):
        self.guard.start()
        return self

    def stop(self):
        self.guard.stop()
        self._release_all()


def guard_client(client, cursor, pause_hold=1.0, resume_idle=3.0,
                 threshold=6, poll=0.02, feedback=False):
    """편의 팩토리.

    사용자가 설정하는 두 시간:
      pause_hold  : 사용자 개입 후 최소 이만큼 멈춤 (초)
      resume_idle : 마우스가 멈춘 뒤 이만큼 지나면 재개 (초)

    feedback=True 로 주면 1방안(절대좌표 폐루프)과 결합된다.
    반환: (GuardedController, InputGuard)
    """
    if feedback:
        from .feedback import FeedbackController
        client = FeedbackController(client, cursor)
    guard = InputGuard(cursor, pause_hold=pause_hold, resume_idle=resume_idle,
                       threshold=threshold, poll=poll)
    return GuardedController(client, guard), guard
