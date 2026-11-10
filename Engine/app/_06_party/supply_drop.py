"""Ground drop for the party shopkeeper.

The shop, the walk, the item id, the give count, and the drop-tile formula
stay as they are. What changes is the gesture beside the leader: each step
has to be seen before the next one runs, the same way Tool_Supply_Practice
does. A calculated tile is not a completed drop.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Optional

from app._05_action.uidialog_gate import LABEL_INVENTORY, is_open, read_uidialog_snap, wait_uidialog_open

# Neighbor tiles, same order as the supply practice (left, right, down).
_DROP_TILES = ((-1, -1), (1, 1), (-1, 1))
_ROWS = 8
_COLS = 4
# Practice tool: inventory open 3s, qty popup 3s, AmountSelector 1s, bag poll 2s.
_OPEN_TIMEOUT_S = 3.0
_QTY_TIMEOUT_S = 3.0
_AMOUNT_TIMEOUT_S = 1.0
_BAG_TIMEOUT_S = 2.0
_MAX_FAILS = 2
_HOLD_S = 20.0
_MAX_SCROLL = 8


def grid_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "data" / "supply" / "inventory_grid.json"


def inventory_protected(blackboard: Any) -> bool:
    """True only while this drop gesture still owns the inventory window."""
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return False
    job = scratch.get("party_supply_drop")
    return isinstance(job, dict) and bool(job.get("active"))


def dismiss_allowed_labels(blackboard: Any) -> tuple[str, ...]:
    """Inventory is spared from Esc only during an active party supply drop."""
    if inventory_protected(blackboard):
        return (LABEL_INVENTORY,)
    return ()


def confirm_live_slot(
    rows: list[dict[str, Any]],
    *,
    item_id: int,
    memory_slot: int,
) -> Optional[tuple[int, int, int]]:
    """Fresh bag row for the already chosen id, at the same memory slot.

    Returns ``(list_index, stack_count, total_qty)`` when that slot still
    holds the id. A different slot is not dragged.
    """
    matched: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        try:
            rid = int(row.get("id") or 0)
            slot = int(row.get("slot"))
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if rid != int(item_id):
            continue
        total += count
        if slot == int(memory_slot):
            matched.append(row)
    if len(matched) != 1 or total <= 0:
        return None
    count = int(matched[0].get("count") or 0)
    if count <= 0:
        return None
    return int(memory_slot) + 1, count, total


def step_ground_drop(
    state: Any,
    blackboard: Any,
    qty: int,
    kind: str = "arrow",
) -> Optional[dict[str, Any]]:
    """Open, confirm the slot, drag, then accept the drop only if the bag shrinks.

    Returns a tile dict with ``ok`` when the bag lost the requested count.
    ``blocked`` means this attempt did not drop; the caller must not publish
    a supply notice or resume follow. None is unused; the gesture finishes
    inside this call so Esc cannot land between the key and the drag.
    """
    kind_name = str(kind or "arrow")
    want = max(1, int(qty))
    scratch = blackboard.scratch.setdefault("party_supply_drop", {})
    if str(scratch.get("item") or "") != kind_name:
        scratch.clear()
        scratch["item"] = kind_name
    now = time.time()
    hold_until = float(scratch.get("hold_until") or 0.0)
    if hold_until > now:
        scratch["active"] = False
        return {
            "blocked": True,
            "reason": str(scratch.get("last_fail") or "drop confirm failed"),
        }

    bag = _kind_stack(state, kind_name)
    if bag is None or int(getattr(bag, "slot", -1)) < 0 or not grid_path().is_file():
        return _fail(scratch, "slot check failed")
    try:
        item_id = int(getattr(bag, "item_id", 0) or 0)
        memory_slot = int(bag.slot)
    except (TypeError, ValueError):
        return _fail(scratch, "slot check failed")
    if item_id <= 0:
        return _fail(scratch, "slot check failed")

    scratch["active"] = True
    if not _ensure_inventory():
        return _fail(scratch, "inventory open failed")

    live = _live_slot(item_id, memory_slot)
    if live is None:
        return _fail(scratch, "slot check failed")
    list_index, stack_count, total_qty = live
    if stack_count < want or total_qty < want:
        return _fail(scratch, "slot check failed")

    base_id = scratch.get("baseline_id")
    base_qty = scratch.get("baseline_qty")
    if base_id != item_id or base_qty is None:
        scratch["baseline_id"] = item_id
        scratch["baseline_qty"] = int(total_qty)
        base_qty = int(total_qty)
    elif int(base_qty) - int(total_qty) >= want:
        return _accept(state, blackboard, scratch, want, kind_name)

    if not _inventory_is_open():
        return _fail(scratch, "inventory open failed")
    scratch["ri"] = int(scratch.get("ri") or 0)
    scratch["list_index"] = int(list_index)
    if not _scroll_until_visible(scratch):
        return _fail(scratch, "slot check failed")
    if not _inventory_is_open():
        return _fail(scratch, "inventory open failed")

    again = _live_slot(item_id, memory_slot)
    if again is None:
        return _fail(scratch, "slot check failed")
    list_index, stack_count, total_qty = again
    if stack_count < want:
        return _fail(scratch, "slot check failed")
    scratch["list_index"] = int(list_index)

    before = _total_qty(item_id)
    if before is None or before < want:
        return _fail(scratch, "slot check failed")

    tile = _drag_once(state, blackboard, scratch)
    if tile is None:
        return _fail(scratch, "drag failed")

    if stack_count > 1:
        if _wait_qty_dialog() is None:
            _tap_esc()
            return _fail(scratch, "qty prompt failed")
        _type_qty(want)

    after = _await_bag_drop(item_id, before, want)
    if after is None:
        return _fail(scratch, "drop confirm failed")
    return _accept(state, blackboard, scratch, want, kind_name, tile=tile)


def _fail(scratch: dict[str, Any], reason: str) -> dict[str, Any]:
    fails = scratch.get("fails")
    if not isinstance(fails, dict):
        fails = {}
        scratch["fails"] = fails
    fails[reason] = int(fails.get(reason) or 0) + 1
    scratch["last_fail"] = reason
    if int(fails[reason]) >= _MAX_FAILS:
        scratch["hold_until"] = time.time() + _HOLD_S
        scratch["active"] = False
    return {"blocked": True, "reason": reason}


def _accept(
    state: Any,
    blackboard: Any,
    scratch: dict[str, Any],
    want: int,
    kind: str,
    tile: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if tile is None:
        tile = _tile_from_pose(state, blackboard)
    if tile is None:
        return _fail(scratch, "drop confirm failed")
    tile["qty"] = int(want)
    tile["ok"] = True
    tile["ground"] = _ground_seen(state, blackboard, tile, kind)
    blackboard.scratch.pop("party_supply_drop", None)
    return tile


def _tools_path() -> None:
    root = Path(__file__).resolve().parents[3]
    tools = str(root / "Tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)


def _inventory_is_open() -> bool:
    """Same Inventory label read the practice tool uses."""
    try:
        _tools_path()
        from supply.windows import inventory_open

        return bool(inventory_open())
    except Exception:
        return is_open(read_uidialog_snap(), (LABEL_INVENTORY,))


def _ensure_inventory() -> bool:
    """Ctrl+I, then wait until Inventory is actually open. Do not drag before that."""
    if _inventory_is_open():
        return True
    try:
        _tools_path()
        from supply.input_ops import focus_game

        focus_game()
    except Exception:
        pass
    _press_inventory()
    try:
        _tools_path()
        from supply.windows import wait_open

        return bool(
            wait_open(
                (LABEL_INVENTORY,),
                timeout_s=_OPEN_TIMEOUT_S,
                poll_s=0.1,
                force_scan=True,
            )
        )
    except Exception:
        return wait_uidialog_open(
            (LABEL_INVENTORY,),
            timeout_s=_OPEN_TIMEOUT_S,
            poll_s=0.1,
        )


def _bag_rows() -> Optional[list[dict[str, Any]]]:
    """Fresh inventory_listen rows, the practice tool's read_bag."""
    try:
        _tools_path()
        from supply.inventory import ordered_items, read_bag

        snap = read_bag()
    except Exception:
        return None
    if snap is None:
        return None
    return ordered_items(snap)


