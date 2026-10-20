"""Lend the Interception devices to ``enter_chat`` for one call.

The bot's mouse/keyboard context holds the devices exclusively; ``ec_run``
opens its own context and fails if they are still held.
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

        is_captured = is_captured or mouse.is_captured
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
