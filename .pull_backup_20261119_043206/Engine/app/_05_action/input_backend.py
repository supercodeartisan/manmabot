"""Pluggable farm input: Interception (default) or Pico USB HID firmware.

Host commands go over CDC; Windows receives real USB HID reports from the Pico.
Decision / combat policy code is unchanged — only the inject path swaps.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator, Literal, Optional

ButtonName = Literal["left", "right", "middle", "mouse4", "mouse5"]

_BTN_MASK = {
    "left": 0x01,
    "right": 0x02,
    "middle": 0x04,
    "mouse4": 0x08,
    "mouse5": 0x10,
}

# Minimal HID usage map (farm keys). Extended names load from control.keys when present.
_KEYCODES: dict[str, int] = {
    "enter": 0x28,
    "return": 0x28,
    "esc": 0x29,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "delete": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
    "ctrl": 0xE0,
    "control": 0xE0,
    "shift": 0xE1,
    "alt": 0xE2,
    "win": 0xE3,
}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _KEYCODES[_c] = 0x04 + _i
for _i, _c in enumerate("1234567890"):
    _KEYCODES[_c] = 0x1E + _i
for _i in range(1, 13):
    _KEYCODES["f%d" % _i] = 0x3A + (_i - 1)

_MOD_BITS = {
    0xE0: 0x01,
    0xE1: 0x02,
    0xE2: 0x04,
    0xE3: 0x08,
    0xE4: 0x10,
    0xE5: 0x20,
    0xE6: 0x40,
    0xE7: 0x80,
}

_backend_name = "interception"
_pico_com = ""
_pico_baud = 115200
_pico_root = os.environ.get("MANMABOT_PICO_ROOT", r"D:\Rasberrypi")
_screen = (1920, 1080)
_instance: Optional["InputBackend"] = None
_accel_cm = None


def _parse_key(name: str) -> tuple[int, int]:
    """Return (hid_usage, modifier_mask)."""
    n = str(name).strip().lower()
    if n in _KEYCODES:
        code = _KEYCODES[n]
    elif n.startswith("0x"):
        code = int(n, 16)
    elif len(n) == 1 and n in _KEYCODES:
        code = _KEYCODES[n]
    else:
        raise ValueError("unknown key %r" % name)
    return code, _MOD_BITS.get(code, 0)


class InputBackend:
    name = "base"

    def open(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def ready(self) -> bool:
        raise NotImplementedError

    def move_to(self, x: int, y: int) -> None:
        raise NotImplementedError

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        delay: float = 0.02,
    ) -> None:
        raise NotImplementedError

    def mouse_down(self, button: str = "left") -> None:
        raise NotImplementedError

    def mouse_up(self, button: str = "left") -> None:
        raise NotImplementedError

    @contextmanager
    def hold_mouse(self, button: str = "left") -> Iterator[None]:
        self.mouse_down(button)
        try:
            yield
        finally:
            self.mouse_up(button)

    def scroll(self, direction: str = "down", amount: int = 1) -> None:
        raise NotImplementedError

    def key_down(self, key: str) -> None:
        raise NotImplementedError

    def key_up(self, key: str) -> None:
        raise NotImplementedError


class InterceptionBackend(InputBackend):
    name = "interception"

    def __init__(self) -> None:
        self._captured = False

    def open(self) -> None:
        from app._05_action import mouse as mouse_mod

        mouse_mod._ensure_captured_interception()
        self._captured = True

    def close(self) -> None:
        from app._05_action import mouse as mouse_mod

        mouse_mod._release_capture_interception()
        self._captured = False

    def ready(self) -> bool:
        from app._05_action import mouse as mouse_mod

        return bool(mouse_mod.is_captured_interception())

    def _ix(self):
        from app._05_action.mouse import _get_interception

        return _get_interception()

    def move_to(self, x: int, y: int) -> None:
        self._ix().move_to(int(x), int(y))

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        delay: float = 0.02,
    ) -> None:
        if x is None:
            self._ix().click(button=button, delay=delay)
        else:
            self._ix().click(int(x), int(y), button=button, delay=delay)

    def mouse_down(self, button: str = "left") -> None:
        self._ix().mouse_down(button)

    def mouse_up(self, button: str = "left") -> None:
        self._ix().mouse_up(button)

    @contextmanager
    def hold_mouse(self, button: str = "left") -> Iterator[None]:
        with self._ix().hold_mouse(button):
            yield

    def scroll(self, direction: str = "down", amount: int = 1) -> None:
        ix = self._ix()
        for _ in range(max(1, int(amount))):
            ix.scroll(direction)

    def key_down(self, key: str) -> None:
        self._ix().key_down(key)

    def key_up(self, key: str) -> None:
        self._ix().key_up(key)


class PicoHidBackend(InputBackend):
    name = "pico"

    def __init__(
        self,
        port: str = "",
        baud: int = 115200,
        control_root: str = "",
        screen: tuple[int, int] = (1920, 1080),
    ) -> None:
        self.port = str(port or "").strip()
        self.baud = int(baud)
        self.control_root = str(control_root or _pico_root)
        self.screen = (int(screen[0]), int(screen[1]))
        self._client = None
        self._open = False

    def _ensure_path(self) -> None:
        root = self.control_root
        if root and root not in sys.path and os.path.isdir(root):
            sys.path.insert(0, root)

    def _find_port(self) -> str:
        if self.port:
            return self.port
        env = os.environ.get("MANMABOT_PICO_COM", "").strip()
        if env:
            return env
        try:
            import serial.tools.list_ports as lp
        except Exception as exc:
            raise RuntimeError("pyserial required for Pico backend") from exc
        for p in lp.comports():
            if getattr(p, "vid", None) == 0x2E8A and "x.2" in (p.hwid or ""):
                return p.device
        for p in lp.comports():
            if getattr(p, "vid", None) == 0x2E8A:
                return p.device
        raise RuntimeError("Pico CDC data port not found (VID 2E8A)")

    def open(self) -> None:
        if self._open and self._client is not None:
            return
        self._ensure_path()
        from control import ControlClient, SerialTransport
        from control.pointer import no_pointer_accel

        global _accel_cm
        port = self._find_port()
        self.port = port
        self._client = ControlClient(SerialTransport(port, self.baud))
        self._client.set_screen(self.screen[0], self.screen[1])
        try:
            self._client.ensure_mode(timeout=1.5)
        except Exception:
            pass
        if _accel_cm is None:
            _accel_cm = no_pointer_accel()
            _accel_cm.__enter__()
        self._open = True

    def close(self) -> None:
        global _accel_cm
        try:
            if self._client is not None:
                try:
                    self._client.sync()
                except Exception:
                    pass
                try:
                    self._client.close()
                except Exception:
                    pass
        finally:
            self._client = None
            self._open = False
            if _accel_cm is not None:
                try:
                    _accel_cm.__exit__(None, None, None)
                except Exception:
                    pass
                _accel_cm = None

    def ready(self) -> bool:
        return bool(self._open and self._client is not None)

    def _c(self):
        if self._client is None:
            self.open()
        return self._client

    def move_to(self, x: int, y: int) -> None:
        # Fire-and-forget ABS (curve steps). Click path uses aim.
        self._c().move_abs(int(x), int(y), resync=False)

    def click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        delay: float = 0.02,
    ) -> None:
        c = self._c()
        if x is not None and y is not None:
            c.move_abs_aim(int(x), int(y), tolerance=2)
        if delay and delay > 0:
            time.sleep(float(delay))
        mask = _BTN_MASK.get(str(button).lower(), 0x01)
        c.button(mask, 1)
        time.sleep(0.012)
        c.button(mask, 0)

    def mouse_down(self, button: str = "left") -> None:
        self._c().button(_BTN_MASK.get(str(button).lower(), 0x01), 1)

    def mouse_up(self, button: str = "left") -> None:
        self._c().button(_BTN_MASK.get(str(button).lower(), 0x01), 0)

    def scroll(self, direction: str = "down", amount: int = 1) -> None:
        dy = -1 if str(direction).lower() in ("down", "d", "-") else 1
        c = self._c()
        for _ in range(max(1, int(amount))):
            c.wheel(dy)

    def key_down(self, key: str) -> None:
        code, mod = _parse_key(key)
        if mod and code in _MOD_BITS:
            # Modifier alone: press as key with its own modifier bit.
            self._c().key_down(code, modifier=mod)
        else:
            self._c().key_down(code, modifier=mod)

    def key_up(self, key: str) -> None:
        code, mod = _parse_key(key)
        self._c().key_up(code, modifier=mod)


def configure_input_backend(
    name: str = "interception",
    *,
    pico_com: str = "",
    pico_baud: int = 115200,
    pico_root: str = "",
    screen: tuple[int, int] | None = None,
) -> None:
    """Select backend for the next prepare_capture. Closes the current one."""
    global _backend_name, _pico_com, _pico_baud, _pico_root, _screen, _instance
    want = str(name or "interception").strip().lower()
    if want not in ("interception", "pico"):
        want = "interception"
    env = os.environ.get("MANMABOT_INPUT_BACKEND", "").strip().lower()
    if env in ("interception", "pico"):
        want = env
    _backend_name = want
    if pico_com:
        _pico_com = str(pico_com).strip()
    if pico_baud:
        _pico_baud = int(pico_baud)
    if pico_root:
        _pico_root = str(pico_root)
    if screen is not None:
        _screen = (int(screen[0]), int(screen[1]))
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
        _instance = None


def backend_name() -> str:
    return _backend_name


def get_backend() -> InputBackend:
    global _instance
    if _instance is not None and _instance.ready():
        return _instance
    if _backend_name == "pico":
        _instance = PicoHidBackend(
            port=_pico_com,
            baud=_pico_baud,
            control_root=_pico_root,
            screen=_screen,
        )
    else:
        _instance = InterceptionBackend()
    _instance.open()
    return _instance


def prepare_capture() -> None:
    global _instance
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
        _instance = None
    get_backend()


def release_capture() -> None:
    global _instance
    if _instance is None:
        return
    try:
        try:
            _instance.mouse_up("left")
            _instance.mouse_up("right")
        except Exception:
            pass
        _instance.close()
    finally:
        _instance = None


def is_captured() -> bool:
    return _instance is not None and _instance.ready()
