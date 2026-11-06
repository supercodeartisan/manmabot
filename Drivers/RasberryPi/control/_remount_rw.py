# -*- coding: utf-8 -*-
import serial
import time

ser = serial.Serial("COM4", 115200, timeout=1, write_timeout=5, dsrdtr=False)
try:
    ser.dtr = False
    ser.rts = False
except Exception:
    pass
for _ in range(5):
    ser.write(b"\x03")
    time.sleep(0.05)
ser.write(b"\r\n")
time.sleep(0.5)
print("INT:", ser.read(4096))
cmds = [
    b"import storage\r\n",
    b'storage.remount("/", False)\r\n',
    b'print("REMOUNT_OK")\r\n',
]
for c in cmds:
    ser.write(c)
    time.sleep(0.5)
    print(c, "->", ser.read(4096))
ser.close()
