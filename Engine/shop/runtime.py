"""Live-bot shopping execution (calibrated behaviors + recover stub)."""
from __future__ import annotations

import random
import time
from typing import Any, Callable, Optional

from shop.behaviors import (
    ShoppingBehavior,
    behavior_by_id,
    item_passes_sell_filter,
    load_sell_filters,
)
from shop.sell_slot_layout import (
    SELL_SLOT_KEYS,
    load_sell_slot_layout,
)

_SELL_MAX_ITEMS = 80
# One wheel flick moves this many sell-list rows. A person does not nudge one row.
SELL_SCROLL_CHUNKS = (5, 6, 7)


def _uv_xy(uv) -> tuple[float, float]:
    if hasattr(uv, "x") and hasattr(uv, "y"):
        return float(uv.x), float(uv.y)
    return float(uv[0]), float(uv[1])


def _click_uv(executor, bounds, uv, *, wait_s: float) -> None:
    from app._05_action.coordinates import game_to_screen

    u, v = _uv_xy(uv)
    sx, sy = game_to_screen(u, v, bounds)
    executor.mouse.move_and_click(sx, sy, snap=True)
    time.sleep(wait_s)


def _scroll_list(executor, bounds, scroll_uv, steps: int, *, move: bool = True) -> None:
    from app._05_action.coordinates import game_to_screen
    from app._05_action.input_backend import scroll_wheel

    if steps <= 0:
        return
    if move:
        u, v = _uv_xy(scroll_uv)
        sx, sy = game_to_screen(u, v, bounds)
        executor.mouse.move(sx, sy, snap=True)
        time.sleep(0.15)
    for _ in range(steps):
        scroll_wheel("down")
        time.sleep(0.08)
    time.sleep(0.25)


def _npc_nav(behavior: ShoppingBehavior) -> tuple[int, int]:
    from app._03_world.merge.memory_sync import game_to_nav

    return game_to_nav(behavior.npc_world_x, behavior.npc_world_y)


def npc_content_uv(behavior: ShoppingBehavior, player_origin) -> Any:
    from app._03_world.space.world_coords import world_to_content

    nav = _npc_nav(behavior)
    return world_to_content(
        float(nav[0] - player_origin.x),
        float(nav[1] - player_origin.y),
    )


def shop_distance(origin, behavior: ShoppingBehavior) -> int:
    from app._03_world.space.world_coords import tile_chebyshev

    nav = _npc_nav(behavior)
    return int(tile_chebyshev(origin.x, origin.y, nav[0], nav[1]))


def near_shop(origin, behavior: ShoppingBehavior) -> bool:
    from app._04_decision.shops import SHOP_ARRIVE_TILES

    return shop_distance(origin, behavior) <= SHOP_ARRIVE_TILES


def close_enough_to_click(origin, behavior: ShoppingBehavior) -> bool:
    from app._04_decision.shops import SHOP_CLICK_TILES

    return shop_distance(origin, behavior) <= SHOP_CLICK_TILES


def shop_nav_tile(behavior: ShoppingBehavior) -> tuple[int, int]:
    return _npc_nav(behavior)


def ensure_behavior_map_origin(behavior: ShoppingBehavior) -> None:
    """Point game_to_nav at the behavior's map pack (Practice does this first)."""
    from app._03_world.space import map_pack as map_pack_mod
    from app._03_world.space.map_pack import get_active_map_pack, load_map_pack, resolve_maps_dir
    from app._03_world.merge.memory_sync import configure_map_origin

    mid = str(getattr(behavior, "map_id", "") or "").strip()
    pack = get_active_map_pack()
    if pack is not None and mid and pack.id == mid:
        configure_map_origin(
            {
                "navigation": {
                    "map_origin_x": pack.origin_x,
                    "map_origin_y": pack.origin_y,
                }
            }
        )
        return
    maps_dir = resolve_maps_dir({})
    if maps_dir is None:
        maps_dir = map_pack_mod._PROJECT_ROOT / "data" / "maps"
    if not mid or not maps_dir.is_dir():
        return
    try:
        pack = load_map_pack(maps_dir, mid, section={})
    except Exception:
        return
    configure_map_origin(
        {
            "navigation": {
                "map_origin_x": pack.origin_x,
                "map_origin_y": pack.origin_y,
            }
        }
    )


