# -*- coding: utf-8 -*-
"""Write pico firmware files onto CIRCUITPY via REPL raw-paste (MSC write-protected OK)."""
from __future__ import annotations

import serial
import serial.tools.list_ports as lp
import time
from pathlib import Path

SRC = Path(r"D:\Rasberrypi\control\pico")
FILES = ("boot.py", "boot_abs.py", "main.py", "abs_hid.py")


def find_console():
    for p in lp.comports():
        if p.vid == 0x2E8A and "x.0" in (p.hwid or ""):
            return p.device
    for p in lp.comports():
        if p.vid == 0x2E8A and "x.1" in (p.hwid or ""):
            return p.device
    for p in lp.comports():
        if p.vid == 0x2E8A:
            return p.device
    return None


def drain(ser, t=0.3):
    t0 = time.time()
    buf = b""
    while time.time() - t0 < t:
        chunk = ser.read(1024)
        if chunk:
            buf += chunk
        else:
            time.sleep(0.02)
    return buf


def interrupt(ser):
    for _ in range(3):
        ser.write(b"\x03")
        time.sleep(0.1)
    ser.write(b"\r\n")
    time.sleep(0.2)
    drain(ser, 0.4)


def raw_paste(ser, code: str):
    """CircuitPython raw paste mode (Ctrl-E ... Ctrl-D)."""
    data = code.encode("utf-8")
    ser.write(b"\x05")  # enter raw paste
    time.sleep(0.05)
    # windowed send
    window = 32
    i = 0
    while i < len(data):
        chunk = data[i : i + window]
        ser.write(chunk)
        # flow control: device may send 0x01 (continue) / 0x04 issues
        time.sleep(0.002)
        i += len(chunk)
        # read flow bytes without blocking long
        ser.timeout = 0.01
        _ = ser.read(64)
    ser.timeout = 0.2
    ser.write(b"\x04")  # finish
    out = b""
    t0 = time.time()
    while time.time() - t0 < 8.0:
        chunk = ser.read(1024)
        if chunk:
            out += chunk
            if b"\x04>" in out or out.endswith(b">>>"):
                break
        else:
            time.sleep(0.05)
    return out


def write_file(ser, name: str, text: str):
    # Escape for triple-quoted write on device
    if '"""' in text:
        payload = repr(text)
        code = (
            "f=open(%r,'w')\n"
            "f.write(%s)\n"
            "f.close()\n"
            "print('WROTE',%r,len(open(%r).read()))\n"
        ) % (name, payload, name, name)
    else:
        code = (
            "f=open(%r,'w')\n"
            'f.write("""%s""")\n'
            "f.close()\n"
            "print('WROTE',%r,len(open(%r).read()))\n"
        ) % (name, text, name, name)
    interrupt(ser)
    out = raw_paste(ser, code)
    print(out.decode("utf-8", errors="replace")[-500:])
    if b"WROTE" not in out:
        # fallback: line-by-line open/write with repr chunks
        interrupt(ser)
        ser.write(b"f=open(%r,'wb')\r\n" % name.encode("ascii"))
        drain(ser, 0.2)
        raw = text.encode("utf-8")
        for i in range(0, len(raw), 40):
            chunk = raw[i : i + 40]
            ser.write(b"f.write(" + repr(chunk).encode("ascii") + b")\r\n")
            drain(ser, 0.15)
        ser.write(b"f.close(); print('WROTE',%r)\r\n" % name.encode("ascii"))
        out2 = drain(ser, 1.0)
        print(out2.decode("utf-8", errors="replace"))
        if b"WROTE" not in out2:
            raise RuntimeError("write failed for %s" % name)


def soft_reset(ser):
    interrupt(ser)
    ser.write(b"import microcontroller\r\n")
    drain(ser, 0.3)
    ser.write(b"microcontroller.reset()\r\n")
    time.sleep(0.2)
    print("reset sent")


def main():
    port = find_console()
    print("console", port)
    if not port:
        return 1
    ser = serial.Serial(port, 115200, timeout=0.2, write_timeout=5, dsrdtr=False)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    interrupt(ser)
    for name in FILES:
        text = (SRC / name).read_text(encoding="utf-8")
        print("writing", name, len(text))
        write_file(ser, name, text)
    soft_reset(ser)
    ser.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
