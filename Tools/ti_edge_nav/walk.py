"""Real ground clicks via imported ActionExecutor. Edge hop planner is tool-local."""
from __future__ import annotations

import threading
import time

from app._03_world.space.world_coords import WorldOrigin, tile_chebyshev
from app._04_decision.pathfinding import waypoint_to_content

from ti_edge_nav.hop import EdgeHopPlan, line_still_clear, plan_edge_hop
from ti_edge_nav.layers import EdgeLayers


class EdgeWalk:
    """Walk the game character to a goal, one edge-aware avoidance click at a time."""

    def __init__(self, reader) -> None:
        self.reader = reader
        self.layers: EdgeLayers | None = None
        self.graph = None
        self.goal: tuple[int, int] | None = None
        self.hop = 5
        self.pins: set[tuple[int, int]] = set()
        self.running = False
        self.message = ""
        self.plan: EdgeHopPlan | None = None
        self._ui_lock = threading.Lock()
        self._clicks: list[tuple[float, float, float]] = []
        self._stop = threading.Event()
        self._go = threading.Event()
        self._executor = None
        self._capture = None
        self._await_focus = False
        self._thread = threading.Thread(target=self._loop, name="ti-edge-walk", daemon=True)
        self._thread.start()

    def update(self, layers, graph, goal, hop, pins) -> None:
        self.layers = layers
        self.graph = graph
        self.goal = None if goal is None else (int(goal[0]), int(goal[1]))
        self.hop = int(hop)
        self.pins = set(pins)

    def start(self) -> None:
        self._await_focus = True
        self.running = True
        self._go.set()

    def stop(self) -> None:
        self._go.clear()
        self.running = False

    def close(self) -> None:
        self._stop.set()
        self.stop()
        if self._executor is not None:
            try:
                self._executor.drop_mouse()
            except Exception:
                pass
        try:
            from app._05_action.mouse import release_capture

            release_capture()
        except Exception:
            pass
        self._executor = None
        self._capture = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self._go.wait(0.2):
                continue
            try:
                self._ensure_click()
            except Exception as exc:
                self.message = f"input not ready: {exc}"
                self.running = False
                self._go.clear()
                continue
            if self._await_focus:
                self._await_focus = False
                if not self._go.is_set():
                    continue
                if not self._wait_until_focused():
                    self.message = "game did not take focus"
                    self.stop()
                    continue
            if self._focus_lost():
                continue
            if not self._step():
                self.running = False
                self._go.clear()
        self.running = False

    def _step(self) -> bool:
        layers = self.layers
        graph = self.graph
        goal = self.goal
        view = self.reader.latest()
        player = view.world_tile()
        if not self._go.is_set():
            return False
        if layers is None or graph is None or goal is None:
            self.message = "click an end point"
            time.sleep(0.2)
            return self._go.is_set()
        if player is None:
            self.message = "waiting for the character"
            time.sleep(0.2)
            return self._go.is_set()
        if tile_chebyshev(player[0], player[1], goal[0], goal[1]) <= 1:
            self.message = f"arrived {goal}"
            self.plan = None
            return False
        bodies = {body.world_tile() for body in view.bodies}
        bodies.update(self.pins)
        try:
            plan = plan_edge_hop(layers, graph, player, goal, bodies, max_hop=self.hop)
        except Exception as exc:
            self.message = f"plan failed: {exc}"
            time.sleep(0.3)
            return self._go.is_set()
        self.plan = plan
        if plan.click is None:
            self.message = plan.note or "no click"
            time.sleep(0.4)
            return self._go.is_set()
        self.message = f"walking to {plan.click}  ({plan.note})"
        ok, detail = self._click(player, plan.click)
        if not ok:
            self.message = detail
            if not self._go.is_set():
                return False
            time.sleep(0.3)
            return self._go.is_set()
        return self._wait_hop(layers, plan.click, goal)

    def _wait_hop(self, layers: EdgeLayers, click: tuple[int, int], goal: tuple[int, int]) -> bool:
        deadline = time.time() + 2.0
        next_click = time.monotonic() + 0.1
        while time.time() < deadline and self._go.is_set():
            if self._focus_lost():
                return False
            if self.goal != goal:
                return True
            view = self.reader.latest()
            player = view.world_tile()
            if player is None:
                time.sleep(0.1)
                continue
            if tile_chebyshev(player[0], player[1], goal[0], goal[1]) <= 1:
                self.message = f"arrived {goal}"
                return False
            if tile_chebyshev(player[0], player[1], click[0], click[1]) <= 1:
                return True
            bodies = {body.world_tile() for body in view.bodies}
            bodies.update(self.pins)
            if not line_still_clear(layers, player, click, bodies):
                self.message = "body entered the line, replanning"
                return True
            moving = self._body_moving()
            if moving is False and time.monotonic() >= next_click:
                ok, detail = self._click(player, click)
                next_click = time.monotonic() + 0.1
                if not ok:
                    self.message = detail
                    if not self._go.is_set():
                        return False
            time.sleep(0.1)
        return self._go.is_set()

    def _body_moving(self) -> bool | None:
        from app._05_action.body_pose import MOVE_VFTS, read_action

        try:
            body, _cmd = read_action()
        except Exception:
            return None
        if body is None:
            return None
        return body in MOVE_VFTS

    def _ensure_click(self) -> None:
        if self._executor is not None and self._capture is not None:
            return
        from app._02_state import CharacterType
        from app._05_action.controller import ActionExecutor
        from app._05_action.mouse import prepare_capture
        from session.perception_capture import open_perception_capture

        prepare_capture()
        self._capture = open_perception_capture()
        self._executor = ActionExecutor(
            enabled=True,
            character=CharacterType.ELF,
            humanize=True,
            humanize_move=True,
        )

    def _click(self, player: tuple[int, int], tile: tuple[int, int]) -> tuple[bool, str]:
        from app._02_state import ActionType
        from app._04_decision.types import ActionIntent

        capture = self._capture
        executor = self._executor
        if capture is None or executor is None:
            return False, "input not ready"
        status = capture.refresh_click_bounds()
        bounds = capture.content_bounds
        if status != "ok" or bounds is None or not getattr(bounds, "valid", False):
            return False, "game window not found"
        if self._focus_lost():
            return False, self.message
        dest = waypoint_to_content(tile, WorldOrigin(x=int(player[0]), y=int(player[1])))
        intent = ActionIntent(
            action=ActionType.TRAVELING,
            destination=dest,
            priority=0.4,
            reason="ti edge nav walk",
        )
        executor.last_travel_click_failed = False
        executor.last_cursor_reject_reason = None
        try:
            executor._search(intent, bounds)
        except Exception as exc:
            return False, f"click failed: {exc}"
        if executor.last_travel_click_failed:
            reason = str(executor.last_cursor_reject_reason or "cursor rejected the ground click")
            return False, reason
        self._note_click(tile)
        return True, "clicked"

    def _game_hwnd(self) -> int:
        capture = self._capture
        tracker = getattr(capture, "_tracker", None) if capture is not None else None
        if tracker is not None:
            hwnd = tracker.live_hwnd()
            if hwnd:
                return int(hwnd)
        from app._05_action.window_bounds import find_game_window

        return int(find_game_window("LC.exe") or 0)

    def _game_focused(self) -> bool:
        from session.probes import _is_game_focused

        hwnd = self._game_hwnd()
        return bool(hwnd) and _is_game_focused(hwnd)

    def _wait_until_focused(self, timeout: float = 0.6) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and self._go.is_set():
            if self._game_focused():
                return True
            time.sleep(0.05)
        return self._game_focused()

    def _focus_lost(self) -> bool:
        if not self._go.is_set():
            return True
        if self._game_focused():
            return False
        self.message = "stopped: game lost focus"
        self.stop()
        return True

    def _note_click(self, tile: tuple[int, int]) -> None:
        now = time.monotonic()
        with self._ui_lock:
            self._clicks = [row for row in self._clicks if now - row[2] < 0.5]
            self._clicks.append((float(tile[0]), float(tile[1]), now))

    def marks(self, now: float | None = None) -> list[tuple[float, float, float]]:
        now = time.monotonic() if now is None else now
        with self._ui_lock:
            return [row for row in self._clicks if now - row[2] < 0.5]
