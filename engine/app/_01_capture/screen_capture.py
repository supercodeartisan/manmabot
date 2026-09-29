"""Captures the game screen and provides image frames in real time."""
from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple

from app.bot_log import get_logger
from app._01_capture.content_crop import (
    DEFAULT_ASPECT,
    ContentRect,
    crop_frame,
)
from app._01_capture.window_bounds import WindowBounds, WindowTracker

try:
    import dxcam
    DXCAM_AVAILABLE = True
except ImportError:
    DXCAM_AVAILABLE = False

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


class ScreenCapture:
    """Screen capture using dxcam (fast) or mss (fallback).

    When ``window_process`` is set, captures only the game window client
    area and refreshes bounds every frame so resize/move stays in sync.

    Frames are cropped to the configured content aspect (default 4:3) so
    fullscreen pillarboxing does not enter vision or click mapping.
    """

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
        """Latest full game window client bounds (before content crop)."""
        return self._bounds

    @property
    def content_bounds(self) -> Optional[WindowBounds]:
        """Desktop rect of the cropped 4:3 game content (use for clicks)."""
        return self._content_bounds

    @property
    def content_rect(self) -> Optional[ContentRect]:
        """Crop offsets inside the client frame."""
        return self._content_rect

    @property
    def is_minimized(self) -> bool:
        """True when the tracked game window is minimized."""
        if self._tracker is None:
            return False
        return self._tracker.is_minimized

    @property
    def frame_size(self) -> Optional[tuple[int, int]]:
        if self._content_bounds is not None:
            return self._content_bounds.width, self._content_bounds.height
        if self._bounds is None:
            return None
        return self._bounds.width, self._bounds.height

    def _init_capture(self) -> None:
        """Initialize the best available capture method."""
        if self._window_mode:
            if not MSS_AVAILABLE:
                raise RuntimeError(
                    "Window capture requires mss (install with: pip install mss)"
                )
            self._mss = mss.mss()
            get_logger("capture").info(
                "mss window capture process=%r title=%r content_aspect=%s:%s",
                self.window_process,
                self.window_title,
                self.content_aspect[0],
                self.content_aspect[1],
            )
            return

        if DXCAM_AVAILABLE:
            try:
                self._camera = dxcam.create(output_idx=0, output_color="BGR")
                if self.region:
                    self._camera.start(region=(
                        self.region.get("left", 0),
                        self.region.get("top", 0),
                        self.region.get("left", 0) + self.region.get("width", 1920),
                        self.region.get("top", 0) + self.region.get("height", 1080),
                    ), target_fps=self.fps)
                else:
                    self._camera.start(target_fps=self.fps)
                get_logger("capture").info("using dxcam")
                return
            except Exception as e:
                get_logger("capture").warning("dxcam failed: %s", e)

        if MSS_AVAILABLE:
            self._mss = mss.mss()
            if self.region:
                self._monitor = {
                    "left": self.region.get("left", 0),
                    "top": self.region.get("top", 0),
                    "width": self.region.get("width", 1920),
                    "height": self.region.get("height", 1080),
                }
            else:
                self._monitor = self._mss.monitors[1]  # Primary monitor
            get_logger("capture").info("using mss")
            return

        raise RuntimeError("No screen capture backend available (need dxcam or mss)")

    def _refresh_window_region(self) -> bool:
        """Update monitor dict from the live game window."""
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
        """Crop to content aspect and refresh content_bounds for click mapping."""
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
            # Full-monitor / region capture: treat frame origin as (0,0) desktop
            # only if no window bounds — still expose content size for mapping.
            self._content_bounds = WindowBounds(
                left=rect.left,
                top=rect.top,
                width=rect.width,
                height=rect.height,
            )
        return cropped

    def _grab_mss(self) -> Optional[np.ndarray]:
        """Grab via mss; BitBlt/GDI failures return None (same as a missed frame)."""
        if self._mss is None or self._monitor is None:
            return None
        try:
            screenshot = self._mss.grab(self._monitor)
        except Exception as exc:
            # mss raises ScreenShotError on intermittent BitBlt failures.
            get_logger("capture").debug("mss grab failed: %s", exc)
            return None
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def get_frame(self) -> Optional[np.ndarray]:
        """Get the latest frame as BGR numpy array (content-aspect cropped)."""
        if self._window_mode:
            if self.is_minimized:
                return None
            if not self._refresh_window_region() or self._monitor is None:
                return None
            frame = self._grab_mss()
            if frame is None:
                return None
            return self._apply_content_crop(frame)

        if self._camera:
            frame = self._camera.get_latest_frame()
            if frame is not None:
                h, w = frame.shape[:2]
                self._bounds = WindowBounds(left=0, top=0, width=w, height=h)
                return self._apply_content_crop(frame)
            return None

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
        """Stop capture."""
        if self._camera:
            self._camera.stop()
            self._camera = None
        if self._mss:
            self._mss.close()
            self._mss = None


def _parse_content_aspect(value) -> Tuple[int, int]:
    if value is None:
        return DEFAULT_ASPECT
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, str) and ":" in value:
        a, b = value.split(":", 1)
        return int(a), int(b)
    return DEFAULT_ASPECT


def create_capture_from_config(config: dict) -> ScreenCapture:
    """Create ScreenCapture from config.yaml capture section."""
    capture_config = config.get("capture", {})
    return ScreenCapture(
        window_title=capture_config.get("window_title"),
        window_process=capture_config.get("window_process"),
        region=capture_config.get("region"),
        fps=capture_config.get("fps", 30),
        content_aspect=_parse_content_aspect(
            capture_config.get("content_aspect")
        ),
    )
