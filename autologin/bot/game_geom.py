"""Game-login click geometry (additive).

Measured R_* ratios are fractions of the 816x639 outer-window grab
(800x600 client + chrome). At other sizes those ratios must be applied
to the live client / detected dialog box, not GetWindowRect.

This module does not change Purple login or the familiar 816x639 path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

import ctypes
import ctypes.wintypes as wt

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover - import-time optional for unit tests
    cv2 = None
    np = None

user32 = ctypes.WinDLL("user32", use_last_error=True)

REF_WIN_W = 816.0
REF_WIN_H = 639.0
REF_CLIENT_W = 800.0
REF_CLIENT_H = 600.0
# Typical Win32 frame for an 800x600 client inside 816x639.
REF_CHROME_L = 8.0
REF_CHROME_T = 31.0
REF_CHROME_R = 8.0
REF_CHROME_B = 8.0

GEOM_AUTO = "auto"
GEOM_WINDOW = "window"
GEOM_DIALOG = "dialog"
GEOM_MODES = (GEOM_AUTO, GEOM_WINDOW, GEOM_DIALOG)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass(frozen=True)
class ClientOrigin:
    """Live client (0,0) in screen pixels plus client size."""
    sx: int
    sy: int
    width: int
    height: int


@dataclass(frozen=True)
class Chrome:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class Box:
    """Rectangle in client pixels."""
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h


def normalize_geom_mode(raw: Any, default: str = GEOM_AUTO) -> str:
    text = str(raw or default).strip().lower()
    if text in GEOM_MODES:
        return text
    return default


def client_origin_screen(hwnd: int) -> Optional[ClientOrigin]:
    """True client origin via Win32 ClientToScreen + GetClientRect."""
    if not hwnd:
        return None
    rc = wt.RECT()
    if not user32.GetClientRect(int(hwnd), ctypes.byref(rc)):
        return None
    width = int(rc.right - rc.left)
    height = int(rc.bottom - rc.top)
    if width <= 0 or height <= 0:
        return None
    pt = _POINT(0, 0)
    if not user32.ClientToScreen(int(hwnd), ctypes.byref(pt)):
        return None
    return ClientOrigin(int(pt.x), int(pt.y), width, height)


def chrome_from_rects(
    outer_left: float,
    outer_top: float,
    outer_w: float,
    outer_h: float,
    origin: Optional[ClientOrigin],
) -> Chrome:
    """Fixed-pixel window chrome. Falls back to the 816x639 reference."""
    if origin is None or origin.width <= 0 or origin.height <= 0:
        return Chrome(REF_CHROME_L, REF_CHROME_T, REF_CHROME_R, REF_CHROME_B)
    left = float(origin.sx) - float(outer_left)
    top = float(origin.sy) - float(outer_top)
    right = float(outer_w) - left - float(origin.width)
    bottom = float(outer_h) - top - float(origin.height)
    if left < -2 or top < -2 or right < -2 or bottom < -2:
        return Chrome(REF_CHROME_L, REF_CHROME_T, REF_CHROME_R, REF_CHROME_B)
    return Chrome(max(0.0, left), max(0.0, top), max(0.0, right), max(0.0, bottom))


def outer_ratio_to_dialog_frac(
    rx: float,
    ry: float,
    *,
    ref_win_w: float = REF_WIN_W,
    ref_win_h: float = REF_WIN_H,
    chrome: Optional[Chrome] = None,
) -> Tuple[float, float]:
    """Map an 816x639 outer-window ratio onto the 800x600 client/dialog."""
    ch = chrome or Chrome(REF_CHROME_L, REF_CHROME_T, REF_CHROME_R, REF_CHROME_B)
    px = float(rx) * float(ref_win_w)
    py = float(ry) * float(ref_win_h)
    cw = max(1.0, float(ref_win_w) - ch.left - ch.right)
    chh = max(1.0, float(ref_win_h) - ch.top - ch.bottom)
    fx = (px - ch.left) / cw
    fy = (py - ch.top) / chh
    return fx, fy


def window_ratio_to_screen(
    rx: float,
    ry: float,
    left: float,
    top: float,
    width: float,
    height: float,
) -> Tuple[int, int]:
    """Legacy GetWindowRect mapping (816x639 path)."""
    return (int(left + float(rx) * float(width)),
            int(top + float(ry) * float(height)))


def centered_43_box(client_w: int, client_h: int) -> Box:
    """Largest 4:3 box centered in the client (800x600 aspect)."""
    cw = max(1, int(client_w))
    ch = max(1, int(client_h))
    target = REF_CLIENT_W / REF_CLIENT_H
    if cw / float(ch) >= target:
        h = ch
        w = max(1, int(round(h * target)))
    else:
        w = cw
        h = max(1, int(round(w / target)))
    return Box((cw - w) // 2, (ch - h) // 2, w, h)


def content_aabb_from_grab(
    img,
    chrome: Optional[Chrome] = None,
    dark: int = 14,
) -> Optional[Box]:
    """Non-letterbox content AABB of a window grab, in client pixels."""
    if img is None or np is None:
        return None
    try:
        arr = np.asarray(img)
    except Exception:
        return None
    if arr.ndim < 2 or arr.size == 0:
        return None
    gray = arr
    if arr.ndim == 3:
        if cv2 is not None:
            gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        else:
            gray = arr.mean(axis=2)
    mask = gray > int(dark)
    if hasattr(mask, "any") and not mask.any():
        return None
    ys, xs = np.where(mask)
    if xs.size < 80 or ys.size < 80:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    ch = chrome or Chrome(0, 0, 0, 0)
    cx0 = int(round(x0 - ch.left))
    cy0 = int(round(y0 - ch.top))
    cx1 = int(round(x1 - ch.left))
    cy1 = int(round(y1 - ch.top))
    w = cx1 - cx0
    h = cy1 - cy0
    if w < 200 or h < 160:
        return None
    return Box(cx0, cy0, w, h)


def dialog_from_anchor(
    match: Optional[dict],
    img_w: int,
    img_h: int,
    chrome: Optional[Chrome] = None,
    client_w: int = 0,
    client_h: int = 0,
) -> Optional[Box]:
    """Restore a dialog box from an anchor match + matched scale."""
    if not match:
        return None
    try:
        scale = float(match.get("scale") or 0)
    except (TypeError, ValueError):
        return None
    if scale <= 0.05:
        return None
    dw = REF_WIN_W * scale
    dh = REF_WIN_H * scale
    if dw < 200 or dh < 160:
        return None
    # Stretched UI: match scale tracks the grab; use the full client.
    if dw >= img_w * 0.90 and dh >= img_h * 0.90:
        if client_w > 0 and client_h > 0:
            return Box(0, 0, int(client_w), int(client_h))
        return None
    ix = (float(img_w) - dw) / 2.0
    iy = (float(img_h) - dh) / 2.0
    mx = match.get("x")
    my = match.get("y")
    if mx is not None and my is not None:
        # Keep the title inside the estimated dialog when possible.
        try:
            ix = min(max(0.0, float(mx) - dw * 0.12), max(0.0, img_w - dw))
            iy = min(max(0.0, float(my) - dh * 0.08), max(0.0, img_h - dh))
        except (TypeError, ValueError):
            pass
    ch = chrome or Chrome(0, 0, 0, 0)
    return Box(
        int(round(ix - ch.left)),
        int(round(iy - ch.top)),
        max(1, int(round(dw))),
        max(1, int(round(dh))),
    )


def clamp_box_to_client(box: Box, client_w: int, client_h: int) -> Box:
    cw = max(1, int(client_w))
    ch = max(1, int(client_h))
    x = max(0, min(box.x, cw - 1))
    y = max(0, min(box.y, ch - 1))
    w = max(1, min(box.w, cw - x))
    h = max(1, min(box.h, ch - y))
    return Box(x, y, w, h)


def resolve_dialog_box(
    *,
    client_w: int,
    client_h: int,
    img=None,
    chrome: Optional[Chrome] = None,
    anchor_match: Optional[dict] = None,
) -> Box:
    """Dialog box in client pixels: anchor, then content AABB, then 4:3."""
    cw, ch = max(1, int(client_w)), max(1, int(client_h))
    img_w = img_h = 0
    if img is not None:
        try:
            img_h, img_w = int(img.shape[0]), int(img.shape[1])
        except Exception:
            img_w = img_h = 0
    if anchor_match is not None and img_w > 0 and img_h > 0:
        found = dialog_from_anchor(
            anchor_match, img_w, img_h, chrome, cw, ch,
        )
        if found is not None and found.w >= 200 and found.h >= 160:
            return clamp_box_to_client(found, cw, ch)
    aabb = content_aabb_from_grab(img, chrome)
    if aabb is not None and aabb.w >= 200 and aabb.h >= 160:
        return clamp_box_to_client(aabb, cw, ch)
    if cw >= 900 or ch >= 700 or abs(cw / float(ch) - REF_CLIENT_W / REF_CLIENT_H) > 0.08:
        return clamp_box_to_client(centered_43_box(cw, ch), cw, ch)
    return Box(0, 0, cw, ch)


def dialog_ratio_to_screen(
    rx: float,
    ry: float,
    origin: ClientOrigin,
    box: Box,
    chrome: Optional[Chrome] = None,
) -> Tuple[int, int]:
    """Apply a measured outer-window ratio inside the live dialog box."""
    fx, fy = outer_ratio_to_dialog_frac(rx, ry, chrome=chrome)
    sx = origin.sx + box.x + fx * box.w
    sy = origin.sy + box.y + fy * box.h
    return int(round(sx)), int(round(sy))


def dialog_ratio_pt(
    rx: float,
    ry: float,
    *,
    hwnd: int = 0,
    outer_left: float = 0,
    outer_top: float = 0,
    outer_w: float = 0,
    outer_h: float = 0,
    img=None,
    anchor_match: Optional[dict] = None,
    origin: Optional[ClientOrigin] = None,
) -> Tuple[int, int]:
    """Screen point for a game-login ratio using dialog/client geometry."""
    live = origin or (client_origin_screen(hwnd) if hwnd else None)
    if live is None:
        if outer_w > 0 and outer_h > 0:
            return window_ratio_to_screen(
                rx, ry, outer_left, outer_top, outer_w, outer_h,
            )
        return (0, 0)
    chrome = chrome_from_rects(outer_left, outer_top, outer_w, outer_h, live)
    box = resolve_dialog_box(
        client_w=live.width,
        client_h=live.height,
        img=img,
        chrome=chrome,
        anchor_match=anchor_match,
    )
    return dialog_ratio_to_screen(rx, ry, live, box, chrome)