def player_game_xy(world) -> tuple[int, int] | None:
    """Raw LC world tile of the player, or None if memory is not ready."""
    if world is None:
        return None
    print_snap = getattr(world, "last_print_state", None)
    player = print_snap.get("player") if isinstance(print_snap, dict) else None
    if isinstance(player, dict):
        try:
            gx, gy = int(player["x"]), int(player["y"])
        except (KeyError, TypeError, ValueError):
            gx, gy = 0, 0
        if gx != 0 or gy != 0:
            return gx, gy
    snap = getattr(world, "last_memory_snapshot", None)
    raw = snap.get("player") if isinstance(snap, dict) else None
    pos = raw.get("pos") if isinstance(raw, dict) else None
    if isinstance(pos, (list, tuple)) and len(pos) >= 2:
        try:
            gx, gy = int(pos[0]), int(pos[1])
        except (TypeError, ValueError):
            return None
        if gx != 0 or gy != 0:
            return gx, gy
    return None


def world_near_shop(world, behavior: ShoppingBehavior, *, tiles: int | None = None) -> bool:
    """True when raw player world pos is within ``tiles`` of the catalog NPC.

    Independent of nav origin — after a TI→Giran scroll the nav tile can be
    stale while the monitor already shows Giran coordinates.
    """
    from app._04_decision.shops import SHOP_ARRIVE_TILES

    xy = player_game_xy(world)
    if xy is None:
        return False
    limit = int(SHOP_ARRIVE_TILES if tiles is None else tiles)
    return max(
        abs(xy[0] - int(behavior.npc_world_x)),
        abs(xy[1] - int(behavior.npc_world_y)),
    ) <= limit


def player_origin_from_executor(executor) -> Any:
    """Live player nav tile from this tick's memory, preferring print_state."""
    from app._03_world.merge.memory_sync import game_to_nav, world_origin_from_snapshot
    from app._03_world.space.world_coords import WorldOrigin

    world = getattr(executor, "_world", None)
    if world is None:
        return None
    xy = player_game_xy(world)
    if xy is not None:
        nx, ny = game_to_nav(xy[0], xy[1])
        return WorldOrigin(x=nx, y=ny)
    snap = getattr(world, "last_memory_snapshot", None)
    if not snap:
        return None
    return world_origin_from_snapshot(snap)


def open_shop_npc(executor, bounds, behavior: ShoppingBehavior, origin=None) -> bool:
    """Open the NPC dialog for shop / warehouse / teleporter.

    When ``behavior.click_offset_uv`` is set: single click at
    content UV ``A + offset`` (calibrated). Otherwise cursor-scan:
    1) tile hunt around the catalog/live NPC cell
    2) 20px pixel ring around the catalog UV

    After a successful NPC click, wait until the matching uidialog is OPEN
    (``UIDIALOG_OPEN_TIMEOUT_S``, default 3s) before Buy/Sell/option clicks.
    """
    from app._04_decision.shops import SHOP_NPC_SEARCH_PX
    from app._05_action import humanize as hz
    from app._05_action.coordinates import game_to_screen
    from app._05_action.cursor_verify import (
        dialog_click,
        dialog_click_destinations,
        dialog_click_ring,
    )
    from app._05_action.uidialog_gate import (
        expected_labels_for_shop_kind,
        wait_uidialog_open,
    )

    ensure_behavior_map_origin(behavior)
    live = player_origin_from_executor(executor)
    if live is not None:
        origin = live
    if origin is None:
        return False
    npc_uv = npc_content_uv(behavior, origin)
    click_bounds = bounds
    capture = getattr(executor, "_perception_capture", None)
    if capture is not None:
        fresh = getattr(capture, "content_bounds", None)
        if fresh is not None and getattr(fresh, "valid", False):
            click_bounds = fresh

    def _screen(u, v):
        return game_to_screen(u, v, click_bounds)

    opened = False
    offset = getattr(behavior, "click_offset_uv", None)
    if offset is not None:
        u = max(0.0, min(1.0, float(npc_uv.x) + float(offset[0])))
        v = max(0.0, min(1.0, float(npc_uv.y) + float(offset[1])))
        sx, sy = _screen(u, v)
        executor.mouse.move(sx, sy, snap=True)
        if hz.SHOP_NPC_SEARCH_STEP_S > 0:
            time.sleep(hz.SHOP_NPC_SEARCH_STEP_S)
        opened = dialog_click(executor, sx, sy)
    else:
        world = getattr(executor, "_world", None) or getattr(executor, "world", None)
        dests = shop_dialog_destinations(world, behavior, npc_uv, origin)
        if dests:
            opened = dialog_click_destinations(
                executor,
                dests,
                _screen,
                step_s=hz.SHOP_NPC_SEARCH_STEP_S,
            )
        if not opened:
            opened = dialog_click_ring(
                executor,
                npc_uv,
                _screen,
                radius_px=SHOP_NPC_SEARCH_PX,
                step_s=hz.SHOP_NPC_SEARCH_STEP_S,
            )
    if not opened:
        return False
    kind = str(getattr(behavior, "action", "") or "buy").strip().lower()
    labels = expected_labels_for_shop_kind(kind)
    if not wait_uidialog_open(
        labels, timeout_s=float(hz.UIDIALOG_OPEN_TIMEOUT_S)
    ):
        return False
    return True


