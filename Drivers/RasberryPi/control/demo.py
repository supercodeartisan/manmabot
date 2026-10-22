# -*- coding: utf-8 -*-
"""
control.demo — 하드웨어 없이 프로토콜/전송/서버/클라이언트 전체 경로와
               지연시간을 실측하는 데모.

실행:  python -m control.demo        (또는  python control/demo.py)
"""

import os
import sys
import threading
import time

# 단독 실행 대비 경로 보정
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from control import (ControlClient, ControlServer, MemoryTransport,
                         NullBackend, TcpListener, tcp_connect)
    from control import protocol as P
else:
    from . import protocol as P
    from .client import ControlClient
    from .server import ControlServer
    from .transport import MemoryTransport, TcpListener, tcp_connect
    from .backend import NullBackend


def _run_server(server, stop_event):
    server.backend.begin()
    while not stop_event.is_set():
        server.step()


def bench_memory(samples=500):
    a, b = MemoryTransport.pair()          # a: client, b: server
    backend = NullBackend()
    server = ControlServer(b, backend, poll=0.0005)
    stop = threading.Event()
    th = threading.Thread(target=_run_server, args=(server, stop), daemon=True)
    th.start()
    client = ControlClient(a)
    client.set_screen(1920, 1080)

    # API 동작 확인
    client.move_click(300, 200, hold_ms=10)
    client.type_text("hello")
    client.hotkey(0xE0, 0x06)   # Ctrl+C
    time.sleep(0.05)
    action_count = backend.count

    rtt = client.ping(samples=samples, timeout=2.0)
    stop.set()
    th.join(timeout=0.5)
    return rtt, action_count, backend


def bench_tcp(samples=500):
    listener = TcpListener("127.0.0.1", 0)
    port = listener.sock.getsockname()[1]

    accepted = {}

    def acceptor():
        tr, _ = listener.accept()
        backend = NullBackend()
        server = ControlServer(tr, backend, poll=0.0002)
        accepted["server"] = server
        accepted["backend"] = backend
        _run_server(server, accepted["stop"])

    accepted["stop"] = threading.Event()
    th = threading.Thread(target=acceptor, daemon=True)
    th.start()

    client = ControlClient(tcp_connect("127.0.0.1", port))
    time.sleep(0.05)
    rtt = client.ping(samples=samples, timeout=2.0)

    client.set_screen(1920, 1080)
    client.move_click(800, 600, hold_ms=15)
    client.type_text("tcp")
    client.wheel(-1)
    time.sleep(0.15)
    backend = accepted.get("backend")

    accepted["stop"].set()
    listener.close()
    return rtt, backend


def bench_codec(n=100000):
    t0 = time.perf_counter()
    frames = 0
    for i in range(n):
        f = P.encode(P.T_MOUSE_ABS, i, P.pack(P.T_MOUSE_ABS, i & 0xFFFF, 0))
        frames += 1
    enc = (time.perf_counter() - t0) / n * 1e6
    parser = P.FrameParser()
    buf = P.encode(P.T_MOUSE_ABS, 1, P.pack(P.T_MOUSE_ABS, 10, 20))
    t0 = time.perf_counter()
    for i in range(n):
        parser.feed(buf)
    dec = (time.perf_counter() - t0) / n * 1e6
    return enc, dec


def fmt(rtt):
    if rtt is None:
        return "실패"
    if isinstance(rtt, tuple):
        return "min %.3f / avg %.3f / max %.3f ms" % rtt
    return "%.3f ms" % rtt