def _live_slot(item_id: int, memory_slot: int) -> Optional[tuple[int, int, int]]:
    rows = _bag_rows()
    if rows is None:
        return None
    return confirm_live_slot(rows, item_id=item_id, memory_slot=memory_slot)


def _total_qty(item_id: int) -> Optional[int]:
    rows = _bag_rows()
    if rows is None:
        return None
    total = 0
    seen = False
    for row in rows:
        try:
            if int(row.get("id") or 0) != int(item_id):
                continue
            total += int(row.get("count") or 0)
            seen = True
        except (TypeError, ValueError):
            continue
    if not seen:
        return 0
    return total


def _scroll_until_visible(scratch: dict[str, Any]) -> bool:
    for _ in range(_MAX_SCROLL):
        if not _inventory_is_open():
            return False
        if not _scroll_one(scratch):
            return True
    return False


def _wait_qty_dialog() -> Optional[str]:
    """Practice order: qty_prompt popup, then AmountSelector. None means do not type."""
    try:
        _tools_path()
        from supply.confirm_reader import wait_qty_prompt
        from supply.windows import LABEL_AMOUNT, wait_open
    except Exception:
        return None
    try:
        if wait_qty_prompt(timeout_s=_QTY_TIMEOUT_S, poll_s=0.1):
            return "qty_prompt"
    except Exception:
        return None
    try:
        if wait_open(
            (LABEL_AMOUNT,),
            timeout_s=_AMOUNT_TIMEOUT_S,
            poll_s=0.12,
            force_scan=True,
        ):
            return "amount"
    except Exception:
        return None
    return None


def _tap_esc() -> None:
    from app._05_action.keyboard import KeyboardController

    try:
        KeyboardController().press("esc", duration=0.05)
    except Exception:
        return
    time.sleep(0.2)


