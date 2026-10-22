# -*- coding: utf-8 -*-
"""Deploy abs touch-screen HID, T_RESET, measure ABS aim."""
from __future__ import annotations

import shutil
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

import serial.tools.list_ports as lp

SRC = Path(r"D:\Rasberrypi\control\pico")
DST = Path("F:/")
OUT = Path(r"D:\Rasberrypi\control\_abs_map_diag.txt")
sys.path.insert(0, r"D:\Rasberrypi")

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cur():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


def data_port():
    for p in lp.comports():
        if p.vid == 0x2E8A and "x.2" in (p.hwid or ""):
            return p.device
    return None


def main():
    lines = []
    for name in ("boot.py", "boot_abs.py", "main.py", "abs_hid.py"):
        shutil.copy2(SRC / name, DST / name)
        print("copied", name)
    time.sleep(3.5)
    port = data_port()
    print("port", port)
    from control import ControlClient, SerialTransport
    from control.pointer import no_pointer_accel
    import control.protocol as P

    c = ControlClient(SerialTransport(port, 115200))
    try:
        print("ping_pre", c.ping(timeout=1.0, samples=1))
        print("mode_pre", c.get_mode(timeout=1.0))
        c.reset_board()
        print("T_RESET sent")
    finally:
        try:
            c.close()
        except Exception:
            pass
    time.sleep(7.0)
    print("boot_out:\n", (DST / "boot_out.txt").read_text(encoding="utf-8"))
    port = data_port()
    for _ in range(30):
        if port:
            break
        time.sleep(0.2)
        port = data_port()
    print("port_after", port)
    c = ControlClient(SerialTransport(port, 115200))
    try:
        mode = c.get_mode(timeout=1.5)
        ping = c.ping(timeout=1.0, samples=2)
        lines.append("mode %s" % mode)
        lines.append("ping %s" % (ping,))
        print(lines[-2])
        print(lines[-1])
        with no_pointer_accel():
            c.set_screen(1920, 1080)
            a = cur()
            c.move_rel(20, 0)
            time.sleep(0.06)
            b = cur()
            lines.append("REL %s -> %s dx=%s" % (a, b, b[0] - a[0]))
            print(lines[-1])
            for tx, ty in ((960, 540), (200, 150), (1700, 900), (300, 300), (960, 540)):
                t0 = time.perf_counter()
                c.send(P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, tx & 0xFFFF, ty & 0xFFFF))
                arrive = None
                while time.perf_counter() - t0 < 0.12:
                    pos = cur()
                    if abs(pos[0] - tx) <= 2 and abs(pos[1] - ty) <= 2:
                        arrive = (time.perf_counter() - t0) * 1000.0
                        break
                    time.sleep(0.001)
                pos = cur()
                err = max(abs(pos[0] - tx), abs(pos[1] - ty))
                line = "ABS_RAW %s -> %s err=%s arrive_ms=%s" % (
                    (tx, ty),
                    pos,
                    err,
                    ("%.2f" % arrive) if arrive is not None else "NONE",
                )
                lines.append(line)
                print(line)
                time.sleep(0.04)
            # move_abs_aim gate
            from control.client import ControlClient as CC  # noqa — use same client

            for tx, ty in ((500, 400), (1400, 800), (960, 540)):
                ok, pos, ms, corr = c.move_abs_aim(
                    tx, ty, tolerance=2, timeout_s=0.05, correct=True
                )
                line = "AIM %s ok=%s pos=%s ms=%.2f corr=%s" % (
                    (tx, ty),
                    ok,
                    pos,
                    ms,
                    corr,
                )
                lines.append(line)
                print(line)
    finally:
        c.close()
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
