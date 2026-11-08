"""Supply drop loop matching the agreed experimental plan."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional

from app._01_perception.sensors import PerceptionSensors
from app._05_action.content_crop import compute_43_crop
from app._05_action.keyboard import KeyboardController
from app._05_action.mouse import MouseController
from app._05_action.window_bounds import find_game_window, get_client_bounds

from supply.drop_geom import drop_screen_points, drop_world_tile, pick_drop_index
from supply.grid import ROWS, COLS, default_grid_path, scale_grid_to_client
from supply.input_ops import (
    ensure_input,
    open_inventory,
    scroll_click,
    shift_drag,
    type_quantity,
)
from supply.inventory import (
    count_matches,
    find_first,
    list_index_1based,
    ordered_items,
    read_bag,
    wait_bag_change,
)
from supply.session import MAX_DRAG_TRIES, SupplyItem, SupplySession
from supply import windows as ui
from supply.walk import walk_to_tile

LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]
GAME_PROCESS = "LC.exe"


@dataclass
class SupplyRequest:
    world_x: int
    world_y: int
    items: list[SupplyItem]
    walk_first: bool = True


def _client_size() -> tuple[int, int]:
    hwnd = find_game_window(GAME_PROCESS)
    if hwnd is None:
        raise RuntimeError("LC.exe window not found")
    bounds = get_client_bounds(int(hwnd))
    if bounds is None or not bounds.valid:
        raise RuntimeError("client bounds invalid")
    return int(bounds.width), int(bounds.height)


def _client_origin() -> tuple[int, int]:
    hwnd = find_game_window(GAME_PROCESS)
    if hwnd is None:
        raise RuntimeError("LC.exe window not found")
    bounds = get_client_bounds(int(hwnd))
    if bounds is None or not bounds.valid:
        raise RuntimeError("client bounds invalid")
    return int(bounds.left), int(bounds.top)


def _to_screen(client_xy: tuple[int, int]) -> tuple[int, int]:
    left, top = _client_origin()
    return left + int(client_xy[0]), top + int(client_xy[1])


def _player_world(sensors: PerceptionSensors) -> Optional[tuple[int, int]]:
    from app._03_world.merge.memory_sync import world_origin_from_snapshot

    buf = sensors.capture_field()
    for snap in (
        buf.player if getattr(buf, "player_ok", False) else None,
        buf.print_state if getattr(buf, "print_state_ok", False) else None,
    ):
        if not isinstance(snap, dict):
            continue
        wo = world_origin_from_snapshot(snap)
        if wo is not None:
            return int(wo.x), int(wo.y)
    return None


def _raw_row_col(list_index: int) -> tuple[int, int]:
    raw_num = (int(list_index) - 1) // COLS + 1
    col_num = (int(list_index) - 1) % COLS + 1
    return raw_num, col_num


def _scroll_into_view(
    mouse: MouseController,
    grid,
    list_index: int,
    ri: int,
    *,
    rng: random.Random,
    log: LogFn,
) -> int:
    """Bring bag row into the 8-row window. Returns updated ri (top row index offset)."""
    raw_num, col_num = _raw_row_col(list_index)
    while True:
        delta = raw_num - ri
        if 1 <= delta <= ROWS:
            row_on_screen = delta  # 1..8
            idx = (row_on_screen - 1) * COLS + (col_num - 1)
            # slot click target is handled by caller via grid.slots[idx]
            return ri
        if delta <= 0:
            n = 1 + ri - raw_num
            log(f"scroll up x{n} (ri={ri} -> raw={raw_num})")
            for _ in range(n):
                scroll_click(mouse, _to_screen(grid.scroll_up), rng=rng)
            ri = raw_num - 1
            continue
        # delta > ROWS
        n = raw_num - ri - ROWS
        log(f"scroll down x{n} (ri={ri} raw={raw_num})")
        for _ in range(n):
            scroll_click(mouse, _to_screen(grid.scroll_down), rng=rng)
        ri = raw_num - ROWS


def _slot_screen(grid, list_index: int, ri: int) -> tuple[int, int]:
    raw_num, col_num = _raw_row_col(list_index)
    row_on_screen = raw_num - ri
    idx = (row_on_screen - 1) * COLS + (col_num - 1)
    return _to_screen(grid.slots[idx])


def _ensure_inventory(keyboard: KeyboardController, log: LogFn) -> bool:
    snap = ui.read_uidialog()
    if ui.inventory_open(snap):
        return True
    log("inventory closed -> Ctrl+I")
    open_inventory(keyboard)
    return ui.wait_open(
        (ui.LABEL_INVENTORY,),
        timeout_s=3.0,
        poll_s=0.1,
        force_scan=True,
    )


def run_supply(
    request: SupplyRequest,
    *,
    session: Optional[SupplySession] = None,
    sensors: Optional[PerceptionSensors] = None,
    log: Optional[LogFn] = None,
    cancel: Optional[CancelFn] = None,
) -> SupplySession:
    def _log(msg: str) -> None:
        if log:
            log(msg)

    def _cancel() -> bool:
        return bool(cancel and cancel())

    sess = session or SupplySession()
    sess.begin(list(request.items))
    if sensors is None:
        from app._01_perception.sensors import shared_sensors

        sense = shared_sensors()
    else:
        sense = sensors
    rng = random.Random()
    ensure_input()
    mouse = MouseController()
    keyboard = KeyboardController()
    outcome = "finished"

    try:
        if request.walk_first:
            _log(f"walk to supply tile ({request.world_x},{request.world_y})")
            ok = walk_to_tile(
                (int(request.world_x), int(request.world_y)),
                sensors=sense,
                log=_log,
                cancel=cancel,
            )
            if not ok:
                _log("walk failed — abort supply")
                for item in sess.request:
                    left = sess.remaining.get(item.key(), item.qty)
                    sess.note_failed(item, left)
                outcome = "aborted"
                return sess

        sess.start_dropping()
        _log("dropping locked (combat/move/loot blocked)")

        if not _ensure_inventory(keyboard, _log):
            _log("inventory did not open")
            for item in sess.request:
                sess.note_failed(item, sess.remaining.get(item.key(), item.qty))
            outcome = "aborted"
            return sess

        grid_file = default_grid_path()
        if not grid_file.is_file():
            _log(
                "inventory grid missing: "
                f"{grid_file}. Run Tool_Supply_Grid.bat, open a client "
                "screenshot with the bag visible, click the 8x4 slots and "
                "both scroll arrows, then save that path."
            )
            for item in sess.request:
                sess.note_failed(item, sess.remaining.get(item.key(), item.qty))
            outcome = "aborted"
            return sess

        cw, ch = _client_size()
        crop = compute_43_crop(cw, ch)
        grid = scale_grid_to_client(cw, ch)
        drops = drop_screen_points(cw, ch)
        _log(
            f"client={cw}x{ch} crop=({crop.left},{crop.top},{crop.width}x{crop.height}) "
            f"drops={[ _to_screen(p) for p in drops ]}"
        )

        bag = read_bag()
        items = ordered_items(bag)
        _log(f"bag rows={len(items)}")

        ri = 0
        for item in list(sess.request):
            if _cancel():
                _log("cancelled (stop)")
                outcome = "cancelled"
                break
            left = int(sess.remaining.get(item.key(), 0))
            if left <= 0:
                continue
            _log(f"supply {item.key()} left={left}")

            while left > 0:
                if _cancel():
                    outcome = "cancelled"
                    break
                bag = read_bag()
                items = ordered_items(bag)
                row = find_first(items, item_id=item.item_id, name=item.name)
                if row is None:
                    _log(f"missing in bag -> fail remaining {left}")
                    sess.note_failed(item, left)
                    sess.remaining[item.key()] = 0
                    break

                before_rows, before_qty = count_matches(
                    items, item_id=item.item_id, name=item.name
                )
                try:
                    slot_count = int(row.get("count") or 0)
                except (TypeError, ValueError):
                    slot_count = 0
                # The quantity field opens only after this slot is Shift-dragged.
                # One slot with count > 1 needs that field even when other
                # stacks of the same item also exist.
                needs_qty = slot_count > 1
                want = min(left, slot_count) if needs_qty else 1
                list_index = list_index_1based(row)
                ri = _scroll_into_view(mouse, grid, list_index, ri, rng=rng, log=_log)
                src = _slot_screen(grid, list_index, ri)

                success = False
                for attempt in range(1, MAX_DRAG_TRIES + 1):
                    if _cancel():
                        break
                    which = pick_drop_index(rng)
                    dst_client = drops[which]
                    dst = _to_screen(dst_client)
                    _log(
                        f"drag try {attempt}/{MAX_DRAG_TRIES} "
                        f"slot={list_index} -> drop[{which}] {dst} want={want}"
                    )
                    if not ui.inventory_open():
                        if not _ensure_inventory(keyboard, _log):
                            _log("inventory lost — abort item")
                            break
                    _log(
                        f"shift-drag slot={list_index} count={slot_count} "
                        f"-> then qty field" if needs_qty else
                        f"shift-drag slot={list_index} count={slot_count} (no qty field)"
                    )
                    shift_drag(mouse, keyboard, src, dst, hold_s=0.55)

                    if needs_qty:
                        # UIdialogmon-style: qty notice = popup msg with Esc+Enter.
                        from supply.confirm_reader import (
                            describe as confirm_describe,
                            wait_qty_prompt,
                        )

                        from supply.qty_diag import (
                            LOG_PATH as QTY_LOG,
                            append_event,
                            run_typed_quantity,
                            snapshot_monitor,
                            verdict_after_type,
                        )

                        if wait_qty_prompt(timeout_s=3.0, poll_s=0.1):
                            _log(f"qty monitor HIT; {confirm_describe()}")
                            typed = run_typed_quantity(
                                want, bag_before=before_qty, log=_log
                            )
                            # Wait until qty prompt clears (or short settle).
                            deadline_amt = time.time() + 2.5
                            while time.time() < deadline_amt:
                                from supply.confirm_reader import qty_prompt_open

                                if not qty_prompt_open():
                                    break
                                time.sleep(0.1)
                            post_mon = snapshot_monitor()
                            after_peek = ordered_items(read_bag())
                            _, after_peek_qty = count_matches(
                                after_peek, item_id=item.item_id, name=item.name
                            )
                            code, brief = verdict_after_type(
                                pre_qty_open=True,
                                post_qty_open=bool(
                                    post_mon.get("qty_prompt_open")
                                ),
                                enter_ok=bool(
                                    (typed.get("enter_chat") or {}).get("ok")
                                ),
                                enter_status=(typed.get("enter_chat") or {}).get(
                                    "status"
                                ),
                                enter_chars=int(
                                    (typed.get("enter_chat") or {}).get("chars")
                                    or 0
                                ),
                                enter_keys=int(
                                    (typed.get("enter_chat") or {}).get("keys")
                                    or 0
                                ),
                                enter_failed=int(
                                    (typed.get("enter_chat") or {}).get("failed")
                                    or 0
                                ),
                                bag_before=before_qty,
                                bag_after=after_peek_qty,
                                want=want,
                            )
                            append_event(
                                {
                                    "phase": "qty_final",
                                    "verdict": code,
                                    "brief": brief,
                                    "want": want,
                                    "bag_before": before_qty,
                                    "bag_after": after_peek_qty,
                                    "enter_chat": typed.get("enter_chat"),
                                    "monitor_post": post_mon,
                                    "log_file": str(QTY_LOG),
                                },
                                log=_log,
                            )
                            if code.startswith("INPUT_CLI") or code == "INPUT_NO_EFFECT":
                                keyboard.press("esc")
                                time.sleep(0.2)
                                continue
                        else:
                            # Fallback: legacy AmountSelector open flag.
                            mon = snapshot_monitor()
                            append_event(
                                {
                                    "phase": "qty_wait_miss",
                                    "verdict": "MONITOR_MISS",
                                    "brief": "wait_qty_prompt timeout",
                                    "monitor": mon,
                                },
                                log=_log,
                            )
                            if ui.wait_open(
                                (ui.LABEL_AMOUNT,),
                                timeout_s=1.0,
                                poll_s=0.12,
                                force_scan=True,
                            ):
                                _log("qty via AmountSelector (no Esc/Enter popup)")
                                typed = run_typed_quantity(
                                    want, bag_before=before_qty, log=_log
                                )
                                ui.wait_closed((ui.LABEL_AMOUNT,), timeout_s=2.0)
                                if not (typed.get("enter_chat") or {}).get("ok"):
                                    keyboard.press("esc")
                                    time.sleep(0.2)
                                    continue
                            else:
                                _log(
                                    f"qty prompt not seen; {confirm_describe()}; "
                                    f"{ui.describe()}"
                                )
                                keyboard.press("esc")
                                time.sleep(0.25)

                    # Drag done: poll bag at 100ms until qty/rows update.
                    after = wait_bag_change(
                        before_rows=before_rows,
                        before_qty=before_qty,
                        item_id=item.item_id,
                        name=item.name,
                        timeout_s=2.0,
                        poll_s=0.100,
                    )
                    after_rows, after_qty = count_matches(
                        after, item_id=item.item_id, name=item.name
                    )
                    if needs_qty:
                        dropped = before_qty - after_qty
                        if dropped >= want:
                            dropped = want
                        if dropped <= 0:
                            continue
                    else:
                        if after_rows >= before_rows and after_qty >= before_qty:
                            continue
                        dropped = 1

                    pose = _player_world(sense)
                    if pose is None:
                        pose = (int(request.world_x), int(request.world_y))
                    wx, wy = drop_world_tile(pose[0], pose[1], which)
                    sess.record_drop(
                        item_id=item.item_id,
                        name=item.name or str(row.get("name") or ""),
                        world_x=wx,
                        world_y=wy,
                        qty=dropped,
                    )
                    left -= dropped
                    sess.remaining[item.key()] = max(0, left)
                    _log(f"drop ok qty={dropped} tile=({wx},{wy}) left={left}")
                    success = True
                    break

                if outcome == "cancelled":
                    break
                if not success:
                    _log(f"drag failed x{MAX_DRAG_TRIES} -> failed_list {left}")
                    sess.note_failed(item, left)
                    sess.remaining[item.key()] = 0
                    break

        if ri > 0:
            _log(f"reset scroll up x{ri}")
            for _ in range(ri):
                scroll_click(
                    mouse,
                    _to_screen(grid.scroll_up),
                    gap_s=0.100,
                    jitter_s=0.010,
                    rng=rng,
                )
            ri = 0

    finally:
        sess.finish()
        _log(f"supply {outcome}; loot blocked 5s")
    return sess
