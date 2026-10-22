# -*- coding: utf-8 -*-
"""Break down aim latency: open-loop ABS vs closed-loop feedback."""
from __future__ import annotations

import sys
import time
import ctypes
from ctypes import wintypes

sys.path.insert(0, r"D:\Rasberrypi")
from control import ControlClient, SerialTransport
from control import protocol as P
from control.feedback import FeedbackController, local_cursor
from control.pointer import no_pointer_accel

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


def wait_for_burst(dist: int, per_chunk_ms: float = 1.0, slack_ms: float = 3.0) -> float:
    chunks = max(1, (abs(dist) + 126) // 127)
    # firmware sleeps 1ms per chunk; USB poll ~1ms
    s = (chunks * per_chunk_ms + slack_ms) / 1000.0
    time.sleep(s)
    return s


def main() -> int:
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    print("SCREEN", w, h)
    c = ControlClient(SerialTransport("COM5", 115200))
    c.set_screen(w, h)
    time.sleep(0.05)
    targets = [
        (w // 2, h // 2),
        (200, 200),
        (1700, 900),
        (400, 800),
        (1500, 300),
    ]
    try:
        with no_pointer_accel():
            print("\n=== A) OPEN-LOOP SYNC+ABS (wait=f(dist), firmware 1ms/chunk) ===")
            for tx, ty in targets:
                a = cursor()
                dist = max(abs(a[0] - tx), abs(a[1] - ty))
                t0 = time.perf_counter()
                c.move_abs(tx, ty, resync=True)
                waited = wait_for_burst(dist)
                b = cursor()
                ms = (time.perf_counter() - t0) * 1000
                e = max(abs(b[0] - tx), abs(b[1] - ty))
                chunks = max(1, (dist + 126) // 127)
                print(
                    f"  {a}->{(tx,ty)} pos={b} err={e} dist={dist} chunks~{chunks} "
                    f"wait_ms={waited*1000:.1f} total_ms={ms:.1f} {'OK' if e<=2 else 'FAIL'}"
                )

            print("\n=== B) OPEN-LOOP + 1 correction if err>2 ===")
            for tx, ty in targets:
                a = cursor()
                dist = max(abs(a[0] - tx), abs(a[1] - ty))
                t0 = time.perf_counter()
                c.move_abs(tx, ty, resync=True)
                wait_for_burst(dist)
                b = cursor()
                e = max(abs(b[0] - tx), abs(b[1] - ty))
                corr = 0
                if e > 2:
                    dx, dy = tx - b[0], ty - b[1]
                    c.move_rel(dx, dy)
                    wait_for_burst(max(abs(dx), abs(dy)))
                    b = cursor()
                    e = max(abs(b[0] - tx), abs(b[1] - ty))
                    corr = 1
                ms = (time.perf_counter() - t0) * 1000
                print(
                    f"  target={(tx,ty)} pos={b} err={e} corr={corr} total_ms={ms:.1f} "
                    f"{'OK' if e<=2 else 'FAIL'}"
                )

            print("\n=== C) FeedbackController settle=12ms factor=0.5 (current smoke) ===")
            fc = FeedbackController(c, local_cursor(), settle=0.012)
            for tx, ty in targets[:3]:
                t0 = time.perf_counter()
                ok, pos, n = fc.move_abs(tx, ty, tolerance=2, max_iter=25)
                ms = (time.perf_counter() - t0) * 1000
                e = max(abs(pos[0] - tx), abs(pos[1] - ty))
                print(f"  target={(tx,ty)} pos={pos} err={e} iters={n} total_ms={ms:.1f} OK={ok}")

            print("\n=== D) FeedbackController settle=2ms factor=1.0 max_step=127 ===")
            fc2 = FeedbackController(c, local_cursor(), settle=0.002)
            for tx, ty in targets[:3]:
                t0 = time.perf_counter()
                ok, pos, n = fc2.move_abs(
                    tx, ty, tolerance=2, max_iter=8, max_step=127, factor=1.0
                )
                ms = (time.perf_counter() - t0) * 1000
                e = max(abs(pos[0] - tx), abs(pos[1] - ty))
                print(f"  target={(tx,ty)} pos={pos} err={e} iters={n} total_ms={ms:.1f} OK={ok}")

            print("\n=== E) RAW REL single 127 (measure HID settle) ===")
            for _ in range(3):
                a = cursor()
                t0 = time.perf_counter()
                c.move_rel(127, 0)
                # poll until moved or 30ms
                b = a
                for _ in range(40):
                    b = cursor()
                    if b[0] != a[0]:
                        break
                    time.sleep(0.0005)
                ms = (time.perf_counter() - t0) * 1000
                print(f"  {a}->{b} dx={b[0]-a[0]} detect_ms={ms:.2f}")

    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
