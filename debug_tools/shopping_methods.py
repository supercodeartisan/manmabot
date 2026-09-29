"""Practice runners for shopping behaviors (travel + calibrated UV loop)."""
from __future__ import annotations

import time

from debug_tools.shopping_catalog import PracticeResult


def _prepare_config_for_map(map_id: str) -> tuple[dict, object]:
    from tool.utils import load_config
    from manmabot_v1.profile import load_profile
    from app._04_decision.configure import configure_action, configure_decision
    from app._03_world.memory_sync import configure_map_origin
    from app._04_decision.nav_config import navigation_with_map_pack
    from app._05_action.spell_box import configure_spell_box

    config = load_config()
    profile = load_profile()
    decision = dict(config.get("decision") or {})
    decision["game_language"] = getattr(profile, "game_language", "ko") or "ko"
    config["decision"] = decision
    nav = dict(config.get("navigation") or {})
    if map_id:
        nav["active_map"] = str(map_id).strip()
    config["navigation"] = nav

    configure_decision(config)
    configure_action(config)
    configure_map_origin(navigation_with_map_pack(config))
    slots = getattr(profile, "spell_slots", None) or {}
    if slots:
        configure_spell_box(slots)
    return config, profile


def _player_world_origin(config: dict):
    from app._03_world.memory_client import PIPE_NAME, LineageMonitor
    from app._03_world.memory_sync import world_origin_from_snapshot

    section = (config or {}).get("memory") or {}
    if not bool(section.get("enabled", False)):
        return None, "memory.enabled is false in engine config/memory.yaml"

    pipe = str(section.get("pipe") or PIPE_NAME)
    retries = max(5, int(section.get("connect_retries", 30)))
    delay = float(section.get("connect_delay", 0.2))
    monitor = LineageMonitor(pipe=pipe, connect_retries=retries, connect_delay=delay)
    try:
        monitor.connect()
        monitor.ping()
        snap = monitor.snapshot(fresh=True)
    except Exception as exc:
        return None, str(exc)
    finally:
        try:
            monitor.close()
        except Exception:
            pass

    origin = world_origin_from_snapshot(snap or {})
    if origin is None:
        return (
            None,
            "memory connected but no player position yet "
            "(enter the game world; lamp should be green)",
        )
    return origin, ""


def _npc_nav(behavior) -> tuple[int, int]:
    from app._03_world.memory_sync import game_to_nav

    return game_to_nav(behavior.npc_world_x, behavior.npc_world_y)


def _near_shop(origin, behavior) -> bool:
    from app._03_world.world_coords import tile_chebyshev
    from app._04_decision.shops import SHOP_ARRIVE_TILES

    nav = _npc_nav(behavior)
    return (
        tile_chebyshev(origin.x, origin.y, nav[0], nav[1]) <= SHOP_ARRIVE_TILES
    )


def _npc_content_uv(behavior, player_origin):
    """Content UV (``Position``) of behavior NPC relative to the player."""
    from app._03_world.world_coords import world_to_content

    nav = _npc_nav(behavior)
    return world_to_content(
        float(nav[0] - player_origin.x),
        float(nav[1] - player_origin.y),
    )


def _uv_xy(uv) -> tuple[float, float]:
    """Normalize Position or (u, v) to a float pair for screen mapping."""
    if hasattr(uv, "x") and hasattr(uv, "y"):
        return float(uv.x), float(uv.y)
    return float(uv[0]), float(uv[1])


def _click_uv(executor, bounds, uv, *, wait_s: float = 0.5) -> None:
    from app._05_action.coordinates import game_to_screen

    u, v = _uv_xy(uv)
    sx, sy = game_to_screen(u, v, bounds)
    executor.mouse.move_and_click(sx, sy, snap=True)
    time.sleep(wait_s)


