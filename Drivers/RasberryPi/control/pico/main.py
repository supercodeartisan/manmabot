# control/pico/main.py — fast HID inject with position resync (precision + speed)
#
# Absolute pixel aim:
#   1) Host SYNC with current cursor (x,y)  → firmware pos tracker aligned
#   2) MOUSE_ABS (tx,ty) → relative burst (1:1 when Windows accel is off)
# One screen-diagonal is ~15 HID reports (~ms), no closed-loop wait.
#
# Also: PING/PONG, non-blocking hold, SYNC clears stuck keys/buttons.

import time
import struct
import usb_cdc

MAGIC0, MAGIC1, VERSION, HEADER_LEN = 0xC0, 0xDE, 1, 12
T_PING, T_PONG = 0x01, 0x02
T_MOUSE_ABS, T_MOUSE_REL, T_MOUSE_BTN, T_MOUSE_WHEEL = 0x10, 0x11, 0x12, 0x13
T_KEY, T_KEY_TEXT, T_TYPE, T_SET_SCREEN, T_SYNC, T_RESET = (
    0x20,
    0x21,
    0x22,
    0x30,
    0x31,
    0x32,
)
T_GET_MODE = 0x33

_CRC_TABLE = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) & 0xFFFF if (_c & 0x8000) else ((_c << 1) & 0xFFFF)
    _CRC_TABLE.append(_c)


def crc16(data):
    crc = 0xFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def encode(msg_type, seq, payload=b""):
    head = struct.pack(
        "<BBBBIHH",
        MAGIC0,
        MAGIC1,
        VERSION,
        msg_type & 0xFF,
        seq & 0xFFFFFFFF,
        len(payload),
        0,
    )
    c = crc16(head[:10] + payload)
    return head[:10] + struct.pack("<H", c) + payload


class Parser:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while len(self.buf) >= HEADER_LEN:
            if self.buf[0] != MAGIC0 or self.buf[1] != MAGIC1:
                idx = self.buf.find(bytes((MAGIC0, MAGIC1)), 1)
                if idx < 0:
                    self.buf = self.buf[-1:]
                    break
                self.buf = self.buf[idx:]
                continue
            _m0, _m1, ver, mtype, seq, length, crc = struct.unpack_from(
                "<BBBBIHH", self.buf, 0
            )
            if len(self.buf) < HEADER_LEN + length:
                break
            payload = bytes(self.buf[HEADER_LEN : HEADER_LEN + length])
            if crc16(bytes(self.buf[0:10]) + payload) == crc and ver == VERSION:
                out.append((mtype, seq, payload))
            self.buf = self.buf[HEADER_LEN + length :]
        return out


try:
    import usb_hid
    from adafruit_hid.keyboard import Keyboard
    from adafruit_hid.mouse import Mouse
    from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS

    _HID_OK = True
except Exception:
    _HID_OK = False


class Hid:
    def __init__(self, screen=(1920, 1080)):
        self.screen = list(screen)
        self.pos = [self.screen[0] // 2, self.screen[1] // 2]
        self.kb = self.mouse = self.layout = None
        self.abs_ptr = None
        self.mode = "REL"
        if _HID_OK:
            try:
                self.kb = Keyboard(usb_hid.devices)
                self.layout = KeyboardLayoutUS(self.kb)
            except Exception:
                self.kb = None
                self.layout = None
            try:
                self.mouse = Mouse(usb_hid.devices)
            except Exception:
                self.mouse = None
            # Optional absolute device ONLY if boot_abs enabled report-id 4.
            # Never bind the normal relative mouse as abs_ptr (silent no-op).
            try:
                import abs_hid

                dev = abs_hid.find_in_devices(usb_hid.devices)
                if dev is not None:
                    self.abs_ptr = abs_hid.AbsolutePointer(dev, screen)
                    self.mode = "ABS"
                else:
                    self.mode = "REL"
            except Exception:
                self.abs_ptr = None
                self.mode = "REL"

    def set_screen(self, w, h):
        self.screen = [max(1, int(w)), max(1, int(h))]
        if self.abs_ptr is not None:
            self.abs_ptr.set_screen(w, h)

    def set_pos(self, x, y):
        """Host-reported cursor — keeps relative move_abs accurate."""
        self.pos = [
            max(0, min(self.screen[0] - 1, int(x))),
            max(0, min(self.screen[1] - 1, int(y))),
        ]

    def _burst_rel(self, dx, dy):
        """Send relative motion in ±127 chunks.

        CircuitPython ``sleep(0.001)`` often costs ~8ms wall time per call, so
        sleeping every report made long ABS warps too slow for the bot.
        Yield every 4th report only; USB HID still keeps up without mass drops.
        """
        if not self.mouse:
            return
        dx = int(dx)
        dy = int(dy)
        n = 0
        while dx or dy:
            sx = max(-127, min(127, dx))
            sy = max(-127, min(127, dy))
            self.mouse.move(x=sx, y=sy)
            dx -= sx
            dy -= sy
            n += 1
            if (n & 3) == 0:
                time.sleep(0.001)

    def move_rel(self, dx, dy):
        dx = int(dx)
        dy = int(dy)
        self.pos[0] = max(0, min(self.screen[0] - 1, self.pos[0] + dx))
        self.pos[1] = max(0, min(self.screen[1] - 1, self.pos[1] + dy))
        if self.mouse:
            self._burst_rel(dx, dy)
        elif self.abs_ptr is not None:
            self.abs_ptr.move(self.pos[0], self.pos[1])

    def move_abs(self, x, y):
        x = max(0, min(self.screen[0] - 1, int(x)))
        y = max(0, min(self.screen[1] - 1, int(y)))
        if self.abs_ptr is not None:
            self.abs_ptr.move(x, y)
            self.pos = [x, y]
            return
        dx = x - self.pos[0]
        dy = y - self.pos[1]
        self.pos = [x, y]
        self._burst_rel(dx, dy)

    def button(self, mask, action):
        if self.abs_ptr is not None and (mask & 0x07) and self.mouse is None:
            if action == 0:
                self.abs_ptr.up(mask & 0x07)
            else:
                self.abs_ptr.down(mask & 0x07)
            return
        if not self.mouse:
            return
        if action == 0:
            self.mouse.release(mask)
        else:
            self.mouse.press(mask)

    def wheel(self, dy):
        if self.mouse:
            self.mouse.move(wheel=int(dy))

    def key(self, code, modifier, action):
        if not self.kb:
            return
        mods = [0xE0 + i for i in range(8) if modifier & (1 << i)]
        if action == 0:
            self.kb.release(code)
            if mods:
                self.kb.release(*mods)
        else:
            if mods:
                self.kb.press(*mods)
            self.kb.press(code)

    def key_text(self, s):
        if self.layout:
            self.layout.write(s)

    def type_text(self, s, cps=0):
        if not self.layout:
            return
        if not cps or cps <= 0:
            self.layout.write(s)
            return
        interval = 1.0 / cps
        for ch in s:
            t0 = time.monotonic()
            self.layout.write(ch)
            rest = interval - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)

    def sync(self, x=None, y=None):
        if x is not None and y is not None:
            self.set_pos(x, y)
        try:
            if self.mouse:
                self.mouse.release(0x07)
        except Exception:
            pass
        try:
            if self.abs_ptr is not None:
                self.abs_ptr.up(0x07)
        except Exception:
            pass
        try:
            if self.kb:
                self.kb.release_all()
        except Exception:
            pass


