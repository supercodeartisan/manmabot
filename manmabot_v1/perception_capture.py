"""Shared screen capture used by live bot perception and hotbar detection.

Both paths must open the same ``ScreenCapture`` built from engine
``capture.yaml`` (window mss on LC.exe + content-aspect crop). Do not add a
second grab path for hotbar tooling.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import numpy as np


def open_perception_capture(config: dict | None = None) -> Any:
    """Create the same capture object the bot worker uses for vision/hotbar."""
    from tool.utils import load_config
    from app._01_capture.screen_capture import create_capture_from_config

    cfg = config if config is not None else load_config()
    return create_capture_from_config(cfg)


def grab_perception_frame(
    capture: Any,
    *,
    retries: int = 40,
    wait_s: float = 0.05,
) -> Optional[np.ndarray]:
    """Poll ``capture.get_frame()`` until a frame arrives (bot-style)."""
    get_frame = getattr(capture, "get_frame", None)
    if not callable(get_frame):
        return None
    for _ in range(max(1, int(retries))):
        frame = get_frame()
        if frame is not None:
            return frame
        time.sleep(wait_s)
    return None


def capture_backend_label(capture: Any) -> str:
    """Short status string for UIs (inspector / debug)."""
    process = getattr(capture, "window_process", None) or ""
    title = getattr(capture, "window_title", None) or ""
    aspect = getattr(capture, "content_aspect", None)
    aspect_s = (
        f"{aspect[0]}:{aspect[1]}"
        if isinstance(aspect, (tuple, list)) and len(aspect) == 2
        else "?"
    )
    if getattr(capture, "_window_mode", False):
        target = process or title or "window"
        return f"bot capture / mss window ({target}) / crop {aspect_s}"
    if getattr(capture, "_camera", None) is not None:
        return f"bot capture / dxcam / crop {aspect_s}"
    return f"bot capture / mss / crop {aspect_s}"
