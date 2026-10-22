# Absolute+REL boot (same as boot.py). Kept for explicit ABS experiments.

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
except Exception:
    try:
        usb_hid.enable((usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE))
    except Exception:
        pass
