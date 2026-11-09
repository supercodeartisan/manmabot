"""One ground-drop step per tick. The practice loop is not pasted in.

A missing inventory grid, or a bag row without a slot, does not click.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from app._05_action.uidialog_gate import LABEL_INVENTORY, is_open

_ARROW_IDS = frozenset({7, 96})
_ARROW_NAMES = frozenset(
    {
        "화살",
        "箭",
        "arrow",
        "arrows",
        "은 화살",
        "銀箭",
        "银箭",
        "silver arrow",
        "silver arrows",
    }
)
# Neighbor tiles, same order as the supply practice (left, right, down).
_DROP_TILES = ((-1, -1), (1, 1), (-1, 1))
_ROWS = 8
_COLS = 4


def grid_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "supply" / "inventory_grid.json"


def step_ground_drop(
    state: Any,
    blackboard: Any,
    qty: int,
) -> Optional[dict[str, Any]]:
    """Advance one drop step.

    Returns a tile dict when the drag has been sent, ``{"blocked": True}``
    when it cannot click, or None while still working.
    """
    bag = _arrow_stack(state)
    if bag is None or int(getattr(bag, "slot", -1)) < 0:
        return {"blocked": True, "reason": "no arrow slot"}
    if not grid_path().is_file():
        return {"blocked": True, "reason": "inventory grid missing"}

    scratch = blackboard.scratch.setdefault("party_supply_drop", {})
    stage = str(scratch.get("stage") or "open")
    if stage == "open":
        snap = getattr(state, "last_uidialog", None)
        if not is_open(snap, (LABEL_INVENTORY,)):
            _press_inventory()
            return None
        scratch["stage"] = "scroll"
        scratch["ri"] = 0
        scratch["list_index"] = int(bag.slot) + 1
        return None
    if stage == "scroll":
        if _scroll_one(scratch):
            return None
        scratch["stage"] = "drag"
        return None
    if stage == "drag":
        tile = _drag_once(state, blackboard, scratch)
        blackboard.scratch.pop("party_supply_drop", None)
        if tile is None:
            return {"blocked": True, "reason": "drag failed"}
        tile["qty"] = max(1, int(qty))
        if int(getattr(bag, "quantity", 1) or 1) > 1:
            _type_qty(int(qty))
        return tile
    blackboard.scratch.pop("party_supply_drop", None)
    return {"blocked": True, "reason": "drop stage"}


def _arrow_stack(state: Any) -> Any:
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None)
    best = None
    for item in getattr(inv, "items", None) or []:
        if int(getattr(item, "slot", -1)) < 0:
            continue
        if not _is_arrow(item):
            continue
        if best is None or int(getattr(item, "quantity", 0) or 0) > int(
            getattr(best, "quantity", 0) or 0
        ):
            best = item
    return best


def _is_arrow(item: Any) -> bool:
    try:
        if int(getattr(item, "item_id", 0) or 0) in _ARROW_IDS:
            return True
    except (TypeError, ValueError):
        pass
    for attr in ("name", "name_en", "name_tw", "name_cn"):
        if str(getattr(item, attr, "") or "").strip().lower() in _ARROW_NAMES:
            return True
    return False


def _press_inventory() -> None:
    from app._05_action.keyboard import KeyboardController

    keys = KeyboardController()
    mod = "ctrlleft"
    try:
        keys.hold(mod)
    except Exception:
        mod = "ctrl"
        keys.hold(mod)
    time.sleep(0.04)
    try:
        keys.press("i", duration=0.05)
    finally:
        keys.release(mod)


def _scroll_one(scratch: dict[str, Any]) -> bool:
    """One scrollbar click when the stack row is outside the 8-row window."""
    list_index = int(scratch.get("list_index") or 1)
    ri = int(scratch.get("ri") or 0)
    raw_num = (list_index - 1) // _COLS + 1
    delta = raw_num - ri
    if 1 <= delta <= _ROWS:
        return False
    grid = _live_grid()
    if grid is None:
        return False
    if delta <= 0:
        _click_screen(grid["scroll_up"])
        scratch["ri"] = ri - 1
    else:
        _click_screen(grid["scroll_down"])
        scratch["ri"] = ri + 1
    time.sleep(0.15)
    return True


def _drag_once(state: Any, blackboard: Any, scratch: dict[str, Any]) -> Optional[dict[str, Any]]:
    grid = _live_grid()
    origin = getattr(blackboard, "world_origin", None)
    if grid is None or origin is None:
        return None
    list_index = int(scratch.get("list_index") or 1)
    ri = int(scratch.get("ri") or 0)
    raw_num = (list_index - 1) // _COLS + 1
    col_num = (list_index - 1) % _COLS + 1
    row_on = raw_num - ri
    if not 1 <= row_on <= _ROWS:
        return None
    idx = (row_on - 1) * _COLS + (col_num - 1)
    slots = grid["slots"]
    if idx < 0 or idx >= len(slots):
        return None
    dx, dy = _DROP_TILES[0]
    try:
        _shift_drag(slots[idx], grid["drops"][0])
    except Exception:
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    return {
        "map_id": None if pose is None else int(pose.map_id),
        "x": int(origin.x) + dx,
        "y": int(origin.y) + dy,
    }


def _live_grid() -> Optional[dict[str, Any]]:
    import json

    from app._05_action.content_crop import compute_43_crop
    from app._05_action.window_bounds import find_game_window, get_client_bounds

    path = grid_path()
    if not path.is_file():
        return None
    hwnd = find_game_window("LC.exe")
    bounds = get_client_bounds(int(hwnd)) if hwnd else None
    if bounds is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ref_w = int(data.get("image_width") or 0)
    ref_h = int(data.get("image_height") or 0)
    raw_slots = data.get("slots") or []
    if ref_w <= 0 or ref_h <= 0 or len(raw_slots) != _ROWS * _COLS:
        return None
    ref = compute_43_crop(ref_w, ref_h)
    live = compute_43_crop(int(bounds.width), int(bounds.height))

    def _xy(x: float, y: float) -> tuple[int, int]:
        u = (float(x) - ref.left) / ref.width
        v = (float(y) - ref.top) / ref.height
        return (
            int(bounds.left + round(live.left + u * live.width)),
            int(bounds.top + round(live.top + v * live.height)),
        )

    by_row: dict[int, list] = {}
    for row in raw_slots:
        by_row.setdefault(int(row["row"]), []).append(row)
    slots: list[tuple[int, int]] = []
    for r in range(1, _ROWS + 1):
        cells = sorted(by_row.get(r, []), key=lambda s: int(s["x"]))
        if len(cells) != _COLS:
            return None
        for cell in cells:
            slots.append(_xy(int(cell["x"]), int(cell["y"])))
    up = data.get("scroll_up_position") or [0, 0]
    down = data.get("scroll_down_position") or [0, 0]
    return {
        "slots": slots,
        "scroll_up": _xy(int(up[0]), int(up[1])),
        "scroll_down": _xy(int(down[0]), int(down[1])),
        "drops": [_drop_screen(bounds.width, bounds.height, bounds.left, bounds.top, dx, dy) for dx, dy in _DROP_TILES],
    }


def _drop_screen(width: int, height: int, left: int, top: int, dx: int, dy: int) -> tuple[int, int]:
    ref_h = 600.0
    scale = float(height) / ref_h
    if scale < 0.2 or scale > 4.0:
        scale = 1.0
    pxp = 0.53 * scale
    sx = float(width) * 0.5 + 1.8 * scale
    sy = float(height) * 0.5 - 63.0 * scale
    du = 48.0 * (int(dx) + int(dy))
    dv = 24.0 * (int(dx) - int(dy))
    return int(left + round(sx + du * pxp)), int(top + round(sy - dv * pxp))


def _click_screen(xy: tuple[int, int]) -> None:
    from app._05_action.mouse import MouseController

    MouseController().click(float(xy[0]), float(xy[1]), snap=True)


def _shift_drag(src: tuple[int, int], dst: tuple[int, int]) -> None:
    from app._05_action import mouse as mouse_mod
    from app._05_action.keyboard import KeyboardController
    from app._05_action.mouse import MouseController

    mouse = MouseController()
    keys = KeyboardController()
    mouse.click(float(src[0]), float(src[1]), snap=True)
    time.sleep(0.08)
    shift_key = "shiftleft"
    try:
        keys.hold(shift_key)
    except Exception:
        shift_key = "shift"
        keys.hold(shift_key)
    time.sleep(0.05)
    try:
        mouse.move(float(src[0]), float(src[1]), snap=True)
        time.sleep(0.04)
        mouse_mod._send_button("left", down=True, px=int(src[0]), py=int(src[1]))
        time.sleep(0.05)
        mouse.move(float(dst[0]), float(dst[1]), snap=False)
        time.sleep(0.55)
    finally:
        mouse_mod._send_button("left", down=False, px=int(dst[0]), py=int(dst[1]))
        keys.release(shift_key)


def _type_qty(qty: int) -> None:
    from app._05_action.keyboard import KeyboardController

    keys = KeyboardController()
    for ch in str(max(1, int(qty))):
        keys.press(ch, duration=0.04)
        time.sleep(0.05)
    keys.press("enter", duration=0.06)
