"""Controls mouse movement and clicks using the Interception input driver."""
from __future__ import annotations

import ctypes
import random
import time
from typing import Callable, Optional

from app._05_action import humanize as hz
from ctypes import wintypes

from win32_prototypes import bind_user32

user32 = ctypes.windll.user32
bind_user32(user32)

_captured = False
_interception = None
# Exclusive \\.\interceptionXX handles need a beat after CloseHandle before
# the next Start / autologin can open them again.
_REBIND_PAUSES_S = (0.0, 0.05, 0.1, 0.2, 0.4)
# Ground click only. Repeat while the body has not accepted the walk.
GROUND_CLICK_INTERVAL_S = 0.1
# Unreadable body: stop the repeat after this long.
GROUND_CLICK_UNREAD_S = 1.0


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
            try:
                _send_button("left", down=False)
                _send_button("right", down=False)
            except Exception:
                pass
        ctx = _current_context()
        _destroy_context(ctx)
        _bind_inputs_context(None)
    except Exception:
        pass
    _captured = False


def _cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _absolute_xy(px: int, py: int) -> tuple[int, int]:
    """Same 0..65535 scale ``move_to`` uses for this pixel."""
    from interception._utils import to_interception_coordinate

    ax, ay = to_interception_coordinate(int(px), int(py))
    return int(ax), int(ay)


def _send_button(
    button: str,
    *,
    down: bool,
    px: int | None = None,
    py: int | None = None,
) -> None:
    """Press or release at a screen pixel.

    The button stroke carries that pixel as an absolute coordinate, the same
    way login clicks do. An absolute (0, 0) stroke clicks the screen origin.
    A relative stroke with no position was ignored on the customer PC.
    Without a pixel, the current cursor is used so a release does not jump.
    """
    from interception.constants import MouseButtonFlag, MouseFlag
    from interception.exceptions import UnknownButtonError
    from interception.strokes import MouseStroke

    try:
        states = MouseButtonFlag.from_string(button)
    except KeyError as exc:
        raise UnknownButtonError(button) from exc
    flag = int(states[0] if down else states[1])
    ctx = _current_context()
    if not _context_usable(ctx):
        return
    if px is None or py is None:
        px, py = _cursor_pos()
    ax, ay = _absolute_xy(px, py)
    stroke = MouseStroke(int(MouseFlag.MOUSE_MOVE_ABSOLUTE), flag, 0, ax, ay)
    ctx.send(ctx.mouse, stroke)


def _button_gap_s() -> float:
    from interception.inputs import MOUSE_BUTTON_DELAY

    return float(MOUSE_BUTTON_DELAY)


def _click_in_place(button: str, px: int, py: int) -> None:
    """Down, hold, up at ``(px, py)``. The hold matches the library button delay."""
    gap = _button_gap_s()
    _send_button(button, down=True, px=px, py=py)
    if gap > 0.0:
        time.sleep(gap)
    _send_button(button, down=False, px=px, py=py)
    if gap > 0.0:
        time.sleep(gap)


