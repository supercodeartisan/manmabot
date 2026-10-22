# -*- coding: utf-8 -*-
"""Isolate ABS vs REL burst vs serial blocking."""
from __future__ import annotations

import sys
import time
import ctypes
from ctypes import wintypes

sys.path.insert(0, r"D:\Rasberrypi")
from control import ControlClient, SerialTransport
from control import protocol as P
from control.feedback import local_cursor
from control.pointer import no_pointer_accel

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


def main():
    w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    c = ControlClient(SerialTransport("COM5", 115200))
    c.set_screen(w, h)
    time.sleep(0.05)
    try:
        with no_pointer_accel():
            # Go to known spot with many small REL (known-good path)
            print("=== warm: many REL(40,0) ===")
            for _ in range(5):
                c.move_rel(-40, 0)
                time.sleep(0.02)
            print("pos", cursor())

            print("\n=== 1) single REL burst dx=-500 (one frame) wait 80ms ===")
            a = cursor()
            t0 = time.perf_counter()
            c.move_rel(-500, 0)
            time.sleep(0.08)
            b = cursor()
            print(f"  {a}->{b} dx={b[0]-a[0]} ms={(time.perf_counter()-t0)*1000:.1f}")

            print("\n=== 2) SYNC+ABS one shot, wait 200ms ===")
            a = cursor()
            tx, ty = w // 2, h // 2
            cx, cy = local_cursor().position()
            t0 = time.perf_counter()
            c.send(P.T_SYNC, P.pack(P.T_SYNC, cx, cy))
            c.send(P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, tx & 0xFFFF, ty & 0xFFFF))
            # sample cursor every 5ms
            samples = []
            for i in range(40):
                time.sleep(0.005)
                p = cursor()
                samples.append((round((time.perf_counter() - t0) * 1000, 1), p))
            print(f"  start={a} target={(tx,ty)} sync_from={(cx,cy)}")
            for ms, p in samples[::4]:
                print(f"  t={ms}ms pos={p}")
            print(f"  end={samples[-1][1]} err={max(abs(samples[-1][1][0]-tx), abs(samples[-1][1][1]-ty))}")

            print("\n=== 3) SYNC+ABS send_many (one write), wait 200ms ===")
            a = cursor()
            cx, cy = cursor()
            tx, ty = 300, 300
            t0 = time.perf_counter()
            c.send_many(
                [
                    (P.T_SYNC, P.pack(P.T_SYNC, cx, cy)),
                    (P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, tx & 0xFFFF, ty & 0xFFFF)),
                ]
            )
            samples = []
            for i in range(40):
                time.sleep(0.005)
                samples.append((round((time.perf_counter() - t0) * 1000, 1), cursor()))
            for ms, p in samples[::4]:
                print(f"  t={ms}ms pos={p}")
            print(f"  end={samples[-1][1]} err={max(abs(samples[-1][1][0]-tx), abs(samples[-1][1][1]-ty))}")

            print("\n=== 4) host-side chunked REL ±127 (no firmware long burst) ===")
            a = cursor()
            tx, ty = w // 2, h // 2
            t0 = time.perf_counter()
            x, y = a
            while abs(tx - x) > 2 or abs(ty - y) > 2:
                dx = max(-127, min(127, tx - x))
                dy = max(-127, min(127, ty - y))
                c.move_rel(dx, dy)
                # poll until this chunk mostly applied
                deadline = time.perf_counter() + 0.025
                while time.perf_counter() < deadline:
                    x, y = cursor()
                    # progress?
                    if abs((a[0] + (tx - a[0])) - x) >= 0:  # always
                        if abs(dx) >= 10 and abs(x - a[0]) >= min(10, abs(dx) // 2):
                            break
                        if abs(dx) < 10:
                            break
                    time.sleep(0.001)
                x, y = cursor()
                a = (x, y)
                if time.perf_counter() - t0 > 0.5:
                    break
            ms = (time.perf_counter() - t0) * 1000
            e = max(abs(x - tx), abs(y - ty))
            print(f"  end={(x,y)} target={(tx,ty)} err={e} ms={ms:.1f}")

            print("\n=== 5) REL(+200,0) timeline ===")
            a = cursor()
            t0 = time.perf_counter()
            c.move_rel(200, 0)
            for i in range(30):
                time.sleep(0.002)
                p = cursor()
                print(f"  t={(time.perf_counter()-t0)*1000:.1f} dx={p[0]-a[0]} pos={p}")
                if abs(p[0] - a[0]) >= 190:
                    break
    finally:
        c.close()


if __name__ == "__main__":
    main()