def _await_bag_drop(item_id: int, before: int, want: int) -> Optional[int]:
    """Poll the bag the way the practice tool does. None if the count never falls."""
    deadline = time.time() + _BAG_TIMEOUT_S
    while True:
        now = _total_qty(item_id)
        if now is None:
            return None
        if int(before) - int(now) >= int(want):
            return int(now)
        if time.time() >= deadline:
            return None
        time.sleep(0.1)


def _ground_seen(
    state: Any,
    blackboard: Any,
    tile: dict[str, Any],
    kind: str,
) -> Optional[bool]:
    """True when a matching pile is already on the drop tile. None if unseen."""
    origin = getattr(blackboard, "world_origin", None)
    if origin is None:
        return None
    try:
        tx = int(tile.get("x"))
        ty = int(tile.get("y"))
    except (TypeError, ValueError):
        return None
    try:
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision.combat_query import list_lootable, object_absolute_tile
        from app._06_party.arrow_policy import supply_pile_matches

        piles = list_lootable(
            state,
            loot_mode="all_items",
            farm=None,
            origin=origin,
            check_path=False,
            ownership_filter=False,
        )
    except Exception:
        return None
    for item in piles or []:
        try:
            if not supply_pile_matches(item, kind):
                continue
            pos = object_absolute_tile(item, origin)
        except Exception:
            continue
        if pos is None:
            continue
        if tile_chebyshev(int(pos[0]), int(pos[1]), tx, ty) <= 2:
            return True
    return False


def _tile_from_pose(state: Any, blackboard: Any) -> Optional[dict[str, Any]]:
    origin = getattr(blackboard, "world_origin", None)
    if origin is None:
        return None
    from app._04_decision.world_nav.session import live_pose_from_state

    pose = live_pose_from_state(state)
    dx, dy = _DROP_TILES[0]
    return {
        "map_id": None if pose is None else int(pose.map_id),
        "x": int(origin.x) + dx,
        "y": int(origin.y) + dy,
    }


def _kind_stack(state: Any, kind: str) -> Any:
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None)
    best = None
    for item in getattr(inv, "items", None) or []:
        if int(getattr(item, "slot", -1)) < 0:
            continue
        if not _is_kind(item, kind):
            continue
        if best is None or int(getattr(item, "quantity", 0) or 0) > int(
            getattr(best, "quantity", 0) or 0
        ):
            best = item
    return best


def _kind_tables(kind: str) -> tuple[frozenset[int], frozenset[str]]:
    from app._03_world.merge.memory_inventory import (
        DEPOISON_IDS,
        DEPOISON_NAMES,
        HP_POTION_IDS,
        HP_POTION_NAMES,
        MP_POTION_IDS,
        MP_POTION_NAMES,
        SILVER_ARROW_IDS,
        SILVER_ARROW_NAMES,
    )

    tables = {
        "hp": (HP_POTION_IDS, HP_POTION_NAMES),
        "depoison": (DEPOISON_IDS, DEPOISON_NAMES),
        "mp": (MP_POTION_IDS, MP_POTION_NAMES),
        "arrow": (SILVER_ARROW_IDS, SILVER_ARROW_NAMES),
    }
    return tables.get(str(kind or "arrow"), tables["arrow"])


def _is_kind(item: Any, kind: str) -> bool:
    ids, names = _kind_tables(kind)
    try:
        if int(getattr(item, "item_id", 0) or 0) in ids:
            return True
    except (TypeError, ValueError):
        pass
    lowered = {str(name).strip().lower() for name in names}
    for attr in ("name", "name_en", "name_tw", "name_cn"):
        if str(getattr(item, attr, "") or "").strip().lower() in lowered:
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
        if not _shift_drag(slots[idx], grid["drops"][0]):
            return None
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


def _release_shift(keys: Any) -> None:
    for key in ("shiftleft", "shiftright", "shift"):
        try:
            keys.release(key)
        except Exception:
            pass


def _shift_drag(src: tuple[int, int], dst: tuple[int, int]) -> bool:
    """Practice order: clear Shift, click the slot, then Shift-drag and button-up."""
    from app._05_action import mouse as mouse_mod
    from app._05_action.keyboard import KeyboardController
    from app._05_action.mouse import MouseController

    mouse = MouseController()
    keys = KeyboardController()
    released = False
    _release_shift(keys)
    time.sleep(0.03)
    mouse.click(float(src[0]), float(src[1]), snap=True)
    time.sleep(0.08)
    _release_shift(keys)
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
        released = True
        time.sleep(0.12)
        _release_shift(keys)
        time.sleep(0.05)
        mouse_mod._send_button("left", down=False, px=int(dst[0]), py=int(dst[1]))
    return released


def _type_qty(qty: int) -> None:
    from app._05_action.keyboard import KeyboardController

    keys = KeyboardController()
    for ch in str(max(1, int(qty))):
        keys.press(ch, duration=0.04)
        time.sleep(0.05)
    keys.press("enter", duration=0.06)
