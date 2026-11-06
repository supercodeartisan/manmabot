# -*- coding: utf-8 -*-
"""Copy firmware to CIRCUITPY, wait for main.py autoreload, then T_RESET for boot.py."""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

import serial.tools.list_ports as lp

SRC = Path(r"D:\Rasberrypi\control\pico")
DST = Path("F:/")
sys.path.insert(0, r"D:\Rasberrypi")


def remount_hint():
    # best-effort; host write may already work
    try:
        import serial

        for p in lp.comports():
            if p.vid == 0x2E8A and "x.0" in (p.hwid or ""):
                ser = serial.Serial(p.device, 115200, timeout=0.5, write_timeout=3, dsrdtr=False)
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
        print("remount skip", e)


def find_data():
    for p in lp.comports():
        if p.vid == 0x2E8A and "x.2" in (p.hwid or ""):
            return p.device
    for p in lp.comports():
        if p.vid == 0x2E8A:
            return p.device
    return None


def main():
    remount_hint()
    for name in ("boot.py", "boot_abs.py", "main.py", "abs_hid.py"):
        shutil.copy2(SRC / name, DST / name)
        print("copied", name)
    print("wait autoreload...")
    time.sleep(3.0)
    port = find_data()
    print("data", port)
    if not port:
        return 1
    from control import ControlClient, SerialTransport
    import control.protocol as P

    c = ControlClient(SerialTransport(port, 115200))
    try:
        # confirm alive
        try:
            r = c.ping(timeout=0.8, samples=1)
            print("ping", r)
        except Exception as e:
            print("ping fail", e)
        c.send(P.T_RESET, b"")
        print("T_RESET sent")
    finally:
        try:
            c.close()
        except Exception:
            pass
    time.sleep(7.0)
    ran = DST / "boot_ran.txt"
    print("boot_ran", ran.read_text(encoding="utf-8") if ran.exists() else "MISSING")
    print("boot_out:\n", (DST / "boot_out.txt").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