def _scroll_list(executor, bounds, scroll_uv, steps: int) -> None:
    """Move to list, then mouse-wheel down ``steps`` times."""
    from app._05_action.coordinates import game_to_screen
    import interception

    if steps <= 0:
        return
    u, v = _uv_xy(scroll_uv)
    sx, sy = game_to_screen(u, v, bounds)
    executor.mouse.move(sx, sy, snap=True)
    time.sleep(0.15)
    for _ in range(steps):
        interception.scroll("down")
        time.sleep(0.08)
    time.sleep(0.25)


def _active_map_id() -> str:
    from app._03_world.map_pack import get_active_map_pack

    pack = get_active_map_pack()
    return str(pack.id) if pack is not None else ""


def _shop_stop(executor, world, bounds) -> None:
    from app._03_world import ActionType
    from app._04_decision.types import ActionIntent

    stop = ActionIntent(
        action=ActionType.SHOP_STOP,
        priority=0.7,
        reason="practice stop at shop",
    )
    executor.execute(world, stop, bounds=bounds)


def _focus_game_for_practice(*, settle_s: float = 0.45) -> str:
    """Bring LC.exe to the foreground so Interception keys/clicks hit the game."""
    from manmabot_v1.probes import bring_game_to_front, probe_game

    game = probe_game()
    if not game.hwnd:
        raise RuntimeError(
            game.detail or "LC.exe window not found — start the game first"
        )
    bring_game_to_front(int(game.hwnd))
    time.sleep(settle_s)
    game = probe_game()
    if not game.hwnd:
        raise RuntimeError("LC.exe window disappeared while focusing")
    if not game.focused:
        # Retry once — UI click often steals focus on the first attempt.
        bring_game_to_front(int(game.hwnd))
        time.sleep(settle_s)
        game = probe_game()
    if game.focused:
        return "game focused"
    return "game bring-to-front attempted (focus still uncertain)"


