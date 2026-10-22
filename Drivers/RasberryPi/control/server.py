# -*- coding: utf-8 -*-
"""
control.server — 라즈베리파이 측: 지령 수신 -> 하드웨어 입력 주입

저지연 설계
  * 수신 루프는 절대 블로킹하지 않음 (transport.recv(timeout=poll))
  * '누르는 시간(hold)' 은 sleep 대신 '예약 해제' 큐로 처리 -> 다음 지령이 즉시 실행
  * ACK 없음(기본). 필요하면 PING/PONG 으로 지연·생존 확인

결합성
  * server.register(TYPE, handler) 로 새 명령을 언제든 추가
  * transport / backend 를 생성자로 주입 -> 임의 모듈과 조합
"""

import time

from . import protocol as P


class ControlServer(object):
    def __init__(self, transport, backend, on_event=None, poll=0.001):
        self.transport = transport
        self.backend = backend
        self.poll = poll
        self._running = False
        self._parser = P.FrameParser()
        self._seq = 0
        self._pending = []          # (due_time, callable) : hold 해제 예약
        self._handlers = {}         # type -> handler(seq, payload)
        self._on_event = on_event   # 사이드 채널(모니터링/결합) 콜백
        self.stats = {"commands": 0, "bad": 0, "pong": 0}
        self._register_defaults()

    # ------------------------------------------------------------ 확장점
    def register(self, msg_type, handler):
        """새 명령 타입 등록. handler(seq, payload)."""
        self._handlers[msg_type] = handler

    def _register_defaults(self):
        self.register(P.T_PING, self._on_ping)
        self.register(P.T_MOUSE_ABS, lambda s, p: self.backend.move_abs(*P.unpack(P.T_MOUSE_ABS, p)))
        self.register(P.T_MOUSE_REL, lambda s, p: self.backend.move_rel(*P.unpack(P.T_MOUSE_REL, p)))
        self.register(P.T_MOUSE_BTN, self._on_button)
        self.register(P.T_MOUSE_WHEEL, lambda s, p: self.backend.wheel(*P.unpack(P.T_MOUSE_WHEEL, p)))
        self.register(P.T_KEY, self._on_key)
        self.register(P.T_KEY_TEXT, lambda s, p: self.backend.key_text(*P.unpack(P.T_KEY_TEXT, p)))
        self.register(P.T_TYPE, lambda s, p: self.backend.type_text(
            P.unpack(P.T_TYPE, p)[1], P.unpack(P.T_TYPE, p)[0]))
        self.register(P.T_SET_SCREEN, lambda s, p: self.backend.set_screen(*P.unpack(P.T_SET_SCREEN, p)))
        self.register(P.T_SYNC, lambda s, p: self.backend.sync())

    # ------------------------------------------------------------ 기본 핸들러
    def _on_ping(self, seq, payload):
        (t0,) = P.unpack(P.T_PING, payload)
        self.stats["pong"] += 1
        self._send(P.T_PONG, P.pack(P.T_PONG, t0, P.now_us()))

    def _on_button(self, seq, payload):
        mask, action, hold = P.unpack(P.T_MOUSE_BTN, payload)
        if action == P.ACT_PRESS:
            self.backend.button(mask, P.ACT_DOWN, hold)
            self._schedule(max(hold, 1), lambda: self.backend.button(mask, P.ACT_UP, 0))
        else:
            self.backend.button(mask, action, hold)

    def _on_key(self, seq, payload):
        code, mod, action, hold = P.unpack(P.T_KEY, payload)
        if action == P.ACT_PRESS:
            self.backend.key(code, mod, P.ACT_DOWN, hold)
            self._schedule(max(hold, 1), lambda: self.backend.key(code, mod, P.ACT_UP, 0))
        else:
            self.backend.key(code, mod, action, hold)

    # ------------------------------------------------------------ 내부
    def _schedule(self, delay_ms, fn):
        self._pending.append((time.perf_counter() + delay_ms / 1000.0, fn))

    def _run_due(self):
        if not self._pending:
            return
        now = time.perf_counter()
        rest = []
        for due, fn in self._pending:
            if due <= now:
                try:
                    fn()
                except Exception:
                    pass
            else:
                rest.append((due, fn))
        self._pending = rest

    def _send(self, msg_type, payload):
        frame = P.encode(msg_type, self._seq, payload)
        self._seq = (self._seq + 1) & 0xFFFFFFFF
        self.transport.send(frame)

    # ------------------------------------------------------------ 루프
    def step(self):
        """한 번 수신/실행. (직접 호출 제어 가능 -> 임의 루프와 결합)"""
        try:
            data = self.transport.recv(timeout=self.poll)
        except Exception:
            self._running = False      # 연결 종료/오류 -> 조용히 정지
            return
        if data:
            for msg_type, seq, payload in self._parser.feed(data):
                handler = self._handlers.get(msg_type)
                if handler is None:
                    continue
                try:
                    handler(seq, payload)
                    self.stats["commands"] += 1
                except Exception as e:
                    if self._on_event:
                        self._on_event("error", (msg_type, str(e)))
        self._run_due()
        self.stats["bad"] = self._parser.frames_bad

    def run(self, duration=None):
        """기본 실행 루프. stop() 또는 duration(초) 까지."""
        self.backend.begin()
        self._running = True
        end = None if duration is None else time.perf_counter() + duration
        try:
            while self._running and (end is None or time.perf_counter() < end):
                self.step()
        finally:
            self.backend.close()
            self._running = False

    def stop(self):
        self._running = False
