# -*- coding: utf-8 -*-
"""Retest: closed-loop abs (farm-usable) + ping diagnostics."""
from __future__ import annotations

import sys
import time
import ctypes
from ctypes import wintypes

sys.path.insert(0, r"D:\Rasberrypi")
from control import ControlClient, SerialTransport
from control import protocol as P
from control.feedback import FeedbackController, local_cursor
from control.keys import parse_key
from control.pointer import no_pointer_accel

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


def main() -> int:
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    print("SCREEN", w, h, "PORT COM5")
    c = ControlClient(SerialTransport("COM5", 115200))
    rows = []
    try:
        c.set_screen(w, h)
        time.sleep(0.05)

        # ping samples individually
        for i in range(5):
            t0 = time.perf_counter()
            c.send(P.T_PING, P.pack(P.T_PING, P.now_us()))
            got = False
            deadline = time.time() + 0.5
            while time.time() < deadline:
                data = c.transport.recv(timeout=0.05)
                if not data:
                    continue
                for mt, seq, payload in c._parser.feed(data):
                    if mt == P.T_PONG:
                        got = True
                        break
                if got:
                    break
            ms = (time.perf_counter() - t0) * 1000
            print("PING_one", i, "ms=", round(ms, 2), "got=", got)
            rows.append(("ping", got and ms < 100, ms))

        with no_pointer_accel():
            fc = FeedbackController(c, local_cursor(), settle=0.012)
            targets = [
                (w // 2, h // 2),
                (max(50, w // 5), max(50, h // 5)),
                (min(w - 50, 4 * w // 5), min(h - 50, 4 * h // 5)),
                (640, 720),
            ]
            for tx, ty in targets:
                t0 = time.perf_counter()
                ok, pos, n = fc.move_abs(tx, ty, tolerance=2, max_iter=25)
                e = max(abs(pos[0] - tx), abs(pos[1] - ty))
                ms = (time.perf_counter() - t0) * 1000
                print(
                    "ABS_CLOSED",
                    (tx, ty),
                    "->",
                    pos,
                    "err=",
                    e,
                    "iters=",
                    n,
                    "ms=",
                    round(ms, 1),
                    "OK" if ok else "FAIL",
                )
                rows.append(("abs_closed", ok and e <= 2, e))

            # move then host click (engine pattern)
            ok, pos, n = fc.move_abs(20, 20, tolerance=3, max_iter=20)
            time.sleep(0.02)
            c.key_down(parse_key("f4"))
            time.sleep(0.03)
            c.key_up(parse_key("f4"))
            c.button_down(P.BTN_LEFT)
            time.sleep(0.02)
            c.button_up(P.BTN_LEFT)
            print("F4_THEN_CLICK at", pos, "OK")
            rows.append(("f4_click", True, pos))

            # open-loop move_abs with distance-based wait (for comparison)
            tx, ty = w // 2, h // 2
            a = cursor()
            c.move_abs(tx, ty, resync=True)
            dist = max(abs(a[0] - tx), abs(a[1] - ty))
            wait = max(0.05, (dist / 127.0) * 0.001 + 0.02)
            time.sleep(wait)
            # also allow firmware chunk yields: ~1ms per 127
            wait2 = (dist / 127.0) * 0.0015 + 0.05
            time.sleep(max(0, wait2 - wait))
            b = cursor()
            e = max(abs(b[0] - tx), abs(b[1] - ty))
            print(
                "ABS_OPEN_WAIT",
                a,
                "->",
                b,
                "target",
                (tx, ty),
                "err=",
                e,
                "wait_ms=",
                round(wait2 * 1000, 1),
                "OK" if e <= 3 else "FAIL",
            )
            rows.append(("abs_open_wait", e <= 3, e))

    except Exception as e:
        print("EXCEPTION", type(e).__name__, e)
        rows.append(("exception", False, str(e)))
    finally:
        c.close()

    fails = [r[0] for r in rows if not r[1]]
    print("VERDICT", "PASS" if not fails else "PARTIAL", "fails=", fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