def _npc_world_xy(item) -> tuple[int, int] | None:
    if isinstance(item, dict):
        cx, cy = item.get("world_cx"), item.get("world_cy")
        if cx is None or cy is None:
            world = item.get("world") if isinstance(item.get("world"), dict) else {}
            cx, cy = world.get("cx"), world.get("cy")
    else:
        cx, cy = getattr(item, "world_cx", None), getattr(item, "world_cy", None)
    if cx is None or cy is None:
        return None
    return int(cx), int(cy)


def _npc_relative_xy(item) -> tuple[int, int] | None:
    if isinstance(item, dict):
        rx, ry = item.get("world_rx"), item.get("world_ry")
    else:
        rx, ry = getattr(item, "world_rx", None), getattr(item, "world_ry", None)
    if rx is None or ry is None:
        return None
    return int(rx), int(ry)


def _iter_live_npcs(world) -> list[Any]:
    out: list[Any] = []
    if world is None:
        return out
    for row in getattr(world, "last_print_entities", None) or []:
        cls = str(row.get("classification") or row.get("class") or "").lower()
        if cls in ("npc", "interactivenpc"):
            out.append(row)
    npcs_fn = getattr(world, "npcs", None)
    if callable(npcs_fn):
        out.extend(list(npcs_fn() or []))
    return out


def shop_npc_memory_hit(world, behavior: ShoppingBehavior) -> Any:
    """Live NPC nearest the catalog world pin, or None if none are close."""
    tx, ty = int(behavior.npc_world_x), int(behavior.npc_world_y)
    best = None
    best_d = 4
    for item in _iter_live_npcs(world):
        xy = _npc_world_xy(item)
        if xy is None:
            continue
        dist = max(abs(xy[0] - tx), abs(xy[1] - ty))
        if dist >= best_d:
            continue
        best_d = dist
        best = item
    return best


def shop_dialog_destinations(world, behavior: ShoppingBehavior, fallback_uv, origin):
    """Content UVs to hunt for the dialog cursor: live NPC cell, then 1 tile."""
    from types import SimpleNamespace

    from app._02_state.objects import Position
    from app._03_world.space.world_coords import world_to_content
    from app._05_action.travel_click import object_cursor_search_destinations

    hit = shop_npc_memory_hit(world, behavior)
    if hit is not None and not isinstance(hit, dict):
        return object_cursor_search_destinations(hit, radius=1)
    if isinstance(hit, dict):
        rxry = _npc_relative_xy(hit)
        dummy = SimpleNamespace(
            position=Position(
                x=float(hit.get("position_x") or 0.0),
                y=float(hit.get("position_y") or 0.0),
            ),
            world_rx=None if rxry is None else rxry[0],
            world_ry=None if rxry is None else rxry[1],
        )
        return object_cursor_search_destinations(dummy, radius=1)
    if origin is not None:
        nav = _npc_nav(behavior)
        rx, ry = int(nav[0] - origin.x), int(nav[1] - origin.y)
        dummy = SimpleNamespace(
            position=fallback_uv or world_to_content(float(rx), float(ry)),
            world_rx=rx,
            world_ry=ry,
        )
        return object_cursor_search_destinations(dummy, radius=1)
    return [fallback_uv] if fallback_uv is not None else []


def _type_qty(executor, qty: int, *, wait_s: float) -> None:
    executor.keyboard.tap("backspace", count=3)
    for digit in str(max(1, min(999, int(qty)))):
        executor.keyboard.press(digit)
    time.sleep(wait_s)


