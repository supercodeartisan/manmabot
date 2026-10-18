"""Drive a planned dungeon route with the live game character.

Reads MapSubsystem mapId and world xy through the existing monitor snapshot.
Walk clicks and floor-gate clicks go through the existing action executor.
This does not change hunt, combat, or HP decision code.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from dungeon.floor_route import (
    MapChoice,
    PickedPoint,
    RouteError,
    RouteSegment,
    _snap,
    _terrain_from_nav,
    choice_for_raw_map,
    plan_floor_route,
    save_route,
)

_ARRIVE = 2
_HOP_WAIT_S = 8.0
# A second timeout this close to the last replan is a stuck character, not a new teleport.
_JUMP_TILES = 6
# Snap-back onto a tile seen at least this long ago is lag, not a step.
_LAG_AGE_S = 1.0
_TRAIL_S = 15.0
# One hop is 3 tiles. A sample inside this is a step even if it leaves the polyline.
_STEP_TILES = 3
# Still on the route when within this many tiles of the planned path.
_ROUTE_SLACK = 2
# One unchanged sample is just a slow step. Sidestep only after standing this long.
_STILL_S = 1.5


class LiveError(Exception):
    """Live map read or in-game walk could not continue."""


class _Shift(Exception):
    """Character left the current hop. Replan from here to the final goal."""

    def __init__(self, pose: tuple[int, int, int]) -> None:
        self.pose = pose


class LiveRoute:
    """One game attachment for the patrol editor."""

    def __init__(self) -> None:
        self._ready = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.world = None
        self.sensors = None
        self.executor = None
        self.capture = None
        self.config: Optional[dict] = None
        self.blackboard = None
        self._terrains: dict[str, object] = {}
        self._anchor: Optional[tuple[int, int, int]] = None
        self._replan_pose: Optional[tuple[int, int, int]] = None
        self._trail: list[tuple[float, int, int, int]] = []
        self._last_nav: Optional[tuple[int, int]] = None
        self._blocked = False
        self._stuck_tile: Optional[tuple[int, int]] = None
        self._stuck_tried: set[tuple[int, int]] = set()
        self._expect_step: Optional[tuple[int, int]] = None
        self._progress = -1
        self._still_since: Optional[float] = None

    def stop(self) -> None:
        self._stop.set()

    def shutdown(self) -> None:
        self.stop()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._release()

    def read_start(self) -> PickedPoint:
        """Current character map and tile, snapped onto a walkable nav cell."""
        self._ensure()
        pose = self._pose(fresh=True)
        if pose is None:
            raise LiveError("게임에서 맵 번호와 좌표를 읽지 못했습니다. 게임이 켜져 있는지 확인하세요.")
        choice = choice_for_raw_map(pose[0])
        if choice is None:
            raise LiveError(f"mapId {pose[0]} 에 해당하는 맵 자료가 없습니다.")
        nav = _world_to_nav(choice, pose[1], pose[2])
        terrain = self._terrain(choice)
        snapped = _snap(terrain, nav) if terrain is not None else nav
        if snapped is None:
            raise LiveError("현재 칸 근처에 걸을 수 있는 타일이 없습니다.")
        return PickedPoint(choice=choice, nav_x=snapped[0], nav_y=snapped[1])

    def walk(
        self,
        segments: list[RouteSegment],
        *,
        on_status: Callable[[str], None],
        on_pose: Callable[[int, int, int], None],
        on_done: Callable[[bool, str], None],
        on_route: Callable[[list[RouteSegment]], None] | None = None,
    ) -> None:
        """Walk ``segments`` on a background thread. Callbacks run on that thread."""
        self.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._stop.clear()
        publish = on_route or (lambda _segments: None)

        def _run() -> None:
            try:
                self._ensure()
                self._walk(
                    segments,
                    on_status=on_status,
                    on_pose=on_pose,
                    on_route=publish,
                )
            except LiveError as exc:
                on_done(False, str(exc))
                return
            except Exception as exc:
                on_done(False, str(exc))
                return
            if self._stop.is_set():
                on_done(False, "이동을 멈췄습니다.")
                return
            on_done(True, "도착했습니다.")

        self._thread = threading.Thread(target=_run, name="dungeon-live-route", daemon=True)
        self._thread.start()

    def _walk(
        self,
        segments: list[RouteSegment],
        *,
        on_status: Callable[[str], None],
        on_pose: Callable[[int, int, int], None],
        on_route: Callable[[list[RouteSegment]], None],
    ) -> None:
        goal = _final_goal(segments)
        self._replan_pose = None
        while segments and not self._stop.is_set():
            try:
                self._follow(segments, on_status=on_status, on_pose=on_pose)
                return
            except _Shift as shift:
                if (
                    self._replan_pose is not None
                    and not _is_jump(self._replan_pose, shift.pose)
                ):
                    raise LiveError(
                        "같은 자리에서 다음 칸에 닿지 못했습니다. "
                        "텔레포트로 옮겨진 위치가 아닙니다."
                    )
                self._replan_pose = shift.pose
                on_status("새 위치에서 도착점까지 다시 계산")
                segments = self._replan(shift.pose, goal)
                on_route(segments)
                if segments:
                    try:
                        save_route(segments)
                    except Exception as exc:
                        on_status(f"다시 계산한 경로 저장 실패: {exc}")

    def _replan(
        self,
        pose: tuple[int, int, int],
        goal: PickedPoint,
    ) -> list[RouteSegment]:
        """Full route from the live tile to the original destination."""
        choice = choice_for_raw_map(pose[0])
        if choice is None:
            raise LiveError(f"mapId {pose[0]} 에 해당하는 맵 자료가 없습니다.")
        nav = _world_to_nav(choice, pose[1], pose[2])
        terrain = self._terrain(choice)
        snapped = _snap(terrain, nav) if terrain is not None else nav
        if snapped is None:
            raise LiveError("현재 칸 근처에 걸을 수 있는 타일이 없습니다.")
        if (
            choice.pack_id == goal.choice.pack_id
            and _chev(snapped, (goal.nav_x, goal.nav_y)) <= _ARRIVE
        ):
            return []
        start = PickedPoint(choice=choice, nav_x=snapped[0], nav_y=snapped[1])
        try:
            return plan_floor_route(start, goal)
        except RouteError as exc:
            raise LiveError(str(exc)) from exc

    def _follow(
        self,
        segments: list[RouteSegment],
        *,
        on_status: Callable[[str], None],
        on_pose: Callable[[int, int, int], None],
    ) -> None:
        self._anchor = None
        self._trail.clear()
        self._last_nav = None
        self._blocked = False
        self._stuck_tried.clear()
        self._expect_step = None
        self._progress = -1
        self._still_since = None
        for index, segment in enumerate(segments):
            if self._stop.is_set():
                return
            label = segment.choice.kr or segment.choice.pack_id
            on_status(f"{label} 이동")
            self._walk_clicks(segment, on_pose=on_pose, on_status=on_status)
            if index + 1 >= len(segments):
                return
            nxt = segments[index + 1]
            gate = segment.clicks[-1] if segment.clicks else None
            if gate is None or not nxt.choice.raw_map:
                raise LiveError("다음 층 입구 좌표가 없습니다.")
            land = nxt.path[0] if nxt.path else (nxt.clicks[0].nav_x, nxt.clicks[0].nav_y)
            on_status(f"{label} 입구 클릭")
            self._gate(
                entrance=(gate.world_x, gate.world_y),
                source_map=int(segment.choice.raw_map or -1),
                expect_map=int(nxt.choice.raw_map),
                expect_xy=_nav_to_world(nxt.choice, land[0], land[1]),
                choice=segment.choice,
                route=_route_tiles(segment),
                on_status=on_status,
                on_pose=on_pose,
            )
            self._anchor = None

    def _walk_clicks(
        self,
        segment: RouteSegment,
        *,
        on_pose: Callable[[int, int, int], None],
        on_status: Callable[[str], None],
    ) -> None:
        terrain = self._terrain(segment.choice)
        if terrain is None:
            raise LiveError(f"{segment.choice.pack_id} 지형을 열지 못했습니다.")
        route = _route_tiles(segment)
        expect_map = int(segment.choice.raw_map or -1)
        self._progress = -1
        for click in segment.clicks:
            deadline = time.time() + _HOP_WAIT_S
            goal = (click.nav_x, click.nav_y)
            origin_pose: Optional[tuple[int, int, int]] = None
            self._blocked = False
            self._stuck_tried.clear()
            while not self._stop.is_set():
                # fresh=True reads monitor xy. print_state lags after a teleport
                # and used to hide the jump until the hop timer gave up.
                pose = self._pose(fresh=True)
                if pose is None:
                    raise LiveError("이동 중 좌표를 잃었습니다.")
                on_pose(pose[0], pose[1], pose[2])
                kind = self._move_kind(
                    pose,
                    expect_map=expect_map,
                    choice=segment.choice,
                    route=route,
                )
                self._anchor = pose
                self._remember(pose)
                if kind == "lag":
                    deadline = time.time() + _HOP_WAIT_S
                    origin_pose = pose
                    on_status("제자리로 돌아와 같은 경로를 계속")
                elif kind == "teleport":
                    raise _Shift(pose)
                here = _world_to_nav(segment.choice, pose[1], pose[2])
                if origin_pose is None:
                    origin_pose = pose
                now = time.monotonic()
                if self._last_nav is not None and here == self._last_nav:
                    if self._still_since is None:
                        self._still_since = now
                    if now - self._still_since >= _STILL_S:
                        self._blocked = True
                elif self._last_nav is not None:
                    self._still_since = None
                    self._blocked = False
                    self._stuck_tried.clear()
                    self._expect_step = None
                self._last_nav = here
                near = _nearest_index(segment.path, here, _ROUTE_SLACK + 1)
                if near is not None and near > self._progress:
                    self._progress = near
                click_i = _first_index(segment.path, goal)
                passed = click_i is not None and click_i < self._progress
                if _chev(here, goal) <= _ARRIVE or passed:
                    break
                if time.time() > deadline:
                    stood = _world_chev(origin_pose, pose) == 0
                    if stood or _near_route(here, route, _ROUTE_SLACK):
                        deadline = time.time() + _HOP_WAIT_S
                        origin_pose = pose
                        if stood:
                            self._blocked = True
                            on_status("막혀 있어 다음 중간점으로 계속 이동")
                        else:
                            on_status("다음 중간점으로 계속 이동")
                    else:
                        raise _Shift(pose)
                if self._blocked:
                    moved = self._step_around(terrain, here, goal)
                else:
                    moved = self._click_toward(terrain, here, goal)
                if not moved:
                    raise LiveError("다음 클릭 칸으로 길이 없습니다.")
                time.sleep(0.45)

    def _click_toward(self, terrain, here: tuple[int, int], goal: tuple[int, int]) -> bool:
        from app._02_state import ActionType
        from app._02_state.geometry import WorldOrigin
        from app._04_decision.dungeon import dungeon_max_hop_tiles
        from app._04_decision.pathfinding import (
            find_path,
            select_click_waypoint,
            waypoint_to_content,
        )
        from app._04_decision.types import ActionIntent

        origin = WorldOrigin(int(here[0]), int(here[1]))
        path = find_path(terrain, here, goal)
        if len(path) < 2:
            return _chev(here, goal) <= _ARRIVE
        picked = select_click_waypoint(
            path,
            origin,
            terrain=terrain,
            max_hop=dungeon_max_hop_tiles(),
        )
        if picked is None:
            return False
        dest = waypoint_to_content((int(picked[0]), int(picked[1])), origin)
        self._act(
            ActionIntent(
                action=ActionType.TRAVELING,
                destination=dest,
                priority=0.5,
                reason="dungeon floor route",
            )
        )
        return True

    def _step_around(self, terrain, here: tuple[int, int], goal: tuple[int, int]) -> bool:
        """Click a free neighbor when the forward hop leaves the character still."""
        if self._stuck_tile != here:
            self._stuck_tile = here
            self._stuck_tried.clear()
        hx, hy = int(here[0]), int(here[1])
        ranked: list[tuple[int, int, tuple[int, int]]] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                tile = (hx + dx, hy + dy)
                if tile in self._stuck_tried:
                    continue
                if not terrain.is_walkable(tile[0], tile[1]):
                    continue
                ranked.append((_chev(tile, goal), abs(dx) + abs(dy), tile))
        ranked.sort()
        for _dist, _diag, tile in ranked:
            self._stuck_tried.add(tile)
            self._expect_step = tile
            if self._click_toward(terrain, here, tile):
                return True
            self._expect_step = None
        self._stuck_tried.clear()
        return self._click_toward(terrain, here, goal)

    def _gate(
        self,
        *,
        entrance: tuple[int, int],
        source_map: int,
        expect_map: int,
        expect_xy: tuple[int, int],
        choice: MapChoice,
        route: set[tuple[int, int]],
        on_status: Callable[[str], None],
        on_pose: Callable[[int, int, int], None],
    ) -> None:
        shifted: list[tuple[int, int, int]] = []
        from app._04_decision.world_nav.gate import run_gate_click

        pose = self._pose(fresh=True)
        if pose is None:
            raise LiveError("입구 클릭 전에 좌표를 읽지 못했습니다.")
        _status, _rect, bounds = self._bounds()
        if bounds is None or not getattr(bounds, "valid", False):
            raise LiveError("게임 창을 찾지 못했습니다.")

        def _read(fresh: bool) -> Optional[tuple[int, int, int]]:
            live = self._pose(fresh=fresh)
            if live is None:
                return None
            on_pose(live[0], live[1], live[2])
            if live[0] == expect_map:
                return live
            kind = self._move_kind(
                live,
                expect_map=source_map,
                choice=choice,
                route=route,
            )
            self._anchor = live
            self._remember(live)
            if kind == "teleport":
                shifted.append(live)
            return live

        ok, detail = run_gate_click(
            actions=self.executor,
            bounds=bounds,
            entrance_abs=entrance,
            pose_abs=(pose[1], pose[2]),
            expect_map_id=expect_map,
            expect_xy=expect_xy,
            read_pose=lambda: _read(False),
            read_pose_fresh=lambda: _read(True),
            stop=lambda: self._stop.is_set() or bool(shifted),
            log=on_status,
        )
        if shifted:
            raise _Shift(shifted[-1])
        if not ok:
            raise LiveError(detail)

    def _move_kind(
        self,
        pose: tuple[int, int, int],
        *,
        expect_map: int,
        choice: MapChoice,
        route: set[tuple[int, int]],
    ) -> str:
        """``ok`` keeps the hop, ``lag`` resets its timer, ``teleport`` replans."""
        prev = self._anchor
        if prev is None:
            return "ok"
        if pose[0] != expect_map or pose[0] != prev[0]:
            return "teleport"
        step = _world_chev(prev, pose)
        if step == 0:
            return "ok"
        nav = _world_to_nav(choice, pose[1], pose[2])
        # A smooth step stays on this route. One tile beside the polyline is
        # still that walk, and must not rebuild the path behind the character.
        if step <= _STEP_TILES or _near_route(nav, route, _ROUTE_SLACK) or nav == self._expect_step:
            return "ok"
        if self._is_return(pose):
            return "lag"
        return "teleport"

    def _remember(self, pose: tuple[int, int, int]) -> None:
        now = time.monotonic()
        self._trail.append((now, pose[0], pose[1], pose[2]))
        cutoff = now - _TRAIL_S
        if self._trail and self._trail[0][0] < cutoff:
            self._trail = [item for item in self._trail if item[0] >= cutoff]

    def _is_return(self, pose: tuple[int, int, int]) -> bool:
        """True when this sample lands on a tile already walked a moment ago."""
        now = time.monotonic()
        for stamp, map_id, x, y in self._trail:
            if now - stamp < _LAG_AGE_S or map_id != pose[0]:
                continue
            if max(abs(x - pose[1]), abs(y - pose[2])) <= 1:
                return True
        return False

    def _pose(self, *, fresh: bool) -> Optional[tuple[int, int, int]]:
        from app._04_decision.world_nav.session import live_pose_from_state

        self._capture()
        pose = live_pose_from_state(self.world, fresh=fresh)
        if pose is None:
            return None
        return int(pose.map_id), int(pose.x), int(pose.y)

    def _capture(self) -> None:
        from app._03_world.merge.apply_perception import apply_perception_buffer
        from app._04_decision.live_map_pack import ensure_navigation_for_live_map_id

        status, rect, _bounds = self._bounds()
        if status != "ok" or rect is None:
            raise LiveError("게임 창을 찾지 못했습니다.")
        buffer = self.sensors.capture_tick()
        applied = apply_perception_buffer(
            self.world,
            self.blackboard,
            buffer,
            content=rect,
        )
        if applied.live_map_id is not None and self.config is not None:
            ensure_navigation_for_live_map_id(
                self.blackboard,
                self.config,
                int(applied.live_map_id),
                snapshot=applied.live_map_snap,
            )

    def _bounds(self):
        capture = self.capture
        if capture is None:
            return "no_window", None, None
        status = capture.refresh_click_bounds()
        return status, capture.content_rect, capture.content_bounds

    def _act(self, intent) -> None:
        status, _rect, bounds = self._bounds()
        if status != "ok" or bounds is None or not getattr(bounds, "valid", False):
            raise LiveError("게임 창을 찾지 못했습니다.")
        self.executor.execute(self.world, intent, bounds=bounds)

    def _terrain(self, choice: MapChoice):
        cached = self._terrains.get(choice.pack_id)
        if cached is None:
            cached = _terrain_from_nav(choice.nav_path, choice.pixel_scale)
            self._terrains[choice.pack_id] = cached
        return cached

    def _ensure(self) -> None:
        if self._ready and self.sensors is not None and self.world is not None:
            return
        self._boot()
        self._ready = True

    def _boot(self) -> None:
        from tool.utils import load_config
        from settings.profile import load_profile
        from app._02_state import CharacterType
        from app._03_world.merge.track import create_game_state
        from app._04_decision.blackboard import Blackboard
        from app._04_decision.configure import (
            apply_action_executor_options,
            configure_action,
            configure_decision,
        )
        from app._04_decision.nav_config import configure_navigation
        from app._05_action.controller import ActionExecutor
        from app._01_perception.sensors import PerceptionSensors, set_shared_sensors
        from session.perception_capture import open_perception_capture

        profile = load_profile()
        config = load_config()
        if not isinstance(config, dict):
            config = {}
        configure_decision(config)
        configure_action(config)
        configure_navigation(config)
        try:
            character = CharacterType(str(profile.character or "mage").strip().lower())
        except ValueError:
            character = CharacterType.MAGE
        world = create_game_state(character)
        blackboard = Blackboard()
        sensors = PerceptionSensors(config)
        set_shared_sensors(sensors)
        capture = open_perception_capture(config)
        executor = ActionExecutor(
            enabled=True,
            character=character,
            humanize=bool(getattr(profile, "humanize", True)),
            humanize_move=bool(getattr(profile, "humanize_move", True)),
        )
        apply_action_executor_options(executor)
        try:
            from app._05_action.mouse import prepare_capture

            prepare_capture()
        except Exception:
            pass
        self.config = config
        self.world = world
        self.blackboard = blackboard
        self.sensors = sensors
        self.capture = capture
        self.executor = executor

    def _release(self) -> None:
        try:
            from app._05_action.mouse import release_capture

            release_capture()
        except Exception:
            pass
        try:
            from app._01_perception.sensors import clear_shared_sensors

            clear_shared_sensors()
        except Exception:
            pass
        self.capture = None
        self.sensors = None
        self.executor = None
        self._ready = False


def _world_to_nav(choice: MapChoice, world_x: int, world_y: int) -> tuple[int, int]:
    scale = max(1, choice.pixel_scale)
    return (
        int(world_x - choice.origin_x) // scale,
        int(world_y - choice.origin_y) // scale,
    )


def _nav_to_world(choice: MapChoice, nav_x: int, nav_y: int) -> tuple[int, int]:
    scale = max(1, choice.pixel_scale)
    return (
        choice.origin_x + int(nav_x) * scale,
        choice.origin_y + int(nav_y) * scale,
    )


def _chev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def _world_chev(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(int(a[1]) - int(b[1])), abs(int(a[2]) - int(b[2])))


def _nearest_index(
    path: list[tuple[int, int]],
    tile: tuple[int, int],
    slack: int,
) -> Optional[int]:
    best_i: Optional[int] = None
    best_d: Optional[int] = None
    for index, point in enumerate(path):
        dist = _chev((int(point[0]), int(point[1])), tile)
        if dist > slack:
            continue
        if best_d is None or dist < best_d:
            best_d = dist
            best_i = index
    return best_i


def _first_index(
    path: list[tuple[int, int]],
    tile: tuple[int, int],
) -> Optional[int]:
    for index, point in enumerate(path):
        if (int(point[0]), int(point[1])) == (int(tile[0]), int(tile[1])):
            return index
    return None


def _near_route(
    tile: tuple[int, int],
    route: set[tuple[int, int]],
    slack: int,
) -> bool:
    tx, ty = int(tile[0]), int(tile[1])
    for x, y in route:
        if max(abs(x - tx), abs(y - ty)) <= slack:
            return True
    return False


def _route_tiles(segment: RouteSegment) -> set[tuple[int, int]]:
    tiles = {(int(x), int(y)) for x, y in segment.path}
    for click in segment.clicks:
        tiles.add((int(click.nav_x), int(click.nav_y)))
    return tiles


def _is_jump(prev: tuple[int, int, int], pose: tuple[int, int, int]) -> bool:
    if prev[0] != pose[0]:
        return True
    return _world_chev(prev, pose) > _JUMP_TILES


def _final_goal(segments: list[RouteSegment]) -> PickedPoint:
    last = segments[-1]
    if last.clicks:
        click = last.clicks[-1]
        return PickedPoint(choice=last.choice, nav_x=click.nav_x, nav_y=click.nav_y)
    tile = last.path[-1]
    return PickedPoint(choice=last.choice, nav_x=tile[0], nav_y=tile[1])