def _board_us():
    try:
        return int(time.monotonic() * 1000000.0) & 0xFFFFFFFFFFFFFFFF
    except Exception:
        return 0


def dispatch(hid, mtype, payload, pending, seq):
    if mtype == T_PING:
        client_us = 0
        if len(payload) >= 8:
            (client_us,) = struct.unpack_from("<Q", payload, 0)
        return encode(T_PONG, seq, struct.pack("<QQ", client_us, _board_us()))

    if mtype == T_MOUSE_ABS:
        hid.move_abs(*struct.unpack_from("<HH", payload, 0))
    elif mtype == T_MOUSE_REL:
        hid.move_rel(*struct.unpack_from("<hh", payload, 0))
    elif mtype == T_MOUSE_BTN:
        mask, action, hold = struct.unpack_from("<BBH", payload, 0)
        if action == 2:
            hid.button(mask, 1)
            pending.append(
                (
                    time.monotonic() + max(hold, 1) / 1000.0,
                    lambda m=mask: hid.button(m, 0),
                )
            )
        else:
            hid.button(mask, action)
    elif mtype == T_MOUSE_WHEEL:
        (dy,) = struct.unpack_from("<b", payload, 0)
        hid.wheel(dy)
    elif mtype == T_KEY:
        code, mod, action, hold = struct.unpack_from("<BBBH", payload, 0)
        if action == 2:
            hid.key(code, mod, 1)
            pending.append(
                (
                    time.monotonic() + max(hold, 1) / 1000.0,
                    lambda c=code, m=mod: hid.key(c, m, 0),
                )
            )
        else:
            hid.key(code, mod, action)
    elif mtype == T_KEY_TEXT:
        hid.key_text(payload.decode("utf-8", "replace"))
    elif mtype == T_TYPE:
        cps = struct.unpack_from("<H", payload, 0)[0]
        hid.type_text(payload[2:].decode("utf-8", "replace"), cps)
    elif mtype == T_SET_SCREEN:
        hid.set_screen(*struct.unpack_from("<HH", payload, 0))
    elif mtype == T_SYNC:
        if len(payload) >= 4:
            x, y = struct.unpack_from("<HH", payload, 0)
            hid.sync(x, y)
        else:
            hid.sync()
    elif mtype == T_RESET:
        try:
            import microcontroller

            microcontroller.reset()
        except Exception:
            pass
    elif mtype == T_GET_MODE:
        mode = getattr(hid, "mode", "?")
        detail = mode
        try:
            import abs_hid

            detail = mode + ";" + ";".join(abs_hid.describe_devices(usb_hid.devices))
        except Exception as e:
            detail = mode + ";err=" + str(e)
        return encode(T_GET_MODE, seq, detail.encode("utf-8"))
    return None


def _read_available(stream, buf):
    try:
        n = stream.readinto(buf)
    except Exception:
        return None
    if n:
        return bytes(buf[:n])
    return None


def main():
    if usb_cdc.data is None:
        print("usb_cdc.data off")
        return
    hid = Hid()
    print("hid mode:", hid.mode)
    parser = Parser()
    pending = []
    stream = usb_cdc.data
    try:
        stream.timeout = 0.001
    except Exception:
        pass
    buf = bytearray(512)
    while True:
        chunk = _read_available(stream, buf)
        if chunk:
            for mtype, seq, payload in parser.feed(chunk):
                try:
                    reply = dispatch(hid, mtype, payload, pending, seq)
                    if reply:
                        try:
                            stream.write(reply)
                            if hasattr(stream, "flush"):
                                stream.flush()
                        except Exception:
                            pass
                except Exception:
                    pass
        else:
            time.sleep(0.0005)
        if pending:
            now = time.monotonic()
            keep = []
            for due, fn in pending:
                if now >= due:
                    try:
                        fn()
                    except Exception:
                        pass
                else:
                    keep.append((due, fn))
            pending[:] = keep


if __name__ == "__main__":
    main()
