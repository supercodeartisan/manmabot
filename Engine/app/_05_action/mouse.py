"""Farm mouse moves and clicks.

The transport is ``input_backend``: Interception or the Pico HID board.
Curves, click timing, and the ground-click repeat stay here.
"""
from __future__ import annotations

import ctypes
import random
import time
from typing import Callable, Optional

from app._05_action import humanize as hz
from app._05_action import input_backend as ib
from ctypes import wintypes

from win32_prototypes import bind_user32

user32 = ctypes.windll.user32
bind_user32(user32)

# Ground click only. Repeat while the body has not accepted the walk.
GROUND_CLICK_INTERVAL_S = 0.1
# Unreadable body: stop the repeat after this long.
GROUND_CLICK_UNREAD_S = 1.0


def _ensure_captured() -> None:
    """Open the hunt input selected in driver setup."""
    ib.ensure_open()


def prepare_capture() -> None:
    """Open hunt input for a new Start. Call after autologin has shut down."""
    ib.prepare_capture()


def is_captured() -> bool:
    return ib.is_captured()


def release_capture() -> None:
    """Lift buttons and free the hunt input.

    Interception handles stay exclusive: this does not reopen them. A Pico
    session closes its COM port and restores pointer acceleration.
    """
    ib.release_capture()


def _cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def _send_button(
    button: str,
    *,
    down: bool,
    px: int | None = None,
    py: int | None = None,
) -> None:
    """Press or release at a screen pixel on the active hunt input."""
    ib.button(button, down=down, px=px, py=py)


def _button_gap_s() -> float:
    return ib.button_gap_s()


def _click_in_place(button: str, px: int, py: int) -> None:
    """Down, hold, up at ``(px, py)``. The hold matches the backend button gap."""
    gap = _button_gap_s()
    _send_button(button, down=True, px=px, py=py)
    if gap > 0.0:
        time.sleep(gap)
    _send_button(button, down=False, px=px, py=py)
    if gap > 0.0:
        time.sleep(gap)


class MouseController:
    """Low-level mouse control for game interaction (hunt input backend)."""

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
            ib.move_abs(px, py)
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
                ib.move_abs(px, py)
                self._last_pos = (px, py)
                self.move_events += 1
                return
            ib.move_abs(qx, qy)
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
        ib.aim(px, py)
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
        ib.aim(px, py)
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
