# -*- coding: utf-8 -*-
import shutil
import sys
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

SRC = Path(r"D:\Rasberrypi\control\pico")
DST = Path("F:/")
for name in ("boot.py", "main.py", "abs_hid.py", "boot_abs.py"):
    shutil.copy2(SRC / name, DST / name)
    print("copied", name)

import serial

ser = serial.Serial("COM4", 115200, timeout=1, dsrdtr=False)
try:
    ser.dtr = False
    ser.rts = False
except Exception:
    pass
ser.write(b"\r\x03\x03")
time.sleep(0.3)
ser.reset_input_buffer()
ser.write(b"import microcontroller\r\n")
time.sleep(0.2)
ser.write(b"microcontroller.reset()\r\n")
time.sleep(0.3)
ser.close()
print("reset sent, waiting...")
time.sleep(5.0)

sys.path.insert(0, r"D:\Rasberrypi")
from control import ControlClient, SerialTransport
from control.pointer import no_pointer_accel

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def cur():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return int(p.x), int(p.y)


import serial.tools.list_ports as lp

port = None
for _ in range(40):
    for p in lp.comports():
        if p.vid == 0x2E8A and "x.2" in (p.hwid or ""):
            port = p.device
            break
    if port:
        break
    time.sleep(0.15)
print("data port", port)

c = ControlClient(SerialTransport(port, 115200))
c.set_screen(1920, 1080)
lines = []
try:
    with no_pointer_accel():
        for tx, ty in ((960, 540), (200, 150), (1700, 900), (960, 540)):
            t0 = time.perf_counter()
            c.move_abs(tx, ty, resync=True)
            time.sleep(0.03)
            pos = cur()
            ms = (time.perf_counter() - t0) * 1000
            e = max(abs(pos[0] - tx), abs(pos[1] - ty))
            lines.append(
                "ABS %s -> %s err=%s ms=%.1f" % ((tx, ty), pos, e, ms)
            )
        t0 = time.perf_counter()
        c.move_click(1000, 500, hold_ms=20)
        time.sleep(0.04)
        lines.append("MOVE_CLICK_ms %.1f" % ((time.perf_counter() - t0) * 1000,))
        r = c.ping(timeout=0.5, samples=3)
        lines.append("PING_ms %s" % (r,))
finally:
    c.close()

text = "\n".join(lines)
Path(r"D:\Rasberrypi\control\_abs_fw_verify.txt").write_text(text, encoding="utf-8")
print(text)
