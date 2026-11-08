"""Walk to an absolute world tile using Engine travel hops (no reimplementation)."""
from __future__ import annotations

import time
from typing import Callable, Optional

from app._02_state.gamestate import GameState
from app._03_world.merge.apply_perception import apply_perception_buffer
from app._03_world.merge.memory_sync import game_to_nav
from app._03_world.merge.track import create_game_state
from app._04_decision.blackboard import Blackboard
from app._04_decision.behaviors.travel import (
    clear_travel,
    emit_travel_hop,
    travel_arrived,
)
from app._04_decision.mode_control import begin_travel
from app._04_decision.nav_config import get_terrain_map
from app._05_action.controller import ActionExecutor
from app._05_action.window_bounds import get_client_bounds, find_game_window
from app._01_perception.sensors import PerceptionSensors


LogFn = Callable[[str], None]
CancelFn = Callable[[], bool]

GAME_PROCESS = "LC.exe"
PURPOSE_SUPPLY = "supply"


def _ensure_nav(world: GameState, blackboard: Blackboard, log: Optional[LogFn]) -> bool:
    """Load the map pack for the live mapId (same path as the bot worker).

    Returns True when a terrain map is available for hops.
    """
    try:
        from tool.utils import load_config
        from app._03_world.merge.memory_sync import player_map_id_from_snapshot
        from app._04_decision.live_map_pack import ensure_navigation_for_live_map_id

        snap = getattr(world, "last_memory_snapshot", None)
        if not isinstance(snap, dict):
            snap = getattr(world, "last_print_state", None)
        mid = player_map_id_from_snapshot(snap) if isinstance(snap, dict) else None
        if mid is None:
            if log:
                log("nav pack skip: live mapId unavailable (MapSubsystem)")
            return get_terrain_map() is not None
        cfg = load_config() if callable(load_config) else {}
        ok, msg = ensure_navigation_for_live_map_id(
            blackboard,
            cfg if isinstance(cfg, dict) else {},
            int(mid),
            snapshot=snap if isinstance(snap, dict) else None,
        )
        if log and msg:
            log(f"nav: {msg}" if ok else f"nav fail: {msg}")
        # Pack load changes map_origin — restamp pose in the new frame.
        _sync_origin(world, blackboard)
        return get_terrain_map() is not None
    except Exception as exc:
        if log:
            log(f"nav pack skip: {exc}")
        return get_terrain_map() is not None


def _sync_origin(world: GameState, blackboard: Blackboard) -> bool:
    """Stamp nav origin from monitor ``pos`` or print_state ``x/y`` (Engine helper)."""
    from app._03_world.merge.memory_sync import world_origin_from_snapshot

    for snap in (
        getattr(world, "last_memory_snapshot", None),
        getattr(world, "last_print_state", None),
    ):
        if not isinstance(snap, dict):
            continue
        wo = world_origin_from_snapshot(snap)
        if wo is not None:
            blackboard.world_origin = wo
            return True
    return False


def walk_to_tile(
    goal: tuple[int, int],
    *,
    sensors: Optional[PerceptionSensors] = None,
    timeout_s: float = 120.0,
    log: Optional[LogFn] = None,
    cancel: Optional[CancelFn] = None,
) -> bool:
    """Navigate to absolute nav tile with project ``emit_travel_hop`` + ActionExecutor."""
    def _log(msg: str) -> None:
        if log:
            log(msg)

    def _cancel() -> bool:
        return bool(cancel and cancel())

    if sensors is None:
        from app._01_perception.sensors import shared_sensors

        sense = shared_sensors()
    else:
        sense = sensors
    world = create_game_state()
    board = Blackboard()
    board.reset()
    hwnd = find_game_window(GAME_PROCESS)
    if hwnd is None:
        _log("game window not found")
        return False
    bounds = get_client_bounds(int(hwnd))
    if bounds is None or not bounds.valid:
        _log("client bounds invalid")
        return False
    executor = ActionExecutor()

    pose_deadline = time.time() + 3.0
    while True:
        if _cancel():
            _log("walk cancelled (stop) during pose wait")
            return False
        buf = sense.capture_field()
        apply_perception_buffer(world, board, buf)
        if _sync_origin(world, board):
            break
        if time.time() >= pose_deadline:
            _log("player pose unavailable")
            return False
        time.sleep(0.15)

    if not _ensure_nav(world, board, _log):
        _log("walk abort: no terrain map (nav pack not loaded)")
        return False

    # GUI / callers may pass raw LC world (~32k) or nav tiles; Engine expects nav.
    raw_g = (int(goal[0]), int(goal[1]))
    gx, gy = game_to_nav(raw_g[0], raw_g[1])
    if (gx, gy) != raw_g:
        _log(f"goal game {raw_g} -> nav ({gx},{gy})")
    begin_travel(board, (gx, gy), purpose=PURPOSE_SUPPLY, reason="supply walk")
    _log(
        f"walk start -> ({gx},{gy}) from "
        f"({board.world_origin.x},{board.world_origin.y})"
    )

    deadline = time.time() + max(1.0, float(timeout_s))
    last_miss = ""
    miss_streak = 0
    try:
        while time.time() < deadline:
            if _cancel():
                _log("walk cancelled (stop)")
                return False
            buf = sense.capture_field()
            apply_perception_buffer(world, board, buf)
            if not _sync_origin(world, board):
                time.sleep(0.1)
                continue
            _ensure_nav(world, board, None)
            if get_terrain_map() is None:
                _log("walk abort: terrain map cleared")
                return False
            board.tick_count += 1
            if travel_arrived(board):
                _log("walk arrived")
                return True
            board.intent = None
            ok = emit_travel_hop(
                board,
                reason="supply hop",
                priority=1.0,
                state=world,
            )
            intent = board.intent
            if intent is not None:
                miss_streak = 0
                hwnd = find_game_window(GAME_PROCESS)
                if hwnd is not None:
                    fresh = get_client_bounds(int(hwnd))
                    if fresh is not None and fresh.valid:
                        bounds = fresh
                executor.execute(world, intent, bounds=bounds, blackboard=board)
            elif not ok and travel_arrived(board):
                _log("walk arrived")
                return True
            else:
                miss = str(board.scratch.get("travel_hop_miss") or "no_intent")
                if miss != last_miss:
                    _log(
                        f"hop miss={miss} at "
                        f"({board.world_origin.x},{board.world_origin.y}) "
                        f"-> ({gx},{gy})"
                    )
                    last_miss = miss
                miss_streak += 1
                # Hard failures that will never recover without a pack/path change.
                if miss in ("no_terrain", "no_nav_goal"):
                    _log(f"walk abort: {miss}")
                    return False
                if miss_streak >= 40 and miss in ("no_path", "no_path_enter_farm"):
                    _log(f"walk abort: repeated {miss}")
                    return False
                time.sleep(0.15)
        _log(
            f"walk timeout at ({board.world_origin.x},{board.world_origin.y}) "
            f"goal=({gx},{gy}) last_miss={last_miss or '-'}"
        )
        return False
    finally:
        clear_travel(board)
