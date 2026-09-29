"""Game-login dialog geometry vs the legacy 816x639 window-ratio path."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import numpy as np

BOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "autologin",
    "bot",
)
if BOT not in sys.path:
    sys.path.insert(0, BOT)

from game_geom import (  # noqa: E402
    GEOM_AUTO,
    GEOM_DIALOG,
    GEOM_WINDOW,
    Box,
    Chrome,
    ClientOrigin,
    centered_43_box,
    chrome_from_rects,
    content_aabb_from_grab,
    dialog_ratio_pt,
    dialog_ratio_to_screen,
    normalize_geom_mode,
    outer_ratio_to_dialog_frac,
    resolve_dialog_box,
    window_ratio_to_screen,
)
from gameflow import (  # noqa: E402
    R_AGREE_BTN,
    R_CHAR_SLOTS,
    R_LOGIN_OK,
    R_PAGE2_BTN,
    GameFlow,
)

# last_click.png measurements: outer 816x639 grab.
KEYS = {
    "agree": R_AGREE_BTN,
    "page2": R_PAGE2_BTN,
    "char1": R_CHAR_SLOTS[0],
    "ok": R_LOGIN_OK,
}


def _window_pt(rx, ry, left, top, w, h):
    return (int(left + rx * w), int(top + ry * h))


def test_normalize_geom_mode():
    assert normalize_geom_mode("AUTO") == GEOM_AUTO
    assert normalize_geom_mode("window") == GEOM_WINDOW
    assert normalize_geom_mode("dialog") == GEOM_DIALOG
    assert normalize_geom_mode("nope") == GEOM_AUTO


def test_window_ratio_matches_legacy_816x639():
    left, top, w, h = 40, 80, 816, 639
    for rx, ry in KEYS.values():
        assert window_ratio_to_screen(rx, ry, left, top, w, h) == _window_pt(
            rx, ry, left, top, w, h
        )


def test_familiar_dialog_close_to_window_path():
    """800x600 client inside 816x639: dialog mapper stays on the same buttons."""
    chrome = Chrome(8, 31, 8, 8)
    origin = ClientOrigin(48, 111, 800, 600)  # 40+8, 80+31
    box = Box(0, 0, 800, 600)
    left, top, w, h = 40, 80, 816, 639
    for name, (rx, ry) in KEYS.items():
        old = window_ratio_to_screen(rx, ry, left, top, w, h)
        new = dialog_ratio_to_screen(rx, ry, origin, box, chrome)
        assert abs(old[0] - new[0]) <= 2, (name, old, new)
        assert abs(old[1] - new[1]) <= 2, (name, old, new)


def test_outer_ratio_to_dialog_frac_login_ok():
    fx, fy = outer_ratio_to_dialog_frac(*R_LOGIN_OK)
    assert 0.70 < fx < 0.90
    assert 0.70 < fy < 0.85


def _wide_points(client_w, client_h, outer_w, outer_h, left=20, top=30):
    chrome = chrome_from_rects(
        left,
        top,
        outer_w,
        outer_h,
        ClientOrigin(left + 8, top + 31, client_w, client_h),
    )
    origin = ClientOrigin(left + 8, top + 31, client_w, client_h)
    box = resolve_dialog_box(client_w=client_w, client_h=client_h)
    pts = {
        name: dialog_ratio_to_screen(rx, ry, origin, box, chrome)
        for name, (rx, ry) in KEYS.items()
    }
    naive = {
        name: window_ratio_to_screen(rx, ry, left, top, outer_w, outer_h)
        for name, (rx, ry) in KEYS.items()
    }
    return pts, naive, box, origin


def test_dialog_points_inside_43_box_at_1280x720_and_1920x1080():
    for cw, ch, ow, oh in ((1280, 720, 1296, 759), (1920, 1080, 1936, 1119)):
        pts, naive, box, origin = _wide_points(cw, ch, ow, oh)
        assert box.w / box.h == 800 / 600 or abs(box.w / box.h - 4 / 3) < 0.02
        assert box.w < cw or box.h < ch
        for name, (sx, sy) in pts.items():
            cx = sx - origin.sx
            cy = sy - origin.sy
            assert box.x <= cx <= box.right, (cw, name, cx, box)
            assert box.y <= cy <= box.bottom, (cw, name, cy, box)
            # Naive outer-window ratio is a different pixel — that is the bug.
            assert naive[name] != (sx, sy), (cw, name, naive[name], (sx, sy))


def test_centered_43_and_content_aabb():
    box = centered_43_box(1920, 1080)
    assert box.w == 1440 and box.h == 1080
    assert box.x == 240 and box.y == 0
    img = np.zeros((759, 1296, 3), dtype=np.uint8)
    img[31:31 + 720, 8:8 + 960] = 80
    aabb = content_aabb_from_grab(img, Chrome(8, 31, 8, 8), dark=14)
    assert aabb is not None
    assert aabb.w >= 900 and aabb.h >= 650


def test_dialog_ratio_pt_falls_back_without_hwnd():
    sx, sy = dialog_ratio_pt(0.5, 0.5, outer_left=10, outer_top=20, outer_w=816, outer_h=639)
    assert (sx, sy) == window_ratio_to_screen(0.5, 0.5, 10, 20, 816, 639)


def _fake_flow(geom: str, left: int, top: int, width: int, height: int):
    game = SimpleNamespace(
        hwnd=0,
        rect=SimpleNamespace(
            left=left, top=top, width=width, height=height,
            right=left + width, bottom=top + height,
        ),
    )
    flow = object.__new__(GameFlow)
    flow.bot = SimpleNamespace(cfg={"game_click_geom": geom}, game=game)
    flow._last_img = None
    flow._last_anchor = None
    return flow


def test_gameflow_ratio_pt_keeps_window_path_when_familiar():
    flow = _fake_flow("auto", 10, 20, 816, 639)
    got = GameFlow._ratio_pt(flow, *R_LOGIN_OK)
    assert got == window_ratio_to_screen(*R_LOGIN_OK, 10, 20, 816, 639)


def test_gameflow_ratio_pt_respects_window_flag_on_wide_shell():
    flow = _fake_flow("window", 0, 0, 1936, 1119)
    got = GameFlow._ratio_pt(flow, *R_LOGIN_OK)
    assert got == window_ratio_to_screen(*R_LOGIN_OK, 0, 0, 1936, 1119)
