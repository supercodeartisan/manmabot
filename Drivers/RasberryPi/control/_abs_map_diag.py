# -*- coding: utf-8 -*-
"""Deploy ABS boot + probe: does T_MOUSE_ABS jump GetCursorPos in <=5ms?"""
from __future__ import annotations

import shutil
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

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


def deploy():
    for name in ("boot.py", "boot_abs.py", "main.py", "abs_hid.py"):
        shutil.copy2(SRC / name, DST / name)
        print("copied", name)


def soft_reset():
    import serial
    import serial.tools.list_ports as lp

    cons = None
    for p in lp.comports():
        h = (p.hwid or "").lower()
        if p.vid == 0x2E8A and ("x.0" in h or "x.1" in h):
            cons = p.device
            break
    if not cons:
        for p in lp.comports():
            if p.vid == 0x2E8A:
                cons = p.device
                break
    print("console", cons)
    if not cons:
        return
    ser = serial.Serial(cons, 115200, timeout=1, write_timeout=5, dsrdtr=False)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    for _ in range(5):
        ser.write(b"\x03")
        time.sleep(0.05)
    ser.write(b"\r\n")
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"import microcontroller\r\n")
    time.sleep(0.3)
    ser.write(b"microcontroller.reset()\r\n")
    time.sleep(0.2)
    ser.close()
    print("reset sent")


def find_data_port(timeout=8.0):
    import serial.tools.list_ports as lp

    t0 = time.time()
    while time.time() - t0 < timeout:
        for p in lp.comports():
            if p.vid == 0x2E8A and "x.2" in (p.hwid or "").lower():
                return p.device
        time.sleep(0.15)
    return None


def main():
    lines = []
    deploy()
    soft_reset()
    time.sleep(5.0)
    port = find_data_port()
    lines.append("data_port %s" % port)
    print("data_port", port)
    if not port:
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 1

    from control import ControlClient, SerialTransport
    from control.pointer import no_pointer_accel
    import control.protocol as P

    c = ControlClient(SerialTransport(port, 115200))
    c.set_screen(1920, 1080)
    targets = ((960, 540), (200, 150), (1700, 900), (300, 300), (960, 540))
    try:
        with no_pointer_accel():
            # warm REL so we know HID is alive
            x0, y0 = cur()
            c.move_rel(40, 0)
            time.sleep(0.05)
            x1, y1 = cur()
            lines.append("REL_WARM %s -> %s dx=%s" % ((x0, y0), (x1, y1), x1 - x0))
            print(lines[-1])

            for tx, ty in targets:
                # no resync first: pure ABS path timing
                t0 = time.perf_counter()
                c.send(P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, tx & 0xFFFF, ty & 0xFFFF))
                samples = []
                deadline = t0 + 0.12
                while time.perf_counter() < deadline:
                    pos = cur()
                    ms = (time.perf_counter() - t0) * 1000.0
                    samples.append((ms, pos))
                    if abs(pos[0] - tx) <= 2 and abs(pos[1] - ty) <= 2:
                        break
                    time.sleep(0.001)
                pos = cur()
                err = max(abs(pos[0] - tx), abs(pos[1] - ty))
                arrive = None
                for ms, p in samples:
                    if abs(p[0] - tx) <= 2 and abs(p[1] - ty) <= 2:
                        arrive = ms
                        break
                line = "ABS_RAW %s -> %s err=%s arrive_ms=%s first=(%.1f,%s)" % (
                    (tx, ty),
                    pos,
                    err,
                    ("%.1f" % arrive) if arrive is not None else "NONE",
                    samples[0][0] if samples else -1,
                    samples[0][1] if samples else None,
                )
                lines.append(line)
                print(line)
                time.sleep(0.05)

            # with SYNC (REL firmware path) for comparison
            for tx, ty in ((400, 400), (1200, 700)):
                t0 = time.perf_counter()
                c.move_abs(tx, ty, resync=True)
                arrive = None
                deadline = t0 + 0.2
                while time.perf_counter() < deadline:
                    pos = cur()
                    if abs(pos[0] - tx) <= 2 and abs(pos[1] - ty) <= 2:
                        arrive = (time.perf_counter() - t0) * 1000.0
                        break
                    time.sleep(0.001)
                pos = cur()
                err = max(abs(pos[0] - tx), abs(pos[1] - ty))
                line = "ABS_SYNC %s -> %s err=%s arrive_ms=%s" % (
                    (tx, ty),
                    pos,
                    err,
                    ("%.1f" % arrive) if arrive is not None else "NONE",
                )
                lines.append(line)
                print(line)
    finally:
        c.close()

    text = "\n".join(lines) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