def bench_robust():
    """손상된 프레임을 섞어도 파서가 재동기화하여 정상 프레임을 복구하는지 확인."""
    parser = P.FrameParser()
    g1 = P.encode(P.T_MOUSE_REL, 1, P.pack(P.T_MOUSE_REL, 5, 5))
    bad = bytearray(P.encode(P.T_MOUSE_REL, 2, P.pack(P.T_MOUSE_REL, 9, 9)))
    bad[14] ^= 0xFF                       # 중간 프레임 페이로드 1바이트 훼손
    g2 = P.encode(P.T_MOUSE_REL, 3, P.pack(P.T_MOUSE_REL, 7, 7))
    frames = parser.feed(g1 + bytes(bad) + g2)
    return frames, parser.frames_ok, parser.frames_bad


class _SimCursor(object):
    """가속을 흉내내는 시뮬레이션 커서 (실제 커서는 움직이지 않음)."""
    def __init__(self):
        self.pos = (0, 0)

    def position(self):
        return self.pos

    def apply(self, dx, dy):
        def f(d):
            if d == 0:
                return 0
            a = 1.0 + min(abs(d), 200) / 200.0 * 0.6   # 큰 이동일수록 가속
            return int(d * a)
        self.pos = (self.pos[0] + f(dx), self.pos[1] + f(dy))


class _FakeClient(object):
    def __init__(self, cur):
        self.cur = cur
        self.moves = 0

    def move_rel(self, dx, dy):
        self.moves += 1
        self.cur.apply(dx, dy)

    def click(self, mask=None, hold_ms=30):
        pass


def bench_feedback(target=(640, 400)):
    from control.feedback import FeedbackController
    # 오픈루프(피드백 없음): 한 번에 이동 -> 가속 때문에 오차 발생
    cur = _SimCursor()
    _FakeClient(cur).move_rel(target[0], target[1])
    open_err = (cur.pos[0] - target[0], cur.pos[1] - target[1])
    # 폐루프(피드백): 실제 위치를 매번 읽어 보정 -> 정확 수렴
    cur2 = _SimCursor()
    fc = FeedbackController(_FakeClient(cur2), cur2, settle=0.0)
    ok, pos, iters = fc.move_abs(target[0], target[1], tolerance=2)
    return open_err, ok, pos, iters


class _GuardClient(object):
    """GuardedController 테스트용 가짜 클라이언트(시뮬레이션 커서를 직접 이동)."""
    def __init__(self, cur):
        self.cur = cur
        self.pressed = []

    def move_abs(self, x, y):
        self.cur.pos = (int(x), int(y))

    def move_rel(self, dx, dy):
        self.cur.pos = (self.cur.pos[0] + int(dx), self.cur.pos[1] + int(dy))

    def click(self, mask=1, hold_ms=30):
        pass

    def button(self, mask, action, hold_ms=0):
        if action == 1:
            self.pressed.append(("btn", mask))

    def key_down(self, code, modifier=0):
        self.pressed.append(("key", code))

    def key_up(self, code, modifier=0):
        pass

    def wheel(self, dy):
        pass

    def set_screen(self, w, h):
        pass


def bench_guard(pause_hold=0.3, resume_idle=0.6):
    import time
    from control.guard import InputGuard, GuardedController
    cur = _SimCursor()
    client = _GuardClient(cur)
    guard = InputGuard(cur, pause_hold=pause_hold, resume_idle=resume_idle,
                       threshold=5, poll=0.01)
    gc = GuardedController(client, guard).start()
    time.sleep(0.05)
    ok1 = gc.move_abs(100, 100)                    # 정상 진행
    time.sleep(0.05)
    ok2 = gc.move_abs(110, 110)                    # 정상 진행
    cur.pos = (500, 500)                           # === 사용자가 마우스를 확 잡아끎 ===
    time.sleep(0.15)
    blocked = (gc.move_abs(120, 120, timeout=0.1) is False)   # 정지중 -> 전송 안 됨
    time.sleep(pause_hold + resume_idle + 0.25)    # 사용자가 멈춤 -> 대기
    resumed = gc.move_abs(130, 130)                # 재개 -> 전송됨
    gc.stop()
    return ok1, ok2, blocked, resumed, guard.pause_count, guard.resume_count


