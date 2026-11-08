# control/pico/boot.py — CDC + keyboard + REL mouse + ABS mouse (report id 4)
#
# Fast aim, click, and wheel use AbsolutePointer. The builtin relative mouse
# stays only as the fallback when the absolute device is missing. boot.py
# runs on full reset (T_RESET / power cycle), not on main.py autoreload.

import usb_cdc
import usb_hid

try:
    usb_cdc.enable(console=True, data=True)
except Exception:
    pass

try:
    from abs_hid import make_device

    _abs = make_device()
    usb_hid.enable((usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE, _abs))
    print("boot: KEYBOARD+REL+ABS")
except Exception as e:
    print("boot abs fail", e)
    try:
        usb_hid.enable((usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE))
        print("boot: KEYBOARD+REL fallback")
    except Exception as e2:
        print("boot fail", e2)
