"""Hunt mouse/keyboard transport.

Login and party chat stay on the Interception driver. This module only
serves the farm controllers (``MouseController`` / ``KeyboardController``).

``interception`` uses the kernel filter. ``pico`` sends the same clicks and
keys through the Raspberry Pi Pico HID board (``Drivers/RasberryPi/control``).
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path
from typing import Any

_REBIND_PAUSES_S = (0.0, 0.05, 0.1, 0.2, 0.4)
_PICO_BUTTON_GAP_S = 0.012
_PICO_NAMES = {"pico", "raspberry", "raspberrypi", "rasberry", "rasberrypi"}

_active: "HuntInput | None" = None


def normalize_backend_name(value: object) -> str:
    name = str(value or "").strip().lower()
    if name in _PICO_NAMES:
        return "pico"
    return "interception"


def control_package_root() -> Path:
    """Directory that contains the ``control`` package."""
    env = os.environ.get("MANMABOT_PICO_ROOT", "").strip()
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[3]
    top = repo / "Drivers" / "RasberryPi"
    if (top / "control" / "client.py").is_file():
        return top
    nested = top / "Rasberrypi"
    if (nested / "control" / "client.py").is_file():
        return nested
    return top


def _ensure_control_path() -> None:
    root = str(control_package_root())
    if root not in sys.path:
        sys.path.insert(0, root)


# Raspberry Pi Pico, and Adafruit's id used by some CircuitPython boards.
_PICO_VIDS = {0x2E8A, 0x239A}


def _comports() -> list[Any]:
    try:
        from serial.tools import list_ports

        return list(list_ports.comports())
    except Exception:
        return []


def _pico_interface_rank(hwid: str) -> int:
    """0 is the data CDC (interface 2). Higher ranks are tried after that."""
    text = str(hwid or "")
    folded = text.lower()
    if folded.endswith(":x.2") or "mi_02" in folded:
        return 0
    if "x.2" in folded:
        return 1
    return 2


def pico_candidate_ports() -> list[str]:
    """Pico COM names, data interface first, then the other Pico interfaces."""
    ranked: list[tuple[int, str]] = []
    for port in _comports():
        if getattr(port, "vid", None) not in _PICO_VIDS:
            continue
        device = str(getattr(port, "device", "") or "").strip()
        if not device:
            continue
        ranked.append((_pico_interface_rank(str(getattr(port, "hwid", "") or "")), device))
    ranked.sort(key=lambda item: item[0])
    ordered: list[str] = []
    for _rank, device in ranked:
        if device not in ordered:
            ordered.append(device)
    return ordered


def find_pico_data_port() -> str:
    """First Pico data-interface name, without opening the port."""
    ports = pico_candidate_ports()
    return ports[0] if ports else ""


_pico_scan_cache: tuple[float, int, str] | None = None
_last_pico_scan_error = ""
_PICO_SCAN_TTL_S = 8.0


def scan_pico_abs_port(baud: int = 115200) -> str:
    """Open each Pico COM and keep the one whose firmware reports ABS.

    A saved name such as COM4 can be the REPL or a hub interface. That port
    opens and then ``GET_MODE`` times out. The data interface is whichever
    Pico COM answers ``ABS``.
    """
    global _last_pico_scan_error
    candidates = pico_candidate_ports()
    if not candidates:
        _last_pico_scan_error = ""
        return ""
    _ensure_control_path()
    from control.client import ControlClient
    from control.transport import SerialTransport

    tried: list[str] = []
    for device in candidates:
        client = None
        try:
            client = ControlClient(SerialTransport(device, int(baud)))
            mode = str(client.ensure_mode(timeout=0.6) or "").split(";", 1)[0].strip()
        except Exception:
            mode = ""
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
        tried.append(f"{device}={mode or 'unknown'}")
        if mode == "ABS":
            _last_pico_scan_error = ""
            return device
    _last_pico_scan_error = (
        "Pico HID mode is not ABS ("
        + ", ".join(tried)
        + "). Absolute mouse firmware is required."
    )
    return ""


def resolve_pico_port(preferred: str = "", baud: int = 115200) -> str:
    """Live Pico data COM that answers ABS. A saved name is ignored.

    The saved name can still be plugged in and still be the REPL (``x.0``).
    ``MANMABOT_PICO_COM`` is the only name that skips the scan.
    """
    del preferred
    global _pico_scan_cache
    forced = os.environ.get("MANMABOT_PICO_COM", "").strip()
    if forced:
        return forced
    try:
        rate = int(baud)
    except (TypeError, ValueError):
        rate = 115200
    now = time.time()
    cached = _pico_scan_cache
    if cached is not None and cached[2] and (now - cached[0]) < _PICO_SCAN_TTL_S and cached[1] == rate:
        return cached[2]
    found = scan_pico_abs_port(rate)
    if found:
        _pico_scan_cache = (now, rate, found)
    return found


def pico_scan_error() -> str:
    return _last_pico_scan_error


def pico_port_choices(preferred: str = "") -> tuple[list[str], str]:
    """Every COM name, with the chosen Pico data port first."""
    chosen = resolve_pico_port(preferred)
    ordered: list[str] = []
    for name in (chosen, find_pico_data_port()):
        text = str(name or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    for port in _comports():
        text = str(getattr(port, "device", "") or "").strip()
        if text and text not in ordered:
            ordered.append(text)
    return ordered, chosen


def resolve_hunt_input(profile: Any | None = None) -> tuple[str, str, int]:
    """Backend name, Pico data COM, baud. Environment overrides the profile."""
    env_name = os.environ.get("MANMABOT_INPUT_BACKEND", "").strip()
    env_port = os.environ.get("MANMABOT_PICO_COM", "").strip()
    env_baud = os.environ.get("MANMABOT_PICO_BAUD", "").strip()
    name = normalize_backend_name(
        env_name or getattr(profile, "input_backend", "interception")
    )
    try:
        baud = int(env_baud or getattr(profile, "pico_baud", 115200) or 115200)
    except (TypeError, ValueError):
        baud = 115200
    if baud < 1200 or baud > 1_000_000:
        baud = 115200
    port = env_port
    if name == "pico" and not env_port:
        port = resolve_pico_port("", baud)
        if profile is not None:
            try:
                profile.pico_com = port
            except Exception:
                pass
    return name, port, baud


def backend_name() -> str:
    return current().kind


def holds_interception_devices() -> bool:
    """True when the farm path owns the exclusive Interception handles.

    Party chat must borrow those handles. A Pico session does not hold them,
    so chat can open ``interception.dll`` without closing the COM port.
    """
    active = current()
    return active.kind == "interception" and active.ready()


def configure_hunt_input(profile: Any | None = None) -> str:
    """Select the hunt transport. Does not open a device."""
    global _active
    name, port, baud = resolve_hunt_input(profile)
    cur = _active
    if (
        isinstance(cur, PicoHuntInput)
        and name == "pico"
        and cur.port == port
        and cur.baud == baud
    ):
        return name
    if isinstance(cur, InterceptionHuntInput) and name == "interception":
        return name
    if cur is not None:
        try:
            cur.close()
        except Exception:
            pass
    _active = PicoHuntInput(port, baud) if name == "pico" else InterceptionHuntInput()
    return name


def current() -> "HuntInput":
    global _active
    if _active is None:
        _active = InterceptionHuntInput()
    return _active


def ensure_open() -> None:
    current().ensure_open()


def prepare_capture() -> None:
    current().prepare()


def release_capture() -> None:
    current().close()


def is_captured() -> bool:
    return current().ready()


def move_abs(x: int, y: int) -> None:
    current().move_abs(int(x), int(y))


def aim(x: int, y: int) -> None:
    current().aim(int(x), int(y))


def button(name: str, *, down: bool, px: int | None = None, py: int | None = None) -> None:
    current().button(name, down=down, px=px, py=py)


def button_gap_s() -> float:
    return current().button_gap_s()


def scroll_wheel(direction: str) -> None:
    current().ensure_open()
    current().wheel(direction)


def list_wheel_count(notches: int) -> int:
    """How many detents to send so a list moves ``notches`` rows.

    Interception's 18 and 36 land on the calibrated row. Pico's same counts
    land on the row above (글루딘 여관 → 창고지기, 은기사 여관 → 창고지기).
    The first Pico detent does not move that list, so a Pico burst sends one more.
    """
    count = max(0, int(notches))
    if count and getattr(current(), "kind", "") == "pico":
        return count + 1
    return count


def key_down(key: str) -> None:
    current().key_down(str(key))


def key_up(key: str) -> None:
    current().key_up(str(key))


def list_pico_ports() -> list[str]:
    ports, _chosen = pico_port_choices("")
    return ports


def probe_pico(port: str, baud: int = 115200) -> tuple[bool, str]:
    """Open the data COM, ping, and close. Does not move the cursor."""
    text = resolve_pico_port(str(port or "").strip())
    if not text:
        return False, "Pico data COM was not found. Plug in the board and try again."
    active = _active
    if (
        isinstance(active, PicoHuntInput)
        and active.ready()
        and active.port == text
    ):
        return True, f"Pico ready on {text} (hunt session)."
    client = None
    try:
        _ensure_control_path()
        from control.client import ControlClient
        from control.transport import SerialTransport

        client = ControlClient(SerialTransport(text, int(baud)))
        rtt = client.ping(timeout=0.8, samples=1)
        if rtt is None:
            return False, f"{text} opened but the board did not answer PING."
        mode = str(client.ensure_mode(timeout=0.8) or "").split(";", 1)[0].strip()
        if mode != "ABS":
            return (
                False,
                f"{text} answered ({float(rtt):.0f} ms) but HID mode is "
                f"{mode or 'unknown'}. Copy boot.py and replug USB.",
            )
        return True, f"Pico ready on {text} ({mode}, {float(rtt):.0f} ms)."
    except Exception as exc:
        return False, f"Pico {text} unavailable: {exc}"
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


class HuntInput:
    kind = "interception"

    def ensure_open(self) -> None:
        raise NotImplementedError

    def prepare(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def ready(self) -> bool:
        return False

    def move_abs(self, x: int, y: int) -> None:
        raise NotImplementedError

    def aim(self, x: int, y: int) -> None:
        return None

    def button(
        self,
        name: str,
        *,
        down: bool,
        px: int | None = None,
        py: int | None = None,
    ) -> None:
        raise NotImplementedError

    def wheel(self, direction: str) -> None:
        raise NotImplementedError

    def key_down(self, key: str) -> None:
        raise NotImplementedError

    def key_up(self, key: str) -> None:
        raise NotImplementedError

    def button_gap_s(self) -> float:
        return 0.0


class InterceptionHuntInput(HuntInput):
    """PyPI ``interception`` package. Same device handling the farm path used."""

    kind = "interception"

    def __init__(self) -> None:
        self._captured = False
        self._lib = None

    def _library(self):
        if self._lib is None:
            import interception as lib

            self._lib = lib
        return self._lib

    def _current_context(self):
        try:
            from interception import inputs

            return getattr(inputs, "_g_context", None)
        except Exception:
            return None

    def _context_usable(self, ctx) -> bool:
        if ctx is None:
            return False
        devices = getattr(ctx, "devices", None) or []
        if not devices:
            return False
        for index, device in enumerate(devices):
            handle = getattr(device, "handle", -1)
            if handle in (-1, 0, None):
                continue
            if 10 <= index <= 19:
                return True
        return False

    def _bind_inputs_context(self, ctx) -> None:
        from interception import inputs

        inputs._g_context = ctx
        try:
            import interception

            interception._g_context = ctx
        except Exception:
            pass

    def _destroy_context(self, ctx) -> None:
        if ctx is None:
            return
        try:
            ctx.destroy()
        except Exception:
            pass

    def _open_context(self):
        from interception.interception import Interception

        last_error: Exception | None = None
        for pause in _REBIND_PAUSES_S:
            if pause:
                time.sleep(pause)
            try:
                ctx = Interception()
            except Exception as exc:
                last_error = exc
                continue
            if self._context_usable(ctx):
                return ctx
            self._destroy_context(ctx)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Interception context has no live mouse handle")

    def _ensure_live_context(self) -> None:
        ctx = self._current_context()
        if self._context_usable(ctx):
            return
        self._destroy_context(ctx)
        self._bind_inputs_context(self._open_context())

    def ready(self) -> bool:
        return bool(self._captured) and self._context_usable(self._current_context())

    def ensure_open(self) -> None:
        if self._captured and self._context_usable(self._current_context()):
            return
        self._ensure_live_context()
        self._library().auto_capture_devices(keyboard=True, mouse=True)
        self._captured = True

    def prepare(self) -> None:
        """Re-bind devices. A live context is kept; a dead one is replaced."""
        self._captured = False
        self.ensure_open()

    def close(self) -> None:
        try:
            if self._captured:
                try:
                    self.button("left", down=False)
                    self.button("right", down=False)
                except Exception:
                    pass
            ctx = self._current_context()
            self._destroy_context(ctx)
            self._bind_inputs_context(None)
        except Exception:
            pass
        self._captured = False

    def move_abs(self, x: int, y: int) -> None:
        self.ensure_open()
        self._library().move_to(int(x), int(y))

    def button(
        self,
        name: str,
        *,
        down: bool,
        px: int | None = None,
        py: int | None = None,
    ) -> None:
        from ctypes import wintypes

        from interception._utils import to_interception_coordinate
        from interception.constants import MouseButtonFlag, MouseFlag
        from interception.exceptions import UnknownButtonError
        from interception.strokes import MouseStroke

        from win32_prototypes import bind_user32

        try:
            states = MouseButtonFlag.from_string(name)
        except KeyError as exc:
            raise UnknownButtonError(name) from exc
        flag = int(states[0] if down else states[1])
        ctx = self._current_context()
        if not self._context_usable(ctx):
            return
        if px is None or py is None:
            user32 = ctypes.windll.user32
            bind_user32(user32)
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            px, py = int(pt.x), int(pt.y)
        ax, ay = to_interception_coordinate(int(px), int(py))
        stroke = MouseStroke(int(MouseFlag.MOUSE_MOVE_ABSOLUTE), flag, 0, int(ax), int(ay))
        ctx.send(ctx.mouse, stroke)

    def wheel(self, direction: str) -> None:
        self.ensure_open()
        self._library().scroll(str(direction))

    def key_down(self, key: str) -> None:
        self.ensure_open()
        self._library().key_down(key)

    def key_up(self, key: str) -> None:
        self.ensure_open()
        self._library().key_up(key)

    def button_gap_s(self) -> float:
        from interception.inputs import MOUSE_BUTTON_DELAY

        return float(MOUSE_BUTTON_DELAY)


class PicoHuntInput(HuntInput):
    """USB HID via the Pico ``control`` client. Curve steps stay open-loop."""

    kind = "pico"

    def __init__(self, port: str, baud: int = 115200) -> None:
        self.port = str(port or "").strip()
        self.baud = int(baud)
        self._client = None
        self._accel_saved = None

    def ready(self) -> bool:
        return self._client is not None

    def ensure_open(self) -> None:
        if self.ready():
            return
        self.open()

    def prepare(self) -> None:
        if self.ready():
            return
        self.open()

    def open(self) -> None:
        self.port = resolve_pico_port(self.port, self.baud)
        if not self.port:
            raise RuntimeError(
                pico_scan_error()
                or "Pico data COM was not found. Plug in the board and try again."
            )
        _ensure_control_path()
        from control.client import ControlClient
        from control.pointer import get_windows_accel, set_windows_accel
        from control.transport import SerialTransport

        self.close()
        saved = get_windows_accel()
        try:
            set_windows_accel((0, 0, 0))
        except Exception:
            saved = None
        self._accel_saved = saved
        try:
            client = ControlClient(SerialTransport(self.port, self.baud))
            from win32_prototypes import bind_user32

            user32 = ctypes.windll.user32
            bind_user32(user32)
            width = int(user32.GetSystemMetrics(0) or 1920)
            height = int(user32.GetSystemMetrics(1) or 1080)
            client.set_screen(width, height)
            mode = str(client.ensure_mode(timeout=1.0) or "").split(";", 1)[0].strip()
            if mode != "ABS":
                try:
                    client.close()
                except Exception:
                    pass
                raise RuntimeError(
                    f"Pico HID mode is {mode or 'unknown'} on {self.port}. "
                    "Absolute mouse firmware is required."
                )
            rtt = client.ping(timeout=0.8, samples=1)
            if rtt is None:
                try:
                    client.close()
                except Exception:
                    pass
                raise RuntimeError(f"Pico on {self.port} did not answer PING.")
            self._client = client
        except Exception:
            self._restore_accel()
            raise

    def _restore_accel(self) -> None:
        saved = self._accel_saved
        self._accel_saved = None
        if saved is None:
            return
        try:
            _ensure_control_path()
            from control.pointer import set_windows_accel

            set_windows_accel(saved)
        except Exception:
            pass

    def close(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                from control import protocol as proto

                client.button_up(proto.BTN_LEFT)
                client.button_up(proto.BTN_RIGHT)
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        self._restore_accel()

    def _require(self):
        self.ensure_open()
        if self._client is None:
            raise RuntimeError("Pico link is not open.")
        return self._client

    def move_abs(self, x: int, y: int) -> None:
        self._require().move_abs(int(x), int(y), resync=False)

    def aim(self, x: int, y: int) -> None:
        try:
            self._require().move_abs_aim(int(x), int(y))
        except Exception:
            self.move_abs(x, y)

    def _mask(self, name: str) -> int:
        from control import protocol as proto

        key = str(name or "left").strip().lower()
        if key == "right":
            return int(proto.BTN_RIGHT)
        if key == "middle":
            return int(proto.BTN_MIDDLE)
        if key != "left":
            raise ValueError(f"Unknown mouse button: {name}")
        return int(proto.BTN_LEFT)

    def button(
        self,
        name: str,
        *,
        down: bool,
        px: int | None = None,
        py: int | None = None,
    ) -> None:
        client = self._require()
        # Pico clicks the cursor, not the pixel in the packet. Settle first.
        if down and px is not None and py is not None:
            client.move_abs_aim(int(px), int(py))
        mask = self._mask(name)
        if down:
            client.button_down(mask)
        else:
            client.button_up(mask)

    def wheel(self, direction: str) -> None:
        text = str(direction or "").strip().lower()
        notches = -1 if text in {"down", "backward", "-"} else 1
        self._require().wheel(notches)

    def _code(self, key: str) -> int:
        _ensure_control_path()
        from control.keys import parse_key

        return int(parse_key(key))

    def key_down(self, key: str) -> None:
        self._require().key_down(self._code(key))

    def key_up(self, key: str) -> None:
        self._require().key_up(self._code(key))

    def button_gap_s(self) -> float:
        return _PICO_BUTTON_GAP_S