def bench_sequence():
    """UI 시퀀스 실행 로직을 하드웨어 없이 검증(가상 링크 + NullBackend)."""
    import time
    from control.sequence import execute_step
    a, b = MemoryTransport.pair()
    backend = NullBackend()
    server = ControlServer(b, backend, poll=0.0005)
    stop = threading.Event()
    threading.Thread(target=_run_server, args=(server, stop), daemon=True).start()
    c = ControlClient(a)
    c.set_screen(1920, 1080)
    seq = [
        {"t": 0.00, "kind": "move", "x": 100, "y": 100},
        {"t": 0.05, "kind": "click", "x": 100, "y": 100, "mask": 1, "hold": 20},
        {"t": 0.10, "kind": "dclick", "x": 200, "y": 150, "mask": 1},
        {"t": 0.20, "kind": "drag", "x": 300, "y": 300, "x2": 360, "y2": 330, "duration": 64, "mask": 1},
        {"t": 0.35, "kind": "wheel", "dy": -2},
        {"t": 0.40, "kind": "key", "key": "enter"},
        {"t": 0.45, "kind": "hotkey", "hotkey": "ctrl+c"},
        {"t": 0.50, "kind": "text", "text": "hi", "cps": 50},
    ]
    start = time.perf_counter()
    for s in seq:
        while (start + s["t"]) - time.perf_counter() > 0:
            time.sleep(0.002)
        execute_step(c, s)
    time.sleep(0.3)
    stop.set()
    return backend.history


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("=" * 62)
    print(" control demo — 저지연 입력주입 파이프라인 검증")
    print("=" * 62)

    enc, dec = bench_codec()
    print("[코덱] 인코딩 %.3f us/frame, 디코딩 %.3f us/frame" % (enc, dec))

    rtt_mem, acts, backend = bench_memory()
    print("[메모리 전송 RTT] %s   (기록된 동작 %d개)" % (fmt(rtt_mem), acts))
    print("  수신된 지령:")
    for item in backend.history:
        print("    ", item)

    rtt_tcp, backend_tcp = bench_tcp()
    print("[TCP localhost RTT] %s   (기록된 동작 %d개)"
          % (fmt(rtt_tcp), backend_tcp.count if backend_tcp else 0))
    if backend_tcp:
        print("  수신된 지령:")
        for item in backend_tcp.history:
            print("    ", item)

    frames, ok, badn = bench_robust()
    print("[안정성] 손상1 + 정상2 혼합 -> 복구 %d개, CRC거부 %d개, 복구값 %s"
          % (len(frames), badn, [P.unpack(f[0], f[2]) for f in frames]))

    oerr, fok, fpos, fit = bench_feedback()
    print("[피드백] 오픈루프 오차 %s  ->  폐루프 성공=%s 위치=%s 반복=%d회"
          % (oerr, fok, fpos, fit))

    g1, g2, gblocked, gresumed, gp, gr = bench_guard()
    print("[중재기] 정상전송=%s,%s 정지중차단=%s 재개후전송=%s (정지 %d회/재개 %d회)"
          % (g1, g2, gblocked, gresumed, gp, gr))

    seq = bench_sequence()
    kinds = [item[0] for item in seq]
    print("[시퀀스] 수신 동작 %d개 (일부: %s)" % (len(seq), ", ".join(kinds[:12])))

    print("-" * 62)
    print("참고 지연 예산(실제 하드웨어):")
    print("  * USB HID 폴링(PC)        : 약 1 ms (1 kHz)")
    print("  * 시리얼 115200 전송(소형) : < 0.5 ms")
    print("  * 서버 처리(디코딩+주입)   : 위 디코딩 수치 수준")
    print("  => 로컬(USB 직결) 총 지령->실행 지연: 대략 수 ms 이내")
    print("     (원격은 네트워크 RTT 가 지배 → TCP_NODELAY / UDP 권장)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