class MouseController:
    """Low-level mouse control for game interaction (Interception driver)."""

    def __init__(
        self,
        enabled: bool = True,
        humanize: bool = True,
        rng: Optional[random.Random] = None,
        humanize_move: Optional[bool] = None,
    ):
        self.enabled = enabled
        self.humanize = humanize
        # Curved path. Independent of key/click timing (``humanize``).
        self.humanize_move = humanize if humanize_move is None else bool(humanize_move)
        self._rng = rng if rng is not None else random.Random()
        self.screen_width = user32.GetSystemMetrics(0)
        self.screen_height = user32.GetSystemMetrics(1)
        self._last_pos: Optional[tuple[int, int]] = None
        # Mouse-down events (click / hold). The game window
        # typically focuses on the first of these, not on key presses.
        self.button_events = 0
        # Cursor moves (hover probes and aim). Used for click-vs-hover diagnostics.
        self.move_events = 0

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

        When ``humanize_move`` is on, walks a short curve that finishes within
        ``MOVE_BUDGET_S`` (0.02s), including attack and travel aims. ``snap``
        is ignored in that mode. When the toggle is off, the cursor jumps.
        """
        if not self.enabled:
            return
        _ensure_captured()
        px, py = self._to_pixels(x, y)

        if not self.humanize_move:
            _get_interception().move_to(px, py)
            self._last_pos = (px, py)
            self.move_events += 1
            return

        self._move_curved(px, py)

    def _move_curved(self, px: int, py: int) -> None:
        """Bezier to ``(px, py)``. Sleeps stop once the 0.02s budget is spent."""
        x0, y0 = self._start_pos()
        steps = hz.randint(hz.MOVE_STEPS, self._rng)
        points = hz.bezier_points(x0, y0, float(px), float(py), steps, self._rng)
        if not points:
            points = [(px, py)]
        started = time.perf_counter()
        budget = float(hz.MOVE_BUDGET_S)
        last = len(points) - 1
        for i, (qx, qy) in enumerate(points):
            if i != last and (time.perf_counter() - started) >= budget:
                _get_interception().move_to(px, py)
                self._last_pos = (px, py)
                self.move_events += 1
                return
            _get_interception().move_to(qx, qy)
            self._last_pos = (qx, qy)
            self.move_events += 1
            if i == last:
                return
            remain = budget - (time.perf_counter() - started)
            slots = last - i
            if remain <= 0.0 or slots <= 0:
                continue
            delay = self._rng.uniform(0.0, remain * 0.5 / slots)
            if delay > 0.0:
                time.sleep(min(delay, remain))

    def click(
        self,
        x: float,
        y: float,
        button: str = "left",
        *,
        snap: bool = False,
        until_walk: bool = False,
        cursor_ok: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Move then click. The move curve follows ``humanize_move``, not ``snap``.

        ``until_walk`` is for a ground hop. The click repeats every 0.1s while
        the body is still busy, and stops when the body stands or walks.
        Attack and interface clicks leave it false.

        ``cursor_ok`` is checked before each until_walk *re*-click (not the
        first). Travel passes a NORMAL cursor gate so a mid-loop attack
        hover cannot fire.
        """
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
        if delay > 0.0:
            time.sleep(delay)
        if until_walk:
            clicks = self._click_until_walk(button, px, py, cursor_ok=cursor_ok)
        else:
            _click_in_place(button, px, py)
            clicks = 1
        self.last_ground_clicks = clicks
        self._last_pos = (px, py)
        self.button_events += clicks

    def _click_until_walk(
        self,
        button: str,
        px: int,
        py: int,
        *,
        cursor_ok: Optional[Callable[[], bool]] = None,
    ) -> int:
        """Click now, then every 0.1s, until stand/walk.

        An unreadable body slot stops the repeat after 1s. One click is enough
        when the body is already standing or already walking. When ``cursor_ok``
        is set, a False result clicks nothing and stops the repeat. The caller
        already moved and waited.
        """
        from app._05_action.body_pose import BREATH_VFT, MOVE_VFTS, read_action
        from app.bot_log import event

        if callable(cursor_ok):
            try:
                allowed = bool(cursor_ok())
            except Exception:
                allowed = False
            if not allowed:
                event("clickgap", "ground-click done how=cursor clicks=0")
                return 0
        _click_in_place(button, px, py)
        clicks = 1
        t0 = time.perf_counter()
        unread_deadline = t0 + float(GROUND_CLICK_UNREAD_S)
        pulse = getattr(self, "_pose_pulse", None)
        while True:
            if callable(pulse):
                try:
                    pulse()
                except Exception:
                    pass
            try:
                body, _cmd = read_action()
            except Exception:
                body = None
            if body == BREATH_VFT:
                how = "stand"
            elif body in MOVE_VFTS:
                how = "move"
            elif body is None and time.perf_counter() >= unread_deadline:
                how = "force"
            else:
                how = ""
            if how:
                if clicks > 1 or how == "force":
                    event(
                        "clickgap",
                        "ground-click done how=%s clicks=%s",
                        how,
                        clicks,
                    )
                return clicks
            time.sleep(float(GROUND_CLICK_INTERVAL_S))
            if callable(cursor_ok):
                try:
                    allowed = bool(cursor_ok())
                except Exception:
                    allowed = False
                if not allowed:
                    event(
                        "clickgap",
                        "ground-click done how=cursor clicks=%s",
                        clicks,
                    )
                    return clicks
            _click_in_place(button, px, py)
            clicks += 1

    def hold(self, x: float, y: float, duration: float, button: str = "left") -> None:
        """Click and hold at position for duration seconds."""
        if not self.enabled:
            return
        _ensure_captured()
        px, py = self._to_pixels(x, y)
        self.move(px, py)
        gap = _button_gap_s()
        _send_button(button, down=True, px=px, py=py)
        if gap > 0.0:
            time.sleep(gap)
        try:
            time.sleep(duration)
        finally:
            _send_button(button, down=False, px=px, py=py)
            if gap > 0.0:
                time.sleep(gap)
        self.button_events += 1

    def move_and_click(
        self,
        x: float,
        y: float,
        button: str = "left",
        *,
        snap: bool = False,
        until_walk: bool = False,
        cursor_ok: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Move to position and click."""
        self.click(
            x,
            y,
            button,
            snap=snap,
            until_walk=until_walk,
            cursor_ok=cursor_ok,
        )

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
        _send_button(button, down=False)
        gap = _button_gap_s()
        if gap > 0.0:
            time.sleep(gap)
