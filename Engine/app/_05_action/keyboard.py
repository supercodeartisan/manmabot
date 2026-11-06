"""Farm keyboard input through the hunt input backend."""
from __future__ import annotations

import random
import time
from typing import Optional

from app._05_action import humanize as hz
from app._05_action import input_backend as ib


class KeyboardController:
    """Low-level keyboard control for game interaction (hunt input backend)."""

    def __init__(
        self,
        enabled: bool = True,
        humanize: bool = True,
        rng: Optional[random.Random] = None,
    ):
        self.enabled = enabled
        self.humanize = humanize
        self._rng = rng if rng is not None else random.Random()

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def press(self, key: str, duration: float | None = None) -> None:
        """Press and release a key with a humanized hold duration."""
        if not self.enabled:
            return
        ib.ensure_open()
        if duration is None:
            duration = (
                hz.uniform(hz.KEY_HOLD, self._rng)
                if self.humanize
                else 0.05
            )
        ib.key_down(key)
        time.sleep(duration)
        ib.key_up(key)

    def hold(self, key: str) -> None:
        """Hold a key down (call release to let go)."""
        if not self.enabled:
            return
        ib.ensure_open()
        ib.key_down(key)

    def release(self, key: str) -> None:
        """Release a held key."""
        if not self.enabled:
            return
        ib.ensure_open()
        ib.key_up(key)

    def tap(self, key: str, count: int = 1, interval: float | None = None) -> None:
        """Tap a key multiple times."""
        for i in range(count):
            self.press(key)
            if i + 1 < count:
                gap = (
                    interval
                    if interval is not None
                    else (
                        hz.uniform((0.06, 0.18), self._rng)
                        if self.humanize
                        else 0.1
                    )
                )
                time.sleep(gap)

    def combo(self, *keys: str, hold_time: float | None = None) -> None:
        """Press multiple keys simultaneously."""
        if not self.enabled:
            return
        ib.ensure_open()
        if hold_time is None:
            hold_time = (
                hz.uniform(hz.KEY_HOLD, self._rng)
                if self.humanize
                else 0.1
            )
        for key in keys:
            ib.key_down(key)
        time.sleep(hold_time)
        for key in reversed(keys):
            ib.key_up(key)
