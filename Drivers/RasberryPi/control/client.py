# -*- coding: utf-8 -*-
"""
control.client — 컴퓨터 측: 라즈베리파이로 지령 전송

저지연
  * send(): 프레임 1개를 즉시 write
  * send_many(): 여러 명령을 하나의 write 로 묶음(시스템콜/프레임오버헤드 절감)
  * ping(): 왕복 지연(RTT) 실측 -> 통신 안정성/품질 확인

결합성
  * 생성자에 임의의 Transport 주입
  * 고수준 API(move_abs/click/key/type_text ...)는 임의 파이프라인에서 그대로 호출
"""

import time

from . import protocol as P


class ControlClient(object):
    def __init__(self, transport):
        self.transport = transport
        self._seq = 0
        self._parser = P.FrameParser()
        self.sent = 0
        self.sent_bytes = 0
        self._hid_mode = None  # "ABS" | "REL" | None (unknown)

    # ------------------------------------------------------------ 저수준
    def _next_seq(self):
        s = self._seq
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        return s

    def send(self, msg_type, payload=b""):
        frame = P.encode(msg_type, self._next_seq(), payload)
        self.transport.send(frame)
        self.sent += 1
        self.sent_bytes += len(frame)
        return frame

    def send_many(self, items):
        """items: [(msg_type, payload), ...] 를 한 번의 write 로 전송."""
        buf = []
        for msg_type, payload in items:
            buf.append(P.encode(msg_type, self._next_seq(), payload))
            self.sent += 1
        blob = b"".join(buf)
        self.transport.send(blob)
        self.sent_bytes += len(blob)
        return len(buf)

    def close(self):
        self.transport.close()

    # ------------------------------------------------------------ 고수준 API
    def set_screen(self, w, h):
        self.send(P.T_SET_SCREEN, P.pack(P.T_SET_SCREEN, w, h))

    def reset_board(self):
        """Full microcontroller.reset() so boot.py re-runs (HID re-enumerate)."""
        self.send(P.T_RESET, b"")

    def get_mode(self, timeout=1.0):
        """Firmware HID mode: 'ABS' or 'REL' (or None on timeout)."""
        self.send(P.T_GET_MODE, b"")
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            data = self.transport.recv(timeout=0.05)
            if not data:
                continue
            for msg_type, seq, payload in self._parser.feed(data):
                if msg_type == P.T_GET_MODE:
                    text = payload.decode("utf-8", "replace")
                    mode = text.split(";", 1)[0].strip()
                    if mode in ("ABS", "REL"):
                        self._hid_mode = mode
                    return text
        return None

    def ensure_mode(self, timeout=1.5):
        if self._hid_mode in ("ABS", "REL"):
            return self._hid_mode
        text = self.get_mode(timeout=timeout)
        if text:
            return text.split(";", 1)[0].strip()
        return None

    def move_abs(self, x, y, resync=True):
        """Pixel move. resync=True sends SYNC with live cursor first (REL firmware)."""
        if resync:
            try:
                from .feedback import local_cursor

                cx, cy = local_cursor().position()
                self.send(P.T_SYNC, P.pack(P.T_SYNC, cx, cy))
            except Exception:
                pass
        self.send(P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, int(x) & 0xFFFF, int(y) & 0xFFFF))

    def move_abs_aim(
        self,
        x,
        y,
        *,
        tolerance=2,
        timeout_s=None,
        correct=None,
        resync=None,
    ):
        """Farm aim: prefer true ABS (1 HID report); REL burst is fallback.

        ABS board: no SYNC and no relative correction. The click that follows
        uses the cursor's real position, so this waits until that position
        matches. A 15ms give-up left the talking-scroll click on the hover row.
        REL board: SYNC + burst + poll + optional one REL correction.
        Returns (ok, (px, py), elapsed_ms, corrections).
        """
        from .feedback import local_cursor

        x, y = int(x), int(y)
        cur = local_cursor()
        mode = self._hid_mode
        if mode not in ("ABS", "REL"):
            mode = self.ensure_mode(timeout=0.8) or "REL"

        if timeout_s is None:
            timeout_s = 0.12
        if correct is None:
            correct = mode != "ABS"
        if resync is None:
            resync = mode != "ABS"

        t0 = time.perf_counter()
        corrections = 0

        # Fast path: absolute HID one-shot (no SYNC)
        self.move_abs(x, y, resync=False)
        deadline = t0 + float(timeout_s)
        pos = cur.position()
        while time.perf_counter() < deadline:
            pos = cur.position()
            if abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance:
                if mode != "ABS":
                    self._hid_mode = "ABS"
                ms = (time.perf_counter() - t0) * 1000.0
                return True, pos, ms, corrections
            time.sleep(0.002)

        # The list click is one row under the hover. Resend once and settle.
        if mode == "ABS" and not correct:
            self.move_abs(x, y, resync=False)
            deadline = time.perf_counter() + 0.08
            while time.perf_counter() < deadline:
                pos = cur.position()
                if abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance:
                    ms = (time.perf_counter() - t0) * 1000.0
                    return True, pos, ms, corrections
                time.sleep(0.002)
            pos = cur.position()
            ok = abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance
            ms = (time.perf_counter() - t0) * 1000.0
            return ok, pos, ms, corrections

        self.move_abs(x, y, resync=True if resync else False)
        deadline = time.perf_counter() + float(timeout_s)
        while time.perf_counter() < deadline:
            pos = cur.position()
            if abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance:
                ms = (time.perf_counter() - t0) * 1000.0
                return True, pos, ms, corrections
            time.sleep(0.0005)

        if correct:
            pos = cur.position()
            dx, dy = x - pos[0], y - pos[1]
            if abs(dx) > tolerance or abs(dy) > tolerance:
                self.move_rel(dx, dy)
                corrections = 1
                deadline = time.perf_counter() + 0.05
                while time.perf_counter() < deadline:
                    pos = cur.position()
                    if abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance:
                        ms = (time.perf_counter() - t0) * 1000.0
                        return True, pos, ms, corrections
                    time.sleep(0.0005)
        pos = cur.position()
        ok = abs(pos[0] - x) <= tolerance and abs(pos[1] - y) <= tolerance
        ms = (time.perf_counter() - t0) * 1000.0
        return ok, pos, ms, corrections

    def move_rel(self, dx, dy):
        dx = max(-32767, min(32767, int(dx)))
        dy = max(-32767, min(32767, int(dy)))
        self.send(P.T_MOUSE_REL, P.pack(P.T_MOUSE_REL, dx, dy))

    def button(self, mask, action, hold_ms=0):
        self.send(P.T_MOUSE_BTN, P.pack(P.T_MOUSE_BTN, mask, action, hold_ms))

    def button_down(self, mask=P.BTN_LEFT):
        self.button(mask, P.ACT_DOWN)

    def button_up(self, mask=P.BTN_LEFT):
        self.button(mask, P.ACT_UP)

    def click(self, mask=P.BTN_LEFT, hold_ms=30):
        self.button(mask, P.ACT_PRESS, hold_ms)

    def move_click(self, x, y, mask=P.BTN_LEFT, hold_ms=30, resync=True):
        items = []
        if resync:
            try:
                from .feedback import local_cursor

                cx, cy = local_cursor().position()
                items.append((P.T_SYNC, P.pack(P.T_SYNC, cx, cy)))
            except Exception:
                pass
        items.append(
            (P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, int(x) & 0xFFFF, int(y) & 0xFFFF))
        )
        items.append(
            (P.T_MOUSE_BTN, P.pack(P.T_MOUSE_BTN, mask, P.ACT_PRESS, hold_ms))
        )
        self.send_many(items)

    def wheel(self, dy):
        self.send(P.T_MOUSE_WHEEL, P.pack(P.T_MOUSE_WHEEL, int(dy)))

    def key(self, keycode, modifier=0, hold_ms=0):
        self.send(P.T_KEY, P.pack(P.T_KEY, keycode & 0xFF, modifier & 0xFF, P.ACT_PRESS, hold_ms))

    def key_down(self, keycode, modifier=0):
        self.send(P.T_KEY, P.pack(P.T_KEY, keycode & 0xFF, modifier & 0xFF, P.ACT_DOWN, 0))

    def key_up(self, keycode, modifier=0):
        self.send(P.T_KEY, P.pack(P.T_KEY, keycode & 0xFF, modifier & 0xFF, P.ACT_UP, 0))

    def hotkey(self, *keys):
        """예: hotkey(0xE0, 0x06) == Ctrl+C  (down 순차 -> up 역순)"""
        items = [(P.T_KEY, P.pack(P.T_KEY, k & 0xFF, 0, P.ACT_DOWN, 0)) for k in keys]
        items += [(P.T_KEY, P.pack(P.T_KEY, k & 0xFF, 0, P.ACT_UP, 0)) for k in reversed(keys)]
        self.send_many(items)

    def type_text(self, s, cps=0):
        """문자열 입력. cps>0 이면 서버가 그 속도(글자/초)로 건별 타이핑."""
        if cps and cps > 0:
            self.send(P.T_TYPE, P.pack(P.T_TYPE, int(cps), s))
        else:
            self.send(P.T_KEY_TEXT, P.pack(P.T_KEY_TEXT, s))

    def sync(self, x=None, y=None):
        """Flush / release. With x,y: realign firmware cursor tracker."""
        if x is None or y is None:
            self.send(P.T_SYNC, b"")
        else:
            self.send(P.T_SYNC, P.pack(P.T_SYNC, x, y))

    # ------------------------------------------------------------ 지연 측정
    def ping(self, timeout=1.0, samples=1):
        """왕복 지연(ms). samples>1 이면 최소/평균/최대 튜플 반환."""
        rtts = []
        for _ in range(max(1, samples)):
            t0 = time.perf_counter()
            self.send(P.T_PING, P.pack(P.T_PING, P.now_us()))
            frame = None
            deadline = time.time() + timeout
            while time.time() < deadline:
                data = self.transport.recv(timeout=0.05)
                if not data:
                    continue
                for msg_type, seq, payload in self._parser.feed(data):
                    if msg_type == P.T_PONG:
                        frame = payload
                        break
                if frame is not None:
                    break
            if frame is None:
                rtts.append(None)
            else:
                rtts.append((time.perf_counter() - t0) * 1000.0)
        if samples == 1:
            return rtts[0]
        vals = [r for r in rtts if r is not None]
        if not vals:
            return None
        return (min(vals), sum(vals) / len(vals), max(vals))
