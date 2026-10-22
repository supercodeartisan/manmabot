# -*- coding: utf-8 -*-
"""One-shot precision smoke test for connected Pico (no engine changes)."""
import sys, time, ctypes
from ctypes import wintypes

sys.path.insert(0, r"D:\Rasberrypi")
from control import ControlClient, SerialTransport
from control.feedback import FeedbackController, local_cursor
from control.pointer import no_pointer_accel
from control import protocol as P

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

def cursor():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)

def screen():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

def try_open(port):
    try:
        c = ControlClient(SerialTransport(port, 115200))
        return c
    except Exception as e:
        print("OPEN_FAIL", port, e)
        return None

def main():
    w, h = screen()
    print("SCREEN", w, h)
    # data CDC is usually the higher interface (COM5 / x.2)
    ports = ["COM5", "COM4"]
    c = None
    port = None
    for p in ports:
        c = try_open(p)
        if c:
            port = p
            break
    if not c:
        print("RESULT FAIL no_serial")
        return 2
    print("PORT", port)
    results = []
    try:
        c.set_screen(w, h)
        time.sleep(0.05)

        # 1) relative move with accel off
        with no_pointer_accel():
            a = cursor()
            c.move_rel(80, 0)
            time.sleep(0.15)
            b = cursor()
            dx = b[0] - a[0]
            ok = 60 <= dx <= 100  # allow some OS scaling
            print("REL_X", a, "->", b, "dx=", dx, "OK" if ok else "WEAK")
            results.append(("rel_x", ok, dx))

            a = cursor()
            c.move_rel(0, 50)
            time.sleep(0.15)
            b = cursor()
            dy = b[1] - a[1]
            ok = 35 <= dy <= 70
            print("REL_Y", a, "->", b, "dy=", dy, "OK" if ok else "WEAK")
            results.append(("rel_y", ok, dy))

            # 2) closed-loop absolute (precision core)
            fc = FeedbackController(c, local_cursor(), settle=0.012)
            targets = [
                (w // 2, h // 2),
                (max(40, w // 4), max(40, h // 4)),
                (min(w - 40, 3 * w // 4), min(h - 40, 3 * h // 4)),
            ]
            errs = []
            for tx, ty in targets:
                ok, pos, n = fc.move_abs(tx, ty, tolerance=2, max_iter=25)
                ex = abs(pos[0] - tx)
                ey = abs(pos[1] - ty)
                e = max(ex, ey)
                errs.append(e)
                print("ABS", (tx, ty), "->", pos, "err=", e, "iters=", n, "OK" if ok else "FAIL")
                results.append(("abs", ok, e))
                time.sleep(0.05)
            print("ABS_MAX_ERR", max(errs) if errs else None)

            # 3) button down/up (no click on UI: move to safe corner first)
            fc.move_abs(5, 5, tolerance=4, max_iter=20)
            time.sleep(0.05)
            c.button_down(P.BTN_LEFT)
            time.sleep(0.04)
            c.button_up(P.BTN_LEFT)
            print("BTN left down/up sent OK")
            results.append(("btn", True, 0))

            # 4) wheel
            c.wheel(-1)
            time.sleep(0.05)
            c.wheel(1)
            print("WHEEL sent OK")
            results.append(("wheel", True, 0))

            # 5) keys: Escape down/up + letter 'a' press (may affect focused window)
            c.key_down(0x29)  # Escape
            time.sleep(0.02)
            c.key_up(0x29)
            c.key(0x04, hold_ms=30)  # 'a'
            print("KEY Esc + a sent OK")
            results.append(("key", True, 0))

            # 6) batch curve budget (engine-like 6 abs points)
            t0 = time.perf_counter()
            cx, cy = cursor()
            pts = []
            for i in range(1, 7):
                pts.append((P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, (cx + i * 8) & 0xFFFF, cy & 0xFFFF)))
            c.send_many(pts)
            # wait for HID to catch up
            time.sleep(0.03)
            dt = time.perf_counter() - t0
            print("BATCH6_ms", round(dt * 1000, 2), "budget20=", "OK" if dt <= 0.05 else "OVER")
            results.append(("batch6", dt <= 0.05, round(dt * 1000, 2)))

    except Exception as e:
        print("EXCEPTION", type(e).__name__, e)
        results.append(("exception", False, str(e)))
        return 1
    finally:
        try:
            c.close()
        except Exception:
            pass

    fails = [r for r in results if not r[1]]
    print("SUMMARY", "PASS" if not fails else "PARTIAL", "fails=", [f[0] for f in fails])
    return 0 if not fails else 1

if __name__ == "__main__":
    sys.exit(main())