def _scan_hotbars_for_practice(capture, executor, profile) -> str:
    """Memory hotbar read. Scan result alone drives spell_box."""
    from app._05_action.spell_box import configure_spell_box, slot_is_enabled
    from manmabot_v1.hotbar.inspect import HotbarInspectError, inspect_hotbars

    try:
        detected = inspect_hotbars()
    except HotbarInspectError as exc:
        raise RuntimeError(f"hotbar scan failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"hotbar scan failed: {exc}") from exc

    slots = dict(detected.spell_slots)
    configure_spell_box(slots)
    try:
        profile.spell_slots = slots
        profile.hotbar_layout = detected.to_profile_dict()
    except Exception:
        pass

    spec = slots.get("talking_scroll") or {}
    if slot_is_enabled("talking_scroll"):
        return (
            f"hotbar scan · talking_scroll enabled · "
            f"box{spec.get('box')}/{spec.get('key')}"
        )
    return "hotbar scan · talking_scroll not on bars"


def _fresh_content_bounds(capture):
    """Grab a frame so content_bounds match the live game window position."""
    from manmabot_v1.perception_capture import grab_perception_frame

    frame = grab_perception_frame(capture, retries=40, wait_s=0.05)
    if frame is None:
        return None, "no game frame — make sure LC.exe is visible"
    bounds = capture.content_bounds
    if bounds is None or not getattr(bounds, "valid", False):
        return None, "no content bounds from capture"
    return bounds, ""


def _open_talking_scroll_and_click(executor, dest, bounds, *, capture=None) -> str:
    """Press talking scroll, wait for the list UI, click the row."""
    from app._05_action import spell_box as sb
    from app._05_action.coordinates import game_to_screen
    from app._05_action import humanize as hz

    if not sb.slot_is_enabled("talking_scroll"):
        raise RuntimeError("talking_scroll slot is disabled in spell_box")
    if dest is None:
        raise RuntimeError("talking scroll destination UV is missing")

    box, key = sb.slot_press("talking_scroll")
    executor.select_skill_box(int(box), force=True)
    time.sleep(0.25)
    executor.keyboard.press(str(key))
    time.sleep(0.4)

    # Focus/restore can move the window; never click with pre-focus bounds.
    click_bounds = bounds
    if capture is not None:
        fresh, err = _fresh_content_bounds(capture)
        if fresh is None:
            raise RuntimeError(f"bounds refresh before scroll click failed: {err}")
        click_bounds = fresh

    x, y = game_to_screen(float(dest.x), float(dest.y), click_bounds)
    executor.mouse.move_and_click(x, y, snap=True)
    time.sleep(0.2)
    executor.select_skill_box(sb.START_BOX, force=True)
    # Teleport/land settle (same constant the live bot uses after a shop hop).
    time.sleep(hz.TALKING_SCROLL_SHOP_WAIT_S)
    return f"opened talking_scroll box{box}/{key} → clicked row"


def _esc_halt_brief(executor) -> None:
    """Esc to cancel post-scroll walk without the full 1s shop-arrive wait."""
    executor.keyboard.press("esc")
    time.sleep(0.25)


def _chebyshev_to_shop(origin, behavior) -> int:
    from app._03_world.world_coords import tile_chebyshev

    nav = _npc_nav(behavior)
    return int(tile_chebyshev(origin.x, origin.y, nav[0], nav[1]))


def _poll_near_shop(
    *,
    behavior,
    config: dict,
    origin,
    timeout_s: float,
) -> tuple[object | None, str]:
    """Wait for memory to report arrive-range (lets scroll auto-walk finish)."""
    cur = origin
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        if cur is not None and _near_shop(cur, behavior):
            return cur, "arrived"
        time.sleep(0.35)
        nxt, err = _player_world_origin(config)
        if nxt is None:
            return cur, f"memory lost ({err})"
        cur = nxt
    if cur is not None and _near_shop(cur, behavior):
        return cur, "arrived"
    return cur, "not yet in arrive tiles"


def _walk_nav_to_shop(
    *,
    behavior,
    config: dict,
    executor,
    bounds,
    origin,
    timeout_s: float = 45.0,
) -> tuple[object | None, str]:
    """Same-map walk using the bot's TRAVELING hop planner (not a raw click)."""
    from app._03_world.world import WorldState
    from app._04_decision.blackboard import Blackboard
    from app._04_decision.behaviors.travel import (
        clear_travel,
        emit_travel_hop,
        travel_arrived,
    )
    from app._04_decision.mode_control import begin_travel
    from app._04_decision.talking_scroll import PURPOSE_SHOP

    world = WorldState(frame_id=0, timestamp=0.0, player=None, objects={})
    bb = Blackboard()
    bb.world_origin = origin
    goal = _npc_nav(behavior)
    begin_travel(bb, goal, purpose=PURPOSE_SHOP, reason="practice walk to shop")

    deadline = time.perf_counter() + timeout_s
    cur = origin
    while time.perf_counter() < deadline:
        nxt, err = _player_world_origin(config)
        if nxt is None:
            clear_travel(bb)
            return None, f"while walking to shop: {err}"
        cur = nxt
        bb.world_origin = cur
        bb.tick_count = int(bb.tick_count) + 1

        if _near_shop(cur, behavior) or travel_arrived(bb):
            clear_travel(bb)
            _shop_stop(executor, world, bounds)
            return cur, "walked to shop (nav)"

        bb.intent = None
        if not emit_travel_hop(bb, reason="practice walk to shop", priority=0.7):
            if _near_shop(cur, behavior) or travel_arrived(bb):
                clear_travel(bb)
                _shop_stop(executor, world, bounds)
                return cur, "walked to shop (nav)"
            clear_travel(bb)
            return None, (
                f"nav unreachable — still not within arrive tiles of "
                f"npc [{behavior.npc_world_x},{behavior.npc_world_y}]"
            )

        intent = bb.intent
        if intent is not None:
            executor.execute(world, intent, bounds=bounds)
        time.sleep(0.25)

    clear_travel(bb)
    return None, (
        f"walk timeout — still not within arrive tiles of "
        f"npc [{behavior.npc_world_x},{behavior.npc_world_y}]"
    )


def _travel_to_shop(
    *,
    behavior,
    config: dict,
    profile,
    executor,
    bounds,
    origin,
    capture=None,
) -> tuple[object | None, str]:
    """Mirror bot ``shop_trip``: scroll when available, else same-map nav walk.

    After a talking scroll the game auto-walks toward the spot — do **not** Esc
    until arrive (or settle timeout). Live shop_trip now also waits for a real
    near-shop reading before NPC click (no fake arrive while nav is loading).
    """
    from app._04_decision.talking_scroll import (
        SCRATCH_SCROLL_ARRIVAL,
        SCRATCH_SCROLL_SPOT,
        apply_talking_scroll_arrival,
        click_uv_for_id,
        talking_scroll_available,
    )
    from app._04_decision.blackboard import Blackboard
    from app._03_world.world import WorldState

    dist = _chebyshev_to_shop(origin, behavior)
    if _near_shop(origin, behavior):
        return origin, f"already near shop (chebyshev={dist})"

    world = WorldState(frame_id=0, timestamp=0.0, player=None, objects={})
    same_map = _active_map_id() == str(behavior.map_id).strip()
    dest = click_uv_for_id(behavior.scroll_spot)
    can_scroll = talking_scroll_available() and dest is not None

    if can_scroll:
        try:
            # Re-assert focus before key presses (scan/UI can steal it).
            try:
                _focus_game_for_practice(settle_s=0.2)
            except Exception:
                pass
            open_note = _open_talking_scroll_and_click(
                executor, dest, bounds, capture=capture
            )
        except Exception as exc:
            return None, f"talking_scroll press failed: {exc}"

        bb = Blackboard()
        bb.scratch[SCRATCH_SCROLL_SPOT] = behavior.scroll_spot
        bb.scratch[SCRATCH_SCROLL_ARRIVAL] = True
        # Fast map-origin for shopping coords; full configure_navigation_for_map
        # runs in a background thread (same as live bot apply_talking_scroll_arrival).
        apply_talking_scroll_arrival(bb, config)

        settled, err = _player_world_origin(config)
        if settled is None:
            return None, f"{open_note} → {behavior.scroll_spot}, then {err}"

        _esc_halt_brief(executor)
        return settled, f"{open_note} → {behavior.scroll_spot}"

    if dest is None and talking_scroll_available():
        return (
            None,
            f"unknown scroll_spot {behavior.scroll_spot!r} "
            "(pick a valid talking-scroll row in Behaviors)",
        )

    if same_map:
        return _walk_nav_to_shop(
            behavior=behavior,
            config=config,
            executor=executor,
            bounds=bounds,
            origin=origin,
        )

    return (
        None,
        "not near shop, talking_scroll is not available, "
        "and character is on a different map — put talking scroll on the hotbar "
        f"(chebyshev={dist}, map={_active_map_id() or '?'})",
    )


def practice_calibrated_behavior(behavior_id: str) -> PracticeResult:
    """Travel to shop (talking scroll if needed), then run calibrated buy/sell UI."""
    from app._03_world.world import WorldState
    from app._04_decision.configure import apply_action_executor_options
    from app._04_decision.shops import SHOP_NPC_SEARCH_PX
    from app._05_action import humanize as hz
    from app._05_action.controller import ActionExecutor
    from app._05_action.cursor_verify import dialog_click_ring
    from app._05_action.coordinates import game_to_screen
    from manmabot_v1.perception_capture import (
        grab_perception_frame,
        open_perception_capture,
    )
    from manmabot_v1.shopping.behaviors import (
        behavior_by_id,
        load_behaviors,
        load_sell_filters,
    )
    from manmabot_v1.shopping.sell_slot_layout import load_sell_slot_layout

    behaviors = load_behaviors()
    behavior = behavior_by_id(behavior_id, behaviors)
    if behavior is None:
        return PracticeResult(ok=False, message=f"behavior not in userdata: {behavior_id!r}")

    ui = behavior.ui
    if behavior.action == "sell":
        if not ui.calibrated(action="sell"):
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior_id} needs sell_button + confirm UV "
                    "(Behaviors tab → Recapture → place markers → Save)"
                ),
            )
        if load_sell_slot_layout() is None:
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior_id}: calibrate Sell → Slot positions "
                    "(row_0..row_6) and Save layout first"
                ),
            )
    else:
        if not ui.calibrated(action="buy"):
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior_id} needs dialog UV calibration "
                    "(Behaviors tab → Recapture → place markers → Save)"
                ),
            )
        mode_uv = ui.buy_button
        if (
            mode_uv is None
            or ui.confirm_button is None
            or ui.list_scroll_point is None
        ):
            return PracticeResult(
                ok=False, message=f"{behavior_id}: missing buy/confirm/scroll UV"
            )
        row_i = behavior.visible_row_for_item()
        row_uv = ui.item_rows[row_i] if row_i < len(ui.item_rows) else None
        if row_uv is None:
            return PracticeResult(
                ok=False, message=f"{behavior_id}: item row {row_i} UV missing"
            )

    config, profile = _prepare_config_for_map(behavior.map_id)
    origin, err = _player_world_origin(config)
    if origin is None:
        return PracticeResult(ok=False, message=err)

    capture = open_perception_capture(config)
    try:
        frame = grab_perception_frame(capture, retries=40, wait_s=0.05)
        if frame is None:
            return PracticeResult(
                ok=False,
                message="no game frame — make sure LC.exe is visible",
            )
        bounds = capture.content_bounds
        if bounds is None or not getattr(bounds, "valid", False):
            return PracticeResult(ok=False, message="no content bounds from capture")

        humanize = bool(getattr(profile, "humanize", True))
        executor = ActionExecutor(enabled=True, humanize=humanize)
        apply_action_executor_options(executor)
        world = WorldState(frame_id=0, timestamp=0.0, player=None, objects={})

        try:
            focus_note = _focus_game_for_practice()
        except Exception as exc:
            return PracticeResult(ok=False, message=f"focus game failed: {exc}")

        try:
            hotbar_note = _scan_hotbars_for_practice(capture, executor, profile)
        except Exception as exc:
            return PracticeResult(ok=False, message=f"{exc} · {focus_note}")

        bounds, bounds_err = _fresh_content_bounds(capture)
        if bounds is None:
            return PracticeResult(
                ok=False,
                message=f"{bounds_err} · {hotbar_note} · {focus_note}",
            )

        origin, travel_note = _travel_to_shop(
            behavior=behavior,
            config=config,
            profile=profile,
            executor=executor,
            bounds=bounds,
            origin=origin,
            capture=capture,
        )
        if origin is None:
            return PracticeResult(
                ok=False,
                message=f"{travel_note} · {hotbar_note} · {focus_note}",
            )

        bounds, bounds_err = _fresh_content_bounds(capture)
        if bounds is None:
            return PracticeResult(ok=False, message=bounds_err or "no game frame after travel")

        prefix = f"{focus_note} · {hotbar_note} · {travel_note}"

        if behavior.action == "sell":
            return _practice_sell_loop(
                behavior=behavior,
                filters=load_sell_filters(),
                executor=executor,
                capture=capture,
                bounds=bounds,
                origin=origin,
                prefix=prefix,
            )

        # ---- buy (same NPC open the live bot now uses) ----
        from manmabot_v1.shopping.runtime import open_shop_npc

        if not open_shop_npc(executor, bounds, behavior, origin):
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior_id} failed after {prefix} — dialog cursor not found near NPC "
                    f"[{behavior.npc_world_x},{behavior.npc_world_y}]"
                ),
            )

        _click_uv(executor, bounds, ui.buy_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
        _scroll_list(
            executor,
            bounds,
            ui.list_scroll_point,
            behavior.scroll_steps_for_item(),
        )
        row_i = behavior.visible_row_for_item()
        row_uv = ui.item_rows[row_i]
        _click_uv(executor, bounds, row_uv, wait_s=hz.SHOP_BUTTON_WAIT_S)

        qty = max(1, min(999, int(behavior.default_qty)))
        executor.keyboard.tap("backspace", count=1)
        for digit in str(qty):
            executor.keyboard.press(digit)
        time.sleep(hz.SHOP_BUTTON_WAIT_S)

        _click_uv(executor, bounds, ui.confirm_button, wait_s=hz.SHOP_BUTTON_WAIT_S)

        return PracticeResult(
            ok=True,
            message=(
                f"{behavior_id} ok · {prefix} · buy · item_index={behavior.item_index} "
                f"(row {row_i}, scroll {behavior.scroll_steps_for_item()}) · qty={qty}"
            ),
        )
    finally:
        close = getattr(capture, "stop", None) or getattr(capture, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


_SELL_MAX_ITEMS = 80


def _sell_template_pool(matcher, *, sell_mode: str, garbage_list: tuple[str, ...]):
    """Item icons only; sell_only_garbage → garbage_list KR names only."""
    from manmabot_v1.shopping.behaviors import SELL_MODE_ONLY_GARBAGE

    if sell_mode == SELL_MODE_ONLY_GARBAGE:
        return matcher.item_templates(names=set(garbage_list))
    return matcher.item_templates()


def _sell_hit_center_uv(hit, slots, frame) -> tuple[float, float]:
    """Content UV for clicking a matched sell-slot hit."""
    key = hit.fkey or ""
    box = slots.get(key) or {}
    if "x0" in box and "x1" in box:
        cu = (float(box["x0"]) + float(box["x1"])) / 2.0
        cv = (float(box["y0"]) + float(box["y1"])) / 2.0
        return (cu, cv)
    fh, fw = frame.shape[:2]
    cu = (hit.x + hit.w / 2) / max(fw, 1)
    cv = (hit.y + hit.h / 2) / max(fh, 1)
    return (cu, cv)


def _practice_sell_loop(
    *,
    behavior,
    filters,
    executor,
    capture,
    bounds,
    origin,
    prefix: str,
) -> PracticeResult:
    """Sell all garbage: reopen shop each batch until the list is clear.

    One batch = open shop → Sell → select every match + qty → one Confirm
    (confirm closes the dialog). Then reopen and repeat until a match finds
    no garbage left.
    """
    from app._04_decision.shops import SHOP_NPC_SEARCH_PX
    from app._05_action import humanize as hz
    from app._05_action.cursor_verify import dialog_click_ring
    from app._05_action.coordinates import game_to_screen
    from manmabot_v1.hotbar.item_catalog import make_sell_icon_matcher
    from manmabot_v1.perception_capture import grab_perception_frame
    from manmabot_v1.shopping.behaviors import item_passes_sell_filter
    from manmabot_v1.shopping.sell_slot_layout import (
        SELL_SLOT_KEYS,
        load_sell_slot_layout,
    )

    ui = behavior.ui
    slots = load_sell_slot_layout()
    if slots is None:
        return PracticeResult(ok=False, message=f"{behavior.id}: sell slot layout missing")

    matcher = make_sell_icon_matcher()
    pool = _sell_template_pool(
        matcher,
        sell_mode=behavior.sell_mode,
        garbage_list=tuple(filters.garbage_list),
    )
    if not pool:
        return PracticeResult(
            ok=False,
            message=(
                f"{behavior.id}: no shopping_slots templates to match "
                f"(mode={behavior.sell_mode}, garbage={len(filters.garbage_list)}) — "
                "fill shopping_slots via Sell → Slot positions → Save slot crop"
            ),
        )

    qty = max(1, min(999, int(behavior.default_qty)))
    sold: list[str] = []
    qty_digits = str(qty)
    npc_uv = _npc_content_uv(behavior, origin)

    def _type_qty() -> None:
        executor.keyboard.tap("backspace", count=3)
        for digit in qty_digits:
            executor.keyboard.press(digit)
        time.sleep(hz.SHOP_BUTTON_WAIT_S)

    def _matching_hits(frame):
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

    def _open_sell_dialog(bounds_now) -> tuple[object | None, str | None]:
        """NPC dialog ring → Sell tab. Returns (bounds, error)."""
        if not dialog_click_ring(
            executor,
            npc_uv,
            lambda u, v: game_to_screen(u, v, bounds_now),
            radius_px=SHOP_NPC_SEARCH_PX,
            step_s=hz.SHOP_NPC_SEARCH_STEP_S,
        ):
            return None, (
                f"{behavior.id} failed after {prefix} — dialog cursor not found near NPC "
                f"[{behavior.npc_world_x},{behavior.npc_world_y}] "
                f"(sold {len(sold)})"
            )
        time.sleep(hz.SHOP_AFTER_NPC_WAIT_S)
        _click_uv(executor, bounds_now, ui.sell_button, wait_s=hz.SHOP_AFTER_TAB_WAIT_S)
        return bounds_now, None

    while len(sold) < _SELL_MAX_ITEMS:
        bounds_now, bounds_err = _fresh_content_bounds(capture)
        if bounds_now is None:
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior.id}: {bounds_err or 'no frame'} "
                    f"after {len(sold)} sold · {prefix}"
                ),
            )
        bounds = bounds_now

        # Confirm closes the shop — reopen every batch.
        _bounds, open_err = _open_sell_dialog(bounds)
        if open_err:
            return PracticeResult(ok=False, message=open_err)

        frame = grab_perception_frame(capture, retries=20, wait_s=0.05)
        if frame is None:
            try:
                executor.keyboard.press("escape")
            except Exception:
                pass
            return PracticeResult(
                ok=False,
                message=(
                    f"{behavior.id}: no frame while selling · sold {len(sold)} · {prefix}"
                ),
            )

        targets = _matching_hits(frame)
        if not targets:
            try:
                executor.keyboard.press("escape")
            except Exception:
                pass
            if not sold:
                return PracticeResult(
                    ok=True,
                    message=(
                        f"{behavior.id} ok · {prefix} · sell · nothing matched "
                        f"({behavior.sell_mode}, scanned {len(SELL_SLOT_KEYS)} slots)"
                    ),
                )
            return PracticeResult(
                ok=True,
                message=(
                    f"{behavior.id} ok · {prefix} · sell · sold {len(sold)} "
                    f"[{', '.join(sold)}] · no more garbage"
                ),
            )

        # Select each match + qty; one confirm (closes dialog).
        batch: list[str] = []
        for target in targets:
            if len(sold) + len(batch) >= _SELL_MAX_ITEMS:
                break
            key = target.fkey or SELL_SLOT_KEYS[0]
            cu, cv = _sell_hit_center_uv(target, slots, frame)
            _click_uv(executor, bounds, (cu, cv), wait_s=hz.SHOP_BUTTON_WAIT_S)
            _type_qty()
            batch.append(f"{key}:{target.kr_name}")

        if not batch:
            break

        _click_uv(executor, bounds, ui.confirm_button, wait_s=hz.SHOP_BUTTON_WAIT_S)
        sold.extend(batch)
        # Dialog is closed after confirm — next while iteration reopens.

    return PracticeResult(
        ok=False,
        message=(
            f"{behavior.id}: sell stopped at {_SELL_MAX_ITEMS} items "
            f"(sold {len(sold)}) · {prefix}"
        ),
    )


def wire_shopping_methods() -> None:
    return


wire_shopping_methods()
