"""Crop captured frames to the real 4:3 game canvas.

The game canvas aspect is 4:3 at **any** window size. Absolute resolutions
(e.g. 1345x1010 windowed, 1920x1080 fullscreen) are examples only — crop
math always uses the live frame width/height.

Fullscreen on wide monitors adds left/right black bars. Windowed 4:3 clients
usually need no crop. Coordinates for vision/clicks are relative to the
cropped content, not the full client including pillarbox.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

# Default game content aspect (width : height).
DEFAULT_ASPECT = (4, 3)

# Treat ratios within this relative error as already matching the aspect.
ASPECT_EPSILON = 0.01


@dataclass(frozen=True)
class ContentRect:
    """Crop rectangle in client-local pixel coordinates."""

    left: int
    top: int
    width: int
    height: int

    @property
    def valid(self) -> bool:
        return self.width > 0 and self.height > 0


def compute_aspect_crop(
    width: int,
    height: int,
    aspect: Tuple[int, int] = DEFAULT_ASPECT,
) -> ContentRect:
    """Largest centered crop of ``aspect`` inside ``width`` x ``height``.

    - Wider than aspect (pillarbox): keep full height, crop width.
    - Taller than aspect (letterbox): keep full width, crop height.
    - Already matching: identity crop.
    """
    if width <= 0 or height <= 0:
        return ContentRect(0, 0, max(0, width), max(0, height))

    target_w, target_h = aspect
    target_ratio = target_w / target_h
    frame_ratio = width / height

    if abs(frame_ratio - target_ratio) <= ASPECT_EPSILON * target_ratio:
        return ContentRect(0, 0, width, height)

    if frame_ratio > target_ratio:
        # Too wide: pillarbox left/right.
        crop_w = int(round(height * target_ratio))
        crop_w = min(crop_w, width)
        left = (width - crop_w) // 2
        return ContentRect(left, 0, crop_w, height)

    # Too tall: letterbox top/bottom.
    crop_h = int(round(width / target_ratio))
    crop_h = min(crop_h, height)
    top = (height - crop_h) // 2
    return ContentRect(0, top, width, crop_h)


def compute_43_crop(width: int, height: int) -> ContentRect:
    """Convenience: centered 4:3 crop."""
    return compute_aspect_crop(width, height, DEFAULT_ASPECT)


def crop_frame(
    frame: np.ndarray,
    aspect: Tuple[int, int] = DEFAULT_ASPECT,
) -> tuple[np.ndarray, ContentRect]:
    """Crop a BGR frame to the centered aspect rect; return crop + rect."""
    height, width = frame.shape[:2]
    rect = compute_aspect_crop(width, height, aspect)
    if rect.left == 0 and rect.top == 0 and rect.width == width and rect.height == height:
        return frame, rect
    cropped = frame[
        rect.top : rect.top + rect.height,
        rect.left : rect.left + rect.width,
    ]
    return cropped, rect
