# -*- coding: utf-8 -*-
import time
import serial

ser = serial.Serial("COM4", 115200, timeout=0.8, dsrdtr=False)
try:
    ser.dtr = False
    ser.rts = False
except Exception:
    pass
ser.write(b"\r\x03\x03")
time.sleep(0.5)
ser.reset_input_buffer()
# Stop main loop briefly and probe
code = b"""
import usb_hid
print('NDEV', len(usb_hid.devices))
for d in usb_hid.devices:
    print('DEV', getattr(d,'usage_page',None), getattr(d,'usage',None), getattr(d,'report_ids',None), getattr(d,'in_report_lengths',None))
try:
    import abs_hid
    print('FIND', abs_hid.find_in_devices(usb_hid.devices))
except Exception as e:
    print('ABSERR', e)
"""
ser.write(b"\x05")  # Ctrl-E paste mode? may not work
time.sleep(0.1)
# line by line
for line in code.strip().splitlines():
    ser.write(line + b"\r\n")
    time.sleep(0.2)
time.sleep(0.8)
out = ser.read(8192)
ser.close()
open(r"D:\Rasberrypi\control\_repl_out.txt", "wb").write(out)
print(out.decode("utf-8", "replace"))
