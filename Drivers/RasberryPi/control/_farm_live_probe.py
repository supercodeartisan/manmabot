# -*- coding: utf-8 -*-
"""Live probe: Pico HID for Manmabot farm-shaped input (no engine changes)."""
from __future__ import annotations

import sys
import time
import ctypes
from ctypes import wintypes

sys.path.insert(0, r"D:\Rasberrypi")

from control import ControlClient, SerialTransport
from control import protocol as P
from control.keys import parse_key
from control.pointer import no_pointer_accel
from control.feedback import local_cursor

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


def screen():
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def host_key(c: ControlClient, name: str, hold_s: float = 0.05) -> None:
    """Manmabot-style blocking down/sleep/up (not Pico hold_ms alone)."""
    code = parse_key(name)
    c.key_down(code)
    time.sleep(hold_s)
    c.key_up(code)


def main() -> int:
    w, h = screen()
    port = "COM5"
    print("SCREEN", w, h)
    print("PORT", port, "(Pico CDC data MI_02)")
    rows: list[tuple[str, bool, object]] = []
    c = None
    try:
        c = ControlClient(SerialTransport(port, 115200))
    except Exception as e:
        print("OPEN_FAIL", e)
        return 2

    try:
        c.set_screen(w, h)
        time.sleep(0.05)

        # 1) ping
        rtt = c.ping(timeout=1.0, samples=5)
        if isinstance(rtt, tuple):
            ok = rtt[0] is not None
            print(
                "PING_ms min/avg/max",
                tuple(round(x, 2) for x in rtt),
                "OK" if ok else "FAIL",
            )
            rows.append(("ping", ok, rtt))
        else:
            ok = rtt is not None
            print("PING_ms", None if rtt is None else round(rtt, 2), "OK" if ok else "FAIL")
            rows.append(("ping", ok, rtt))

        with no_pointer_accel():
            # 2) engine-style move_abs(resync=True)
            targets = [
                (w // 2, h // 2),
                (max(50, w // 5), max(50, h // 5)),
                (min(w - 50, 4 * w // 5), min(h - 50, 4 * h // 5)),
                (max(50, w // 3), min(h - 50, 2 * h // 3)),
            ]
            errs = []
            for tx, ty in targets:
                t0 = time.perf_counter()
                c.move_abs(tx, ty, resync=True)
                # wait for relative burst (~1ms/127px + margin)
                time.sleep(0.08)
                px, py = cursor()
                e = max(abs(px - tx), abs(py - ty))
                errs.append(e)
                ms = (time.perf_counter() - t0) * 1000
                ok = e <= 2
                print(
                    "ABS_RESYNC",
                    (tx, ty),
                    "->",
                    (px, py),
                    "err=",
                    e,
                    "ms=",
                    round(ms, 1),
                    "OK" if ok else "FAIL",
                )
                rows.append(("abs_resync", ok, e))

            # 3) move_click at safe corner (desktop corner — may focus taskbar)
            sx, sy = 8, 8
            c.move_click(sx, sy, hold_ms=25, resync=True)
            time.sleep(0.1)
            px, py = cursor()
            ok = max(abs(px - sx), abs(py - sy)) <= 4
            print("MOVE_CLICK", (sx, sy), "pos=", (px, py), "OK" if ok else "WEAK")
            rows.append(("move_click", ok, (px, py)))

            # 4) farm hotbar keys (host blocking press)
            farm_keys = ["esc", "f1", "f2", "f3", "f4", "f5", "f8", "f9", "f11", "f12", "enter", "space"]
            missing = []
            for name in farm_keys:
                try:
                    host_key(c, name, hold_s=0.04)
                    time.sleep(0.02)
                except Exception as e:
                    missing.append((name, str(e)))
            print("HOTBAR_KEYS", farm_keys, "missing=", missing, "OK" if not missing else "FAIL")
            rows.append(("hotbar_keys", not missing, missing))

            # 5) F4 loot spam interleaved with click (ghost-pickup pattern)
            cx, cy = w // 2, h // 2
            c.move_abs(cx, cy, resync=True)
            time.sleep(0.06)
            t0 = time.perf_counter()
            for i in range(8):
                host_key(c, "f4", hold_s=0.03)
                c.button(P.BTN_LEFT, P.ACT_PRESS, 20)
                time.sleep(0.02)
            dt = time.perf_counter() - t0
            print("F4_CLICK_x8_ms", round(dt * 1000, 1), "OK")
            rows.append(("f4_click_burst", True, round(dt * 1000, 1)))

            # 6) ground re-click cadence (~0.1s) like until_walk
            c.move_abs(cx + 40, cy, resync=True)
            time.sleep(0.05)
            t0 = time.perf_counter()
            for _ in range(5):
                c.button(P.BTN_LEFT, P.ACT_PRESS, 15)
                time.sleep(0.1)
            dt = time.perf_counter() - t0
            print("GROUND_RECLICK5_ms", round(dt * 1000, 1), "OK" if 450 <= dt * 1000 <= 700 else "WEAK")
            rows.append(("ground_reclick", 0.45 <= dt <= 0.75, round(dt * 1000, 1)))

            # 7) short humanize-like polyline (open-loop abs points)
            t0 = time.perf_counter()
            x0, y0 = cursor()
            pts = []
            for i in range(1, 7):
                pts.append(
                    (
                        P.T_MOUSE_ABS,
                        P.pack(P.T_MOUSE_ABS, (x0 + i * 10) & 0xFFFF, y0 & 0xFFFF),
                    )
                )
            # sync first for firmware tracker
            lc = local_cursor().position()
            c.send(P.T_SYNC, P.pack(P.T_SYNC, lc[0], lc[1]))
            c.send_many(pts)
            time.sleep(0.04)
            dt = time.perf_counter() - t0
            print("POLY6_ms", round(dt * 1000, 1), "budget50=", "OK" if dt <= 0.08 else "OVER")
            rows.append(("poly6", dt <= 0.08, round(dt * 1000, 1)))

            print("ABS_RESYNC_MAX_ERR", max(errs) if errs else None)

    except Exception as e:
        print("EXCEPTION", type(e).__name__, e)
        rows.append(("exception", False, str(e)))
    finally:
        try:
            if c is not None:
                c.close()
        except Exception:
            pass

    fails = [r[0] for r in rows if not r[1]]
    verdict = "PASS" if not fails else "PARTIAL"
    print("VERDICT", verdict, "fails=", fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
