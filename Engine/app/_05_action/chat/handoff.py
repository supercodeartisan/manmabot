"""Lend the Interception devices to ``enter_chat`` for one call.

The farm path holds those devices only while hunt input is Interception.
A Pico session leaves the COM port open; chat opens Interception itself.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable, Iterator

# Closed device handles need a beat before another context can open them.
RELEASE_SETTLE_S = 0.1


@contextmanager
def bot_input_released(
    *,
    is_captured: Callable[[], bool] | None = None,
    release: Callable[[], None] | None = None,
    reacquire: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[None]:
    """Release the bot's capture if held, and take it back afterwards."""
    if is_captured is None or release is None or reacquire is None:
        from app._05_action import mouse
        from app._05_action.input_backend import holds_interception_devices

        is_captured = is_captured or holds_interception_devices
        release = release or mouse.release_capture
        reacquire = reacquire or mouse.prepare_capture

    held = bool(is_captured())
    if held:
        release()
        sleep(RELEASE_SETTLE_S)
    try:
        yield
    finally:
        if held:
            reacquire()


__all__ = ["RELEASE_SETTLE_S", "bot_input_released"]
