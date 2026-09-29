"""Screen capture: LC.exe window via mss, then 4:3 content crop.

Same method the bot uses (window mss + aspect crop). No engine imports.
"""
from __future__ import annotations

from typing import Optional, Tuple

import cv2
import numpy as np

from lib.content_crop import DEFAULT_ASPECT, ContentRect, crop_frame
from lib.window_bounds import WindowBounds, WindowTracker

try:
    import mss

    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


class ScreenCapture:
    """Capture the game window client area and crop to content aspect."""

    def __init__(
        self,
        window_title: Optional[str] = None,
        window_process: Optional[str] = None,
        region: Optional[dict] = None,
        fps: int = 30,
        content_aspect: Tuple[int, int] = DEFAULT_ASPECT,
    ):
        self.window_title = window_title
        self.window_process = window_process
        self.region = region
        self.fps = fps
        self.content_aspect = content_aspect
        self._camera = None
        self._mss = None
        self._monitor: Optional[dict] = None
        self._window_mode = bool(window_process or window_title)
        self._tracker = (
            WindowTracker(process_name=window_process, title_hint=window_title)
            if self._window_mode
            else None
        )
        self._bounds: Optional[WindowBounds] = None
        self._content_bounds: Optional[WindowBounds] = None
        self._content_rect: Optional[ContentRect] = None
        self._init_capture()

    @property
    def bounds(self) -> Optional[WindowBounds]:
        return self._bounds

    @property
    def content_bounds(self) -> Optional[WindowBounds]:
        return self._content_bounds

    @property
    def is_minimized(self) -> bool:
        if self._tracker is None:
            return False
        return self._tracker.is_minimized

    def _init_capture(self) -> None:
        if not MSS_AVAILABLE:
            raise RuntimeError("Window capture requires mss (pip install mss)")
        self._mss = mss.mss()
        if not self._window_mode:
            if self.region:
                self._monitor = {
                    "left": int(self.region.get("left", 0)),
                    "top": int(self.region.get("top", 0)),
                    "width": int(self.region.get("width", 1920)),
                    "height": int(self.region.get("height", 1080)),
                }
            else:
                self._monitor = self._mss.monitors[1]

    def _refresh_window_region(self) -> bool:
        if self._tracker is None:
            return False
        bounds = self._tracker.refresh()
        if bounds is None or not bounds.valid:
            self._bounds = None
            self._content_bounds = None
            self._content_rect = None
            self._monitor = None
            return False
        self._bounds = bounds
        self._monitor = bounds.as_region()
        return True

    def _apply_content_crop(self, frame: np.ndarray) -> np.ndarray:
        cropped, rect = crop_frame(frame, self.content_aspect)
        self._content_rect = rect
        origin = self._bounds
        if origin is not None:
            self._content_bounds = WindowBounds(
                left=origin.left + rect.left,
                top=origin.top + rect.top,
                width=rect.width,
                height=rect.height,
                hwnd=origin.hwnd,
            )
        else:
            self._content_bounds = WindowBounds(
                left=rect.left,
                top=rect.top,
                width=rect.width,
                height=rect.height,
            )
        return cropped

    def _grab_mss(self) -> Optional[np.ndarray]:
        if self._mss is None or self._monitor is None:
            return None
        try:
            screenshot = self._mss.grab(self._monitor)
        except Exception:
            return None
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def get_frame(self) -> Optional[np.ndarray]:
        if self._window_mode:
            if self.is_minimized:
                return None
            if not self._refresh_window_region() or self._monitor is None:
                return None
            frame = self._grab_mss()
            if frame is None:
                return None
            return self._apply_content_crop(frame)
        if self._mss and self._monitor:
            frame = self._grab_mss()
            if frame is None:
                return None
            h, w = frame.shape[:2]
            left = int(self._monitor.get("left", 0))
            top = int(self._monitor.get("top", 0))
            self._bounds = WindowBounds(left=left, top=top, width=w, height=h)
            return self._apply_content_crop(frame)
        return None

    def stop(self) -> None:
        if self._mss:
            self._mss.close()
            self._mss = None


def open_capture(settings) -> ScreenCapture:
    return ScreenCapture(
        window_title=settings.window_title,
        window_process=settings.window_process,
        region=settings.region,
        fps=settings.fps,
        content_aspect=settings.content_aspect,
    )


def capture_backend_label(capture: ScreenCapture) -> str:
    process = capture.window_process or ""
    title = capture.window_title or ""
    aspect = capture.content_aspect
    aspect_s = f"{aspect[0]}:{aspect[1]}" if aspect else "?"
    if capture._window_mode:
        target = process or title or "window"
        return f"mss window ({target}) / crop {aspect_s}"
    return f"mss / crop {aspect_s}"
