"""Controls mouse movement and clicks using the Interception input driver."""
from __future__ import annotations

import ctypes
import random
import time
from typing import Optional

from app._05_action import humanize as hz

user32 = ctypes.windll.user32

_captured = False
_interception = None
# Exclusive \\.\interceptionXX handles need a beat after CloseHandle before
# the next Start / autologin can open them again.
_REBIND_PAUSES_S = (0.0, 0.05, 0.1, 0.2, 0.4)


def _get_interception():
    global _interception
    if _interception is None:
        import interception as _interception
    return _interception


def _bind_inputs_context(ctx) -> None:
    """Point both the inputs module and star-import copy at the same context."""
    from interception import inputs

    inputs._g_context = ctx
    try:
        import interception

        interception._g_context = ctx
    except Exception:
        pass


def _current_context():
    try:
        from interception import inputs

        return getattr(inputs, "_g_context", None)
    except Exception:
        return None


def _context_usable(ctx) -> bool:
    """True when the context still has a live mouse device handle."""
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


def _destroy_context(ctx) -> None:
    if ctx is None:
        return
    try:
        ctx.destroy()
    except Exception:
        pass


def _open_context():
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
        if _context_usable(ctx):
            return ctx
        _destroy_context(ctx)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Interception context has no live mouse handle")


def _ensure_live_context() -> None:
    ctx = _current_context()
    if _context_usable(ctx):
        return
    _destroy_context(ctx)
    _bind_inputs_context(_open_context())


def _ensure_captured() -> None:
    """Bind keyboard/mouse devices, creating a fresh context after Stop."""
    global _captured
    if _captured and _context_usable(_current_context()):
        return
    _ensure_live_context()
    _get_interception().auto_capture_devices(keyboard=True, mouse=True)
    _captured = True


def prepare_capture() -> None:
    """Re-open devices for a new Start. Call after autologin has shut down."""
    global _captured
    _captured = False
    _ensure_captured()


def is_captured() -> bool:
    return bool(_captured) and _context_usable(_current_context())


def release_capture() -> None:
    """Lift buttons and free Interception devices for the next Start/login.

    Do not construct a replacement context here. ``CreateFileA`` on the
    interception devices is exclusive; an immediate reopen either fails and
    leaves the destroyed context in place (next Start clicks go nowhere) or
    steals the handles from autologin.
    """
    global _captured
    try:
        if _captured:
            ix = _get_interception()
            try:
                ix.mouse_up("left")
                ix.mouse_up("right")
            except Exception:
                pass
        ctx = _current_context()
        _destroy_context(ctx)
        _bind_inputs_context(None)
    except Exception:
        pass
    _captured = False


def _cursor_pos() -> tuple[int, int]:
    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = _POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


class MouseController:
    """Low-level mouse control for game interaction (Interception driver)."""

    def __init__(
        self,
        enabled: bool = True,
        humanize: bool = True,
        rng: Optional[random.Random] = None,
    ):
        self.enabled = enabled
        self.humanize = humanize
        self._rng = rng if rng is not None else random.Random()
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)
        self._last_pos: Optional[tuple[int, int]] = None
        # Mouse-down events (click / hold). The game window
        # typically focuses on the first of these, not on key presses.
        self.button_events = 0

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def _to_absolute(self, x: float, y: float) -> tuple[int, int]:
        """Convert normalized (0-1) or pixel coordinates to absolute (0-65535)."""
        if x <= 1.0 and y <= 1.0:
            ax = int(x * 65535)
            ay = int(y * 65535)
        else:
            ax = int(x / self.screen_width * 65535)
            ay = int(y / self.screen_height * 65535)
        return ax, ay

    def _to_pixels(self, x: float, y: float) -> tuple[int, int]:
        """Convert normalized (0-1) coordinates to screen pixels."""
        if x <= 1.0 and y <= 1.0:
            return int(x * self.screen_width), int(y * self.screen_height)
        return int(x), int(y)

    def _start_pos(self) -> tuple[int, int]:
        if self._last_pos is not None:
            return self._last_pos
        return _cursor_pos()

    def move(self, x: float, y: float, *, snap: bool = False) -> None:
        """Move mouse to position (normalized 0-1 or pixels).

        When humanize is on and ``snap`` is false, walks a short curved path
        with per-step delays. Attack/loot pass ``snap=True`` so aim is not
        delayed (the sprite has already moved since the captured frame).
        """
        if not self.enabled:
            return
        _ensure_captured()
        px, py = self._to_pixels(x, y)

        if snap or not self.humanize:
            _get_interception().move_to(px, py)
            self._last_pos = (px, py)
            return

        x0, y0 = self._start_pos()
        steps = hz.randint(hz.MOVE_STEPS, self._rng)
        points = hz.bezier_points(x0, y0, px, py, steps, self._rng)
        delays = list(hz.path_delays(len(points), rng=self._rng))
        for (qx, qy), delay in zip(points, delays):
            _get_interception().move_to(qx, qy)
            self._last_pos = (qx, qy)
            if delay > 0:
                time.sleep(delay)

    def click(self, x: float, y: float, button: str = "left", *, snap: bool = False) -> None:
        """Move then click. ``snap`` skips the curved path (already aimed)."""
        if not self.enabled:
            return
        _ensure_captured()
        px, py = self._to_pixels(x, y)
        self.move(px, py, snap=snap)
        delay = (
            0.008
            if snap
            else (
                hz.uniform(hz.CLICK_DELAY, self._rng)
                if self.humanize
                else 0.02
            )
        )
        _get_interception().click(px, py, button=button, delay=delay)
        self._last_pos = (px, py)
        self.button_events += 1

    def hold(self, x: float, y: float, duration: float, button: str = "left") -> None:
        """Click and hold at position for duration seconds."""
        if not self.enabled:
            return
        _ensure_captured()
        self.move(x, y)
        with _get_interception().hold_mouse(button):
            time.sleep(duration)
        self.button_events += 1

    def move_and_click(
        self, x: float, y: float, button: str = "left", *, snap: bool = False
    ) -> None:
        """Move to position and click (single action)."""
        self.click(x, y, button, snap=snap)

    def move_and_hold(self, x: float, y: float, duration: float, button: str = "left") -> None:
        """Move to position and hold for duration."""
        self.hold(x, y, duration, button)

    def release(self, button: str = "left") -> None:
        """Release mouse button."""
        if not self.enabled:
            return
        # Do not reopen devices just to lift a button after Stop.
        if not is_captured():
            return
        _get_interception().mouse_up(button)