def execute_calibrated_buy(
    executor,
    bounds,
    behavior: ShoppingBehavior,
    *,
    qty: Optional[int] = None,
) -> bool:
    """Buy UI from calibrated behavior UVs. True on completed confirm click."""
    from app._05_action import humanize as hz

    ui = behavior.ui
    if not ui.calibrated(action="buy"):
        return False
    assert ui.buy_button is not None
    assert ui.list_scroll_point is not None
    assert ui.confirm_button is not None
    wait = hz.SHOP_BUTTON_WAIT_S
    _click_uv(executor, bounds, ui.buy_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
    _scroll_list(
        executor, bounds, ui.list_scroll_point, behavior.scroll_steps_for_item()
    )
    row_i = behavior.visible_row_for_item()
    row_uv = ui.item_rows[row_i]
    if row_uv is None:
        return False
    _click_uv(executor, bounds, row_uv, wait_s=wait)
    amount = int(qty) if qty is not None else int(behavior.default_qty)
    # Practice buy taps backspace once, then types the quantity.
    executor.keyboard.tap("backspace", count=1)
    for digit in str(max(1, min(999, amount))):
        executor.keyboard.press(digit)
    time.sleep(wait)
    _click_uv(executor, bounds, ui.confirm_button, wait_s=wait)
    return True


def execute_calibrated_teleporter(
    executor,
    bounds,
    behavior: ShoppingBehavior,
) -> bool:
    """Teleporter dialog: option click + confirm (no list slot / qty)."""
    from app._05_action import humanize as hz
    from shop.behaviors import ACTION_TELEPORTER

    ui = behavior.ui
    if not ui.calibrated(action=ACTION_TELEPORTER):
        return False
    assert ui.buy_button is not None
    assert ui.confirm_button is not None
    wait = hz.SHOP_BUTTON_WAIT_S
    _click_uv(executor, bounds, ui.buy_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
    _click_uv(executor, bounds, ui.confirm_button, wait_s=wait)
    return True


def _sell_hit_center_uv(hit, slots, frame) -> tuple[float, float]:
    key = hit.fkey or ""
    box = slots.get(key) or {}
    if "x0" in box and "x1" in box:
        return (
            (float(box["x0"]) + float(box["x1"])) / 2.0,
            (float(box["y0"]) + float(box["y1"])) / 2.0,
        )
    fh, fw = frame.shape[:2]
    return (
        (hit.x + hit.w / 2) / max(fw, 1),
        (hit.y + hit.h / 2) / max(fh, 1),
    )


def sell_scroll_clicks(
    indices: list[int],
    *,
    visible_rows: int = 7,
    limit: int = _SELL_MAX_ITEMS,
    list_len: int | None = None,
    chunk_picker: Callable[[], int] | None = None,
) -> list[tuple]:
    """Steps for one sell dialog.

    ``("scroll", notches)`` then ``("click", target_i, visible_row)``.
    The list starts at the top. Every flick rolls 5, 6, or 7 rows. The flick
    is shortened when fewer rows remain, and it never rolls past the next
    unselected row, so a click stays on that row. Rows already chosen are
    not clicked again when a short flick leaves them on screen.
    ``target_i`` is the position in ``indices`` (the caller sorts the same way).
    """
    rows = max(1, int(visible_rows))
    cap = max(0, int(limit))
    pairs = sorted(
        ((n, max(0, int(idx))) for n, idx in enumerate(indices)),
        key=lambda pair: (pair[1], pair[0]),
    )
    if not pairs:
        return []
    last_idx = pairs[-1][1]
    length = last_idx + 1 if list_len is None else max(int(list_len), last_idx + 1)
    max_scroll = max(0, length - rows)
    pick = chunk_picker or (lambda: random.choice(SELL_SCROLL_CHUNKS))

    steps: list[tuple] = []
    scroll_at = 0
    chosen = [False] * len(pairs)
    clicks = 0
    while clicks < cap and not all(chosen):
        for n, (target_i, idx) in enumerate(pairs):
            if chosen[n] or clicks >= cap:
                continue
            if scroll_at <= idx < scroll_at + rows:
                steps.append(("click", target_i, idx - scroll_at))
                chosen[n] = True
                clicks += 1
        if clicks >= cap or all(chosen):
            break
        pending = [
            idx
            for n, (_, idx) in enumerate(pairs)
            if not chosen[n] and idx >= scroll_at
        ]
        room = max_scroll - scroll_at
        if not pending or room <= 0:
            break
        try:
            roll = int(pick())
        except (TypeError, ValueError):
            roll = SELL_SCROLL_CHUNKS[0]
        if roll < 1:
            roll = SELL_SCROLL_CHUNKS[0]
        # Stay on the next unselected row, and stop at the bottom of the list.
        delta = min(roll, room, pending[0] - scroll_at)
        if delta <= 0:
            break
        steps.append(("scroll", delta))
        scroll_at += delta
    return steps


def execute_calibrated_sell(
    executor,
    bounds,
    behavior: ShoppingBehavior,
    *,
    grab_frame,
    npc_uv,
) -> bool:
    """Sell shop_listen Sell-tab rows using the same Keep/Sell rule as Debug.

    Open Sell once. Click every keep-list miss on the current screen, then
    flick the wheel 5, 6, or 7 rows and click the newly shown rows. One
    Confirm at the end closes the dialog. Adena (id 5) is never sold.
    ``grab_frame`` kept for call-site compat.
    """
    del npc_uv, grab_frame
    from app._01_perception.sensors import shared_sensors
    from app._01_perception.shop_listen_reader import parse_sell_entries
    from app._05_action import humanize as hz
    from shop.behaviors import ITEM_ROW_COUNT

    ui = behavior.ui
    is_store = str(behavior.action) == "store"
    if not ui.calibrated(action="store" if is_store else "sell"):
        return False
    if ui.list_scroll_point is None:
        return False
    if sum(1 for r in ui.item_rows if r is not None) < ITEM_ROW_COUNT:
        return False

    sensors = None if is_store else shared_sensors()
    if sensors is not None and not sensors.shop_ready:
        return False

    from shop.behaviors import resolve_active_sell_mode

    filters = load_sell_filters()
    # Same rule as Debug: keep_list ⇒ except_keep (ignore per-NPC only_garbage).
    sell_mode = resolve_active_sell_mode(filters=filters)
    qty = max(1, min(999, int(behavior.default_qty)))
    wait = hz.SHOP_BUTTON_WAIT_S
    sold = 0

    def read_sell_tab() -> tuple[list[dict], int] | None:
        """Sellable rows, and the full list length (keep rows included).

        Merchants use shop_listen. The warehouse uses the open storewin list.
        The visit opens the deposit tab, so bag-name overlap is not a mode check.
        None means that list was not open.
        """
        if is_store:
            from app._01_perception.storewin_reader import (
                capture_store,
                parse_store_entries,
            )

            snap = capture_store()
            if not snap or not snap.get("open"):
                return None
            rows = parse_store_entries(snap)
        else:
            rows = parse_sell_entries(sensors.capture_shop())
        sellable: list[dict] = []
        length = 0
        for row in rows:
            try:
                idx = max(0, int(row.get("idx") or 0))
            except (TypeError, ValueError):
                idx = 0
            length = max(length, idx + 1)
            try:
                item_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                item_id = 0
            if is_store and str(row.get("name") or "").strip() in ("아데나", "Adena"):
                continue
            if not item_passes_sell_filter(
                str(row.get("name") or ""),
                sell_mode=sell_mode,
                garbage_list=filters.garbage_list,
                keep_list=filters.keep_list,
                item_id=item_id,
            ):
                continue
            sellable.append(row)
        return sellable, max(length, len(rows))

    def open_sell() -> bool:
        if not open_shop_npc(
            executor, bounds, behavior, player_origin_from_executor(executor)
        ):
            return False
        _click_uv(executor, bounds, ui.sell_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
        time.sleep(0.35)
        return True

    def close_shop() -> None:
        try:
            executor.keyboard.press("escape")
        except Exception:
            pass

    def _idx(row: dict) -> int:
        try:
            return max(0, int(row.get("idx") or 0))
        except (TypeError, ValueError):
            return 0

    def _sell_qty(row: dict) -> int:
        try:
            row_count = max(0, int(row.get("count") or 0))
        except (TypeError, ValueError):
            row_count = 0
        return max(1, min(999, row_count if row_count > 0 else qty))

    # Confirm closes the dialog. Select every keep-list miss, then confirm once.
    if not open_sell():
        return False
    read = read_sell_tab()
    if read is None:
        close_shop()
        return False
    targets, list_len = read
    if not targets:
        close_shop()
        return True

    targets.sort(key=_idx)
    plan = sell_scroll_clicks(
        [_idx(row) for row in targets],
        visible_rows=ITEM_ROW_COUNT,
        limit=_SELL_MAX_ITEMS,
        list_len=list_len,
    )
    clicked_item = False
    for step in plan:
        if step[0] == "scroll":
            # After an item click, leave the cursor there. The wheel still
            # hits the sell list. Before any item click, hover the list.
            _scroll_list(
                executor,
                bounds,
                ui.list_scroll_point,
                int(step[1]),
                move=not clicked_item,
            )
            continue
        target = targets[int(step[1])]
        row_uv = ui.item_rows[int(step[2])]
        if row_uv is None:
            continue
        _click_uv(
            executor,
            bounds,
            row_uv,
            wait_s=random.uniform(0.2, 0.5),
        )
        _type_qty(executor, _sell_qty(target), wait_s=0)
        clicked_item = True
        sold += 1

    if sold <= 0:
        close_shop()
        return False

    _click_uv(executor, bounds, ui.confirm_button, wait_s=wait)
    time.sleep(0.25)
    return True


def execute_calibrated_sell_legacy_template(
    executor,
    bounds,
    behavior: ShoppingBehavior,
    *,
    grab_frame,
    npc_uv,
) -> bool:
    """Previous icon-template sell (no scroll). Kept for Practice/debug only."""
    del npc_uv
    from app._05_action import humanize as hz
    from hotbar.item_catalog import make_sell_icon_matcher
    from shop.behaviors import SELL_MODE_ONLY_GARBAGE

    ui = behavior.ui
    if not ui.calibrated(action="sell"):
        return False
    slots = load_sell_slot_layout()
    if slots is None:
        return False
    filters = load_sell_filters()
    matcher = make_sell_icon_matcher()
    if behavior.sell_mode == SELL_MODE_ONLY_GARBAGE:
        pool = matcher.item_templates(names=set(filters.garbage_list))
    else:
        pool = matcher.item_templates()
    if not pool:
        return False

    qty = max(1, min(999, int(behavior.default_qty)))
    wait = hz.SHOP_BUTTON_WAIT_S
    sold = 0

    def matching_hits(frame):
        hits = matcher.match_slot_boxes(
            frame,
            slots,
            SELL_SLOT_KEYS,
            threshold=0.7,
            templates=pool,
            use_color=True,
        )
        by_key = {h.fkey: h for h in hits if h.fkey}
        out = []
        for key in SELL_SLOT_KEYS:
            hit = by_key.get(key)
            if hit is None:
                continue
            if item_passes_sell_filter(
                hit.kr_name,
                sell_mode=behavior.sell_mode,
                garbage_list=filters.garbage_list,
                keep_list=filters.keep_list,
            ):
                out.append(hit)
        return out

    def open_sell() -> bool:
        if not open_shop_npc(
            executor, bounds, behavior, player_origin_from_executor(executor)
        ):
            return False
        _click_uv(executor, bounds, ui.sell_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
        return True

    while sold < _SELL_MAX_ITEMS:
        if not open_sell():
            return sold > 0
        frame = grab_frame()
        if frame is None:
            try:
                executor.keyboard.press("escape")
            except Exception:
                pass
            return sold > 0
        targets = matching_hits(frame)
        if not targets:
            try:
                executor.keyboard.press("escape")
            except Exception:
                pass
            return True
        for target in targets:
            if sold >= _SELL_MAX_ITEMS:
                break
            cu, cv = _sell_hit_center_uv(target, slots, frame)
            _click_uv(executor, bounds, (cu, cv), wait_s=wait)
            _type_qty(executor, qty, wait_s=wait)
            sold += 1
        _click_uv(executor, bounds, ui.confirm_button, wait_s=wait)

    return sold > 0


def resolve_behavior(behavior_id: str) -> Optional[ShoppingBehavior]:
    return behavior_by_id(str(behavior_id or "").strip())


def execute_recover_arrow_buy(executor, bounds, action) -> bool:
    """Hardcoded buy-arrows UI (only when Intent sets shop_use_recover)."""
    from app._04_decision.shops import (
        ARROW_BUY_QTY,
        SHOP_NPC_SEARCH_PX,
        shop_ui_clicks,
    )
    from app._05_action import humanize as hz
    from app._05_action.coordinates import game_to_screen
    from app._05_action.cursor_verify import dialog_click_ring

    dest = getattr(action, "destination", None)
    if dest is None:
        return False
    if not dialog_click_ring(
        executor,
        dest,
        lambda u, v: game_to_screen(u, v, bounds),
        radius_px=SHOP_NPC_SEARCH_PX,
        step_s=hz.SHOP_NPC_SEARCH_STEP_S,
    ):
        return False
    from app._05_action.uidialog_gate import (
        expected_labels_for_shop_kind,
        wait_uidialog_open,
    )

    if not wait_uidialog_open(
        expected_labels_for_shop_kind("buy"),
        timeout_s=float(hz.UIDIALOG_OPEN_TIMEOUT_S),
    ):
        return False

    clicks = shop_ui_clicks()
    sx, sy = game_to_screen(clicks.buy_tab.x, clicks.buy_tab.y, bounds)
    executor.mouse.move_and_click(sx, sy, snap=True)
    time.sleep(hz.SHOP_AFTER_TAB_WAIT_S)
    sx, sy = game_to_screen(clicks.arrow_row.x, clicks.arrow_row.y, bounds)
    executor.mouse.move_and_click(sx, sy, snap=True)
    time.sleep(hz.SHOP_BUTTON_WAIT_S)

    qty = getattr(action, "shop_qty", None)
    try:
        qty_i = int(qty) if qty is not None else int(ARROW_BUY_QTY)
    except (TypeError, ValueError):
        qty_i = int(ARROW_BUY_QTY)
    qty_i = max(1, min(999, qty_i))
    executor.keyboard.tap("backspace", count=3)
    for digit in str(qty_i):
        executor.keyboard.press(digit)
    time.sleep(hz.SHOP_BUTTON_WAIT_S)

    confirm = clicks.confirm
    cx, cy = game_to_screen(confirm.x, confirm.y, bounds)
    executor.mouse.move_and_click(cx, cy, snap=True)
    time.sleep(hz.SHOP_BUTTON_WAIT_S)
    return True


def execute_shop_intent(executor, bounds, action) -> tuple[bool, str]:
    """Run one SHOP_RUN Intent. Returns ``(ok, behavior_id_for_feedback)``.

    Decide owns ``shop_kind`` / ``shop_qty`` / ``shop_use_recover``. Action
    should call this instead of re-resolving buy/sell/teleporter policy.
    """
    if getattr(action, "destination", None) is None:
        return False, ""

    if bool(getattr(action, "shop_use_recover", False)):
        ok = execute_recover_arrow_buy(executor, bounds, action)
        return ok, ""

    behavior_id = str(getattr(action, "shop_behavior_id", None) or "").strip()
    if not behavior_id:
        return False, ""

    behavior = resolve_behavior(behavior_id)
    if behavior is None:
        return False, behavior_id
    kind = str(getattr(action, "shop_kind", None) or "").strip().lower()
    if kind not in ("buy", "sell", "store", "teleporter"):
        kind = str(getattr(behavior, "action", "") or "buy").strip().lower()
    if not behavior.ui.calibrated(action=kind):
        return False, behavior_id

    # store reads the warehouse window (storewin). sell reads shop_listen.
    # Both then use the same keep-list clicks and scroll flicks.
    if kind in ("sell", "store"):
        capture = getattr(executor, "_perception_capture", None)
        if capture is None:
            return False, behavior_id

        def _grab():
            return None

        ok = execute_calibrated_sell(
            executor,
            bounds,
            behavior,
            grab_frame=_grab,
            npc_uv=action.destination,
        )
        return bool(ok), behavior_id

    if not open_shop_npc(
        executor, bounds, behavior, player_origin_from_executor(executor)
    ):
        return False, behavior_id

    if kind == "teleporter":
        ok = execute_calibrated_teleporter(executor, bounds, behavior)
        return bool(ok), behavior_id

    qty = getattr(action, "shop_qty", None)
    if qty is not None:
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            qty = None
    if qty is not None and qty < 1:
        return True, behavior_id

    ok = execute_calibrated_buy(executor, bounds, behavior, qty=qty)
    return bool(ok), behavior_id
