# -*- coding: utf-8 -*-
"""Re-run boot.py via a temporary main.py reset stub, then restore real main.

CircuitPython only executes boot.py on full microcontroller.reset()/power-cycle.
DTR/autoreload is not enough when changing usb_hid.enable().
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import serial.tools.list_ports as lp

SRC = Path(r"D:\Rasberrypi\control\pico")
DST = Path("F:/")

STUB = """import time
time.sleep(4)
import microcontroller
microcontroller.reset()
"""


def pico_ports():
    return [p.device for p in lp.comports() if p.vid == 0x2E8A]


def wait_ports_change(before, timeout=12.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        now = pico_ports()
        if now and set(now) != set(before):
            return now
        if now and before and set(now) == set(before):
            # also accept brief disappear
            pass
        if not now and before:
            # disappeared — wait for return
            while time.time() - t0 < timeout:
                now = pico_ports()
                if now:
                    return now
                time.sleep(0.1)
        time.sleep(0.1)
    return pico_ports()


def remount():
    try:
        import serial

        for p in lp.comports():
            if p.vid == 0x2E8A and "x.0" in (p.hwid or ""):
                ser = serial.Serial(
                    p.device, 115200, timeout=0.4, write_timeout=3, dsrdtr=False
                )
                try:
                    ser.dtr = False
                    ser.rts = False
                except Exception:
                    pass
                for _ in range(3):
                    ser.write(b"\x03")
                    time.sleep(0.05)
                ser.write(b"import storage\r\n")
                time.sleep(0.2)
                ser.write(b'storage.remount("/", False)\r\n')
                time.sleep(0.3)
                ser.close()
                break
    except Exception as e:
        print("remount", e)


def main():
    remount()
    for name in ("boot.py", "boot_abs.py", "abs_hid.py"):
        shutil.copy2(SRC / name, DST / name)
        print("copied", name)

    before = pico_ports()
    print("ports before", before)
    (DST / "main.py").write_text(STUB, encoding="utf-8")
    print("stub main written; nudge DTR for reload...")
    try:
        import serial

        for p in lp.comports():
            if p.vid != 0x2E8A:
                continue
            ser = serial.Serial(p.device, 115200, timeout=0.3, write_timeout=3)
            ser.dtr = False
            time.sleep(0.05)
            ser.dtr = True
            time.sleep(0.1)
            ser.dtr = False
            ser.close()
            print("dtr", p.device)
    except Exception as e:
        print("dtr fail", e)
    time.sleep(1.0)
    ports = wait_ports_change(before, timeout=15.0)
    print("ports after", ports)
    time.sleep(1.2)
    # restore real main during stub's next sleep window (or after boot)
    remount()
    shutil.copy2(SRC / "main.py", DST / "main.py")
    print("real main restored", (DST / "main.py").stat().st_size)
    time.sleep(4.0)
    print("boot_out:\n", (DST / "boot_out.txt").read_text(encoding="utf-8"))

    sys.path.insert(0, r"D:\Rasberrypi")
    from control import ControlClient, SerialTransport
    from control.pointer import no_pointer_accel
    import control.protocol as P
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()

    def cur():
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)

    port = None
    for _ in range(40):
        for p in lp.comports():
            if p.vid == 0x2E8A and "x.2" in (p.hwid or ""):
                port = p.device
                break
        if port:
            break
        time.sleep(0.15)
    print("data", port)
    if not port:
        return 1
    c = ControlClient(SerialTransport(port, 115200))
    try:
        print("ping", c.ping(timeout=1.0, samples=2))
        with no_pointer_accel():
            a = cur()
            c.move_rel(25, 0)
            time.sleep(0.06)
            b = cur()
            print("REL", a, "->", b, "dx", b[0] - a[0])
            # ABS raw timing
            tx, ty = 960, 540
            t0 = time.perf_counter()
            c.send(P.T_MOUSE_ABS, P.pack(P.T_MOUSE_ABS, tx, ty))
            arrive = None
            while time.perf_counter() - t0 < 0.12:
                pos = cur()
                if abs(pos[0] - tx) <= 2 and abs(pos[1] - ty) <= 2:
                    arrive = (time.perf_counter() - t0) * 1000.0
                    break
                time.sleep(0.001)
            pos = cur()
            err = max(abs(pos[0] - tx), abs(pos[1] - ty))
            print(
                "ABS_RAW",
                (tx, ty),
                "->",
                pos,
                "err",
                err,
                "arrive_ms",
                arrive,
            )
            t0 = time.perf_counter()
            c.move_abs(400, 400, resync=True)
            arrive = None
            while time.perf_counter() - t0 < 0.2:
                pos = cur()
                if abs(pos[0] - 400) <= 2 and abs(pos[1] - 400) <= 2:
                    arrive = (time.perf_counter() - t0) * 1000.0
                    break
                time.sleep(0.001)
            print("ABS_SYNC ->", cur(), "arrive_ms", arrive)
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
