# control/pico/abs_hid.py — absolute mouse for Windows system cursor
#
# 5-byte report (Report ID 4): buttons(1) + X uint16 + Y uint16, range 0..32767
# CircuitPython 10 often leaves report_ids empty on Device objects; find the
# Generic-Desktop Mouse that is NOT the first (builtin relative) mouse.

REPORT_DESCRIPTOR = bytes(
    (
        0x05,
        0x01,  # Usage Page (Generic Desktop)
        0x09,
        0x02,  # Usage (Mouse)
        0xA1,
        0x01,  # Collection (Application)
        0x85,
        0x04,  #   Report ID 4
        0x09,
        0x01,  #   Usage (Pointer)
        0xA1,
        0x00,  #   Collection (Physical)
        0x05,
        0x09,  #     Usage Page (Button)
        0x19,
        0x01,
        0x29,
        0x05,  #     5 buttons
        0x15,
        0x00,
        0x25,
        0x01,
        0x95,
        0x05,
        0x75,
        0x01,
        0x81,
        0x02,
        0x95,
        0x01,
        0x75,
        0x03,
        0x81,
        0x03,  #     pad
        0x05,
        0x01,  #     Usage Page (Generic Desktop)
        0x09,
        0x30,  #     Usage (X)
        0x09,
        0x31,  #     Usage (Y)
        0x15,
        0x00,
        0x26,
        0xFF,
        0x7F,  #     Logical Max 32767
        0x35,
        0x00,
        0x46,
        0xFF,
        0x7F,  #     Physical Max 32767
        0x75,
        0x10,
        0x95,
        0x02,
        0x81,
        0x02,  #     Input Abs
        0xC0,
        0xC0,
    )
)

_USAGE_PAGE_GD = 0x01
_USAGE_MOUSE = 0x02
_REPORT_ID = 4
MAXV = 32767


def make_device():
    import usb_hid

    return usb_hid.Device(
        report_descriptor=REPORT_DESCRIPTOR,
        usage_page=_USAGE_PAGE_GD,
        usage=_USAGE_MOUSE,
        report_ids=(_REPORT_ID,),
        in_report_lengths=(5,),
        out_report_lengths=(0,),
    )


def find_in_devices(devices):
    """Prefer custom abs mouse; never steal the builtin relative mouse."""
    mice = []
    for d in devices:
        rids = getattr(d, "report_ids", ()) or ()
        if _REPORT_ID in rids:
            return d
        up = getattr(d, "usage_page", None)
        us = getattr(d, "usage", None)
        if up == _USAGE_PAGE_GD and us == _USAGE_MOUSE:
            mice.append(d)
    # Builtin relative mouse is first; custom abs (boot order) is last.
    if len(mice) >= 2:
        return mice[-1]
    return None


def describe_devices(devices):
    parts = []
    for d in devices:
        rids = getattr(d, "report_ids", ()) or ()
        up = getattr(d, "usage_page", None)
        us = getattr(d, "usage", None)
        inl = getattr(d, "in_report_lengths", ()) or ()
        parts.append("up=%s us=%s rid=%s in=%s" % (up, us, rids, inl))
    return parts


class AbsolutePointer(object):
    def __init__(self, device, screen=(1920, 1080)):
        self.device = device
        self.screen = [max(1, int(screen[0])), max(1, int(screen[1]))]
        self.pos = [0, 0]
        self.buttons = 0
        self._last = None

    def set_screen(self, w, h):
        self.screen = [max(1, int(w)), max(1, int(h))]
        self._last = None

    def _scaled(self, x, y):
        sx = max(1, self.screen[0] - 1)
        sy = max(1, self.screen[1] - 1)
        x = max(0, min(self.screen[0] - 1, int(x)))
        y = max(0, min(self.screen[1] - 1, int(y)))
        vx = int(round(x * MAXV / float(sx)))
        vy = int(round(y * MAXV / float(sy)))
        return max(0, min(MAXV, vx)), max(0, min(MAXV, vy))

    def _send(self, force=False):
        vx, vy = self._scaled(self.pos[0], self.pos[1])
        key = (self.buttons & 0x1F, vx, vy)
        if not force and key == self._last:
            return
        self._last = key
        self.device.send_report(
            bytes(
                (
                    self.buttons & 0x1F,
                    vx & 0xFF,
                    (vx >> 8) & 0xFF,
                    vy & 0xFF,
                    (vy >> 8) & 0xFF,
                )
            )
        )

    def move(self, x, y):
        self.pos = [int(x), int(y)]
        self._send(force=True)

    def down(self, mask=0x01):
        self.buttons |= int(mask) & 0x1F
        self._send(force=True)

    def up(self, mask=0x01):
        self.buttons &= ~(int(mask) & 0x1F)
        self._send(force=True)

    def wheel(self, dy):
        pass

    def click(self, x, y, hold_ms=20):
        import time as _t

        self.move(x, y)
        self.down(0x01)
        _t.sleep(max(1, int(hold_ms)) / 1000.0)
        self.up(0x01)
