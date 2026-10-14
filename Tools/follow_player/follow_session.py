"""Live loop: read nearby players, hop toward one, shoot and loot when close.

Does not call the schedule decide loop and does not patch shared movement,
combat, or HP functions. Clicks go through the existing action executor.
"""
from __future__ import annotations

import random
import threading
import time
import traceback
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from follow_player.follow_logic import (
    action_kind,
    choose_approach_tile,
    guid_key,
    strike_hits,
    within_chebyshev,
)


@dataclass
class FollowParams:
    follow_tiles: int = 9
    approach_tiles: int = 2
    attack_tiles: int = 7
    poll_s: float = 0.5
    target_ent: str = ""
    target_name: str = ""
    target_track_id: Optional[int] = None

    def clamped(self) -> "FollowParams":
        return FollowParams(
            follow_tiles=max(1, min(40, int(self.follow_tiles))),
            approach_tiles=max(1, min(8, int(self.approach_tiles))),
            attack_tiles=max(1, min(40, int(self.attack_tiles))),
            poll_s=max(0.2, min(5.0, float(self.poll_s))),
            target_ent=str(self.target_ent or ""),
            target_name=str(self.target_name or ""),
            target_track_id=self.target_track_id,
        )


def _player_key(obj: Any) -> str:
    ent = str(getattr(obj, "memory_ent", None) or "").strip()
    if ent:
        return ent
    return f"tid:{int(getattr(obj, 'track_id', 0) or 0)}"


def _player_name(obj: Any) -> str:
    identity = getattr(obj, "identity", None)
    name = str(getattr(identity, "name", None) or "").strip()
    if not name:
        name = str(getattr(obj, "species_name", None) or "").strip()
    return name or "(이름 없음)"


class FollowSession:
    """One game session. The GUI reads and writes params while this runs."""

    def __init__(
        self,
        *,
        on_status: Callable[[str], None],
        on_players: Callable[[list[dict[str, Any]]], None],
        on_log: Callable[[str], None],
        on_running: Callable[[bool, bool], None],
    ) -> None:
        self._on_status = on_status
        self._on_players = on_players
        self._on_log = on_log
        self._on_running = on_running
        self._lock = threading.Lock()
        self._params = FollowParams()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._refresh = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rng = random.Random()
        self._goal: Optional[tuple[int, int]] = None
        self._goal_for = ""
        self._last_follow_at = 0.0
        self._last_loot_hop_at = 0.0
        self._loot_stand: Optional[tuple[int, int]] = None
        self._runtime_ready = False
        # Re-entrant: a stopped-state refresh holds this across boot.
        self._busy = threading.RLock()
        self.sensors: Any = None
        self.capture: Any = None
        self.executor: Any = None
        self.world: Any = None
        self.blackboard: Any = None
        self.config: dict[str, Any] = {}
        self.loot_mode = "all_items"
        self._mouse_up = False

    def set_params(self, params: FollowParams) -> None:
        """Replace the live knobs. Safe to call from the GUI thread."""
        nxt = params.clamped()
        with self._lock:
            prev_ent = self._params.target_ent
            self._params = nxt
        if nxt.target_ent != prev_ent:
            self._goal = None
            self._goal_for = ""
            self._loot_stand = None
            self._last_loot_hop_at = 0.0

    def snapshot_params(self) -> FollowParams:
        with self._lock:
            return replace(self._params)

    def has_target(self) -> bool:
        return bool(self.snapshot_params().target_ent)

    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def paused(self) -> bool:
        return self._pause.is_set()

    def toggle(self) -> None:
        """Home: start if idle, pause if acting, resume if paused."""
        if not self.has_target():
            self._status("목록에서 플레이어를 고르세요")
            return
        if not self.running():
            self.start()
            return
        if self._pause.is_set():
            self._pause.clear()
            self._mouse_up = False
            self._on_running(True, False)
            self._log("재개")
            self._status("재개")
            return
        self._pause.set()
        self._lift_mouse()
        self._on_running(True, True)
        self._log("정지 — 값을 바꾸면 다음 확인에 적용됩니다")
        self._status("정지")

    def start(self) -> None:
        if self.running():
            self._pause.clear()
            self._on_running(True, False)
            return
        if not self.has_target():
            self._status("목록에서 플레이어를 고르세요")
            return
        self._stop.clear()
        self._pause.clear()
        self._mouse_up = False
        self._last_follow_at = 0.0
        self._goal = None
        thread = threading.Thread(target=self._loop, name="follow-player", daemon=True)
        self._thread = thread
        thread.start()
        self._on_running(True, False)

    def stop(self) -> None:
        self._stop.set()
        self._pause.clear()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
        self._lift_mouse()
        self._on_running(False, False)
        self._status("중지")

    def request_refresh(self) -> None:
        """Read nearby players. The worker does it when the loop is up."""
        if self.running():
            self._refresh.set()
            return
        threading.Thread(
            target=self._refresh_bg, name="follow-refresh", daemon=True
        ).start()

    def _refresh_bg(self) -> None:
        try:
            rows, note = self._read_players()
        except Exception as exc:
            self._log(f"갱신 실패: {exc}")
            self._status("플레이어를 읽지 못했습니다")
            return
        self._on_players(rows)
        self._status(note)

    def close(self) -> None:
        self.stop()
        self._shutdown_runtime()

    def _status(self, text: str) -> None:
        try:
            self._on_status(text)
        except Exception:
            pass

    def _log(self, text: str) -> None:
        try:
            self._on_log(text)
        except Exception:
            pass

    def _lift_mouse(self) -> None:
        executor = self.executor
        if executor is None:
            return
        try:
            executor.drop_mouse()
        except Exception:
            pass
        self._mouse_up = True

    def _loop(self) -> None:
        try:
            self._ensure_runtime()
            self._log("따라가기 시작")
            while not self._stop.is_set():
                if self._pause.is_set():
                    if not self._mouse_up:
                        self._lift_mouse()
                    if self._refresh.is_set():
                        self._refresh.clear()
                        if self._capture() is not None:
                            self._emit_players()
                    time.sleep(0.05)
                    continue
                self._mouse_up = False
                self._tick()
        except Exception:
            self._log("루프 오류\n" + traceback.format_exc())
            self._status("오류로 멈춤")
        finally:
            self._lift_mouse()
            self._on_running(False, False)

    def _tick(self) -> None:
        params = self.snapshot_params()
        applied = self._capture()
        if applied is None:
            time.sleep(0.05)
            return
        if self._refresh.is_set():
            self._refresh.clear()
            self._emit_players()

        origin = getattr(self.blackboard, "world_origin", None)
        target = self._find_target(params)
        if origin is None:
            self._status("내 위치를 읽는 중")
            time.sleep(0.05)
            return
        threat = self._threat_monster(origin, target)
        if threat is not None:
            who = _player_name(target) if target is not None else "대상"
            self._goal = None
            self._status(f"{who} — 반격")
            self._act_attack(int(threat.track_id))
            return
        if target is None:
            if not params.target_ent:
                self._status("목록에서 플레이어를 고르세요")
            else:
                self._status(f"{params.target_name or '대상'} — 시야 밖")
            time.sleep(0.05)
            return

        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision.combat_query import object_absolute_tile

        tile = object_absolute_tile(target, origin)
        dist = tile_chebyshev(int(origin.x), int(origin.y), int(tile[0]), int(tile[1]))
        name = _player_name(target)
        if self._try_leader_loot(params, origin, tile, name):
            return
        kind = action_kind(dist, params.follow_tiles, params.attack_tiles)
        if kind == "follow":
            self._follow(params, origin, tile, dist, name)
        elif kind == "hunt":
            self._goal = None
            self._hunt(origin, dist, name)
        else:
            self._goal = None
            self._status(
                f"{name} {dist}타일 — 유지 "
                f"(따라가기 {params.follow_tiles} / 공격 {params.attack_tiles})"
            )
            time.sleep(0.05)

    def _follow(
        self,
        params: FollowParams,
        origin: Any,
        target_tile: tuple[int, int],
        dist: int,
        name: str,
    ) -> None:
        now = time.perf_counter()
        wait = float(params.poll_s) - (now - self._last_follow_at)
        if self._last_follow_at > 0.0 and wait > 0.0:
            self._status(f"{name} {dist}타일 — 따라가는 중")
            time.sleep(min(0.05, wait))
            return
        self._last_follow_at = now
        intent, detail = self._plan_follow(params, origin, target_tile)
        self._status(f"{name} {dist}타일 — {detail}")
        if intent is None:
            time.sleep(0.05)
            return
        self._act(intent)
        time.sleep(0.02)

    def _plan_follow(
        self,
        params: FollowParams,
        origin: Any,
        target_tile: tuple[int, int],
    ) -> tuple[Any, str]:
        from app._02_state import ActionType
        from app._04_decision.nav_config import get_terrain_map
        from app._04_decision.pathfinding import plan_travel_click
        from app._04_decision.types import ActionIntent
        from app._04_decision.combat_query import object_absolute_tile
        from app._02_state.objects import ObjectType

        terrain = get_terrain_map()
        if terrain is None:
            return None, "지형 없음"
        if self._goal == (int(origin.x), int(origin.y)):
            self._goal = None
        occupied: list[tuple[int, int]] = []
        for kind in (ObjectType.PLAYER, ObjectType.MONSTER, ObjectType.NPC):
            for obj in self.world.objects(kind):
                try:
                    occupied.append(object_absolute_tile(obj, origin))
                except Exception:
                    continue
        key = f"{int(target_tile[0])},{int(target_tile[1])}"
        # Keep the last empty tile only while it is still inside the disk.
        previous = self._goal
        goal = choose_approach_tile(
            terrain.is_walkable,
            target_tile,
            params.approach_tiles,
            occupied,
            self._rng,
            previous,
        )
        if goal is None:
            self._goal = None
            return None, "주변 빈 타일 없음"
        dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
        if dest is None:
            self._goal = None
            goal = choose_approach_tile(
                terrain.is_walkable,
                target_tile,
                params.approach_tiles,
                occupied,
                self._rng,
                None,
                exclude=(goal,),
            )
            if goal is None:
                return None, "경로 없음"
            dest, _path, waypoint = plan_travel_click(terrain, origin, goal)
            if dest is None:
                self._goal = None
                return None, "경로 없음"
        self._goal = goal
        self._goal_for = key
        hop = waypoint if waypoint is not None else goal
        intent = ActionIntent(
            action=ActionType.TRAVELING,
            destination=dest,
            priority=0.4,
            reason=f"follow {goal[0]},{goal[1]}",
        )
        return intent, f"이동 {hop[0]},{hop[1]} → {goal[0]},{goal[1]}"

    def _act_attack(self, track_id: int) -> None:
        from app._02_state import ActionType
        from app._04_decision.types import ActionIntent

        self._act(
            ActionIntent(
                action=ActionType.ATTACK,
                target_id=int(track_id),
                priority=0.8,
                reason="follow threat",
            )
        )
        time.sleep(0.02)

    def _threat_monster(self, origin: Any, follow_obj: Any) -> Any:
        """Nearest monster whose AttackAction hits me or the followed player."""
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision.combat_query import (
            can_engage_target,
            nearest_attacks_me_force,
            object_absolute_tile,
        )

        found: list[Any] = []
        seen: set[int] = set()

        def add(obj: Any, *, check: bool) -> None:
            if obj is None or bool(getattr(obj, "bait", False)):
                return
            tid = int(getattr(obj, "track_id", 0) or 0)
            if tid in seen:
                return
            if check and origin is not None:
                try:
                    if not can_engage_target(obj, origin):
                        return
                except Exception:
                    return
            seen.add(tid)
            found.append(obj)

        try:
            # Already engage-filtered, including mobs missing from the entity list.
            add(
                nearest_attacks_me_force(self.world, origin=origin, check_path=True),
                check=False,
            )
        except Exception:
            pass

        snap = getattr(self.world, "last_attacks_me", None)
        wanted: set[int] = set()
        rows: list[Any] = []
        if isinstance(snap, dict):
            me = guid_key(snap.get("me_guid"))
            if me is not None:
                wanted.add(me)
            rows = list(snap.get("strikes") or [])
            if not rows:
                rows = list(snap.get("attacks_me") or [])
        ally = guid_key(getattr(follow_obj, "memory_guid", None))
        if ally is not None:
            wanted.add(ally)
        for row in rows:
            if not strike_hits(row, wanted):
                continue
            add(self._monster_for_strike(row), check=True)

        if not found:
            return None

        def dist_of(obj: Any) -> tuple[int, int]:
            try:
                tile = object_absolute_tile(obj, origin)
                dist = tile_chebyshev(
                    int(origin.x), int(origin.y), int(tile[0]), int(tile[1])
                )
            except Exception:
                dist = 999
            return dist, int(getattr(obj, "track_id", 0) or 0)

        return min(found, key=dist_of)

    def _monster_for_strike(self, row: dict[str, Any]) -> Any:
        ent = str(row.get("ent") or "").strip().lower()
        monsters = self.world.monsters()
        if ent:
            for obj in monsters:
                got = str(getattr(obj, "memory_ent", None) or "").strip().lower()
                if got and got == ent:
                    return obj
        world = row.get("world") if isinstance(row.get("world"), dict) else None
        if not isinstance(world, dict):
            return None
        try:
            cx, cy = int(world["cx"]), int(world["cy"])
        except (KeyError, TypeError, ValueError):
            return None
        matches = [
            obj
            for obj in monsters
            if getattr(obj, "world_cx", None) is not None
            and getattr(obj, "world_cy", None) is not None
            and int(obj.world_cx) == cx
            and int(obj.world_cy) == cy
        ]
        if not matches:
            return None
        return min(matches, key=lambda obj: int(obj.track_id))

    def _try_leader_loot(
        self,
        params: FollowParams,
        origin: Any,
        leader_tile: tuple[int, int],
        name: str,
    ) -> bool:
        """Walk to a pile that stays inside the attack range of the followed player."""
        from app._02_state import ActionType
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision import player_mode as pm
        from app._04_decision.combat_query import object_absolute_tile
        from app._04_decision.types import ActionIntent

        item = self._leader_loot_item(origin, leader_tile, params.attack_tiles)
        if item is None:
            self._loot_stand = None
            return False
        try:
            pile = object_absolute_tile(item, origin)
        except Exception:
            return False
        if tile_chebyshev(int(origin.x), int(origin.y), int(pile[0]), int(pile[1])) <= int(
            pm.LOOT_PICKUP_TILES
        ):
            self._loot_stand = None
            self._status(f"{name} — 줍기")
            self._act(
                ActionIntent(
                    action=ActionType.PICKUP,
                    target_id=int(item.track_id),
                    priority=0.6,
                    reason="follow loot",
                )
            )
            time.sleep(0.02)
            return True
        now = time.perf_counter()
        wait = float(params.poll_s) - (now - self._last_loot_hop_at)
        if self._last_loot_hop_at > 0.0 and wait > 0.0:
            self._status(f"{name} — 줍으러 이동")
            time.sleep(min(0.05, wait))
            return True
        self._last_loot_hop_at = now
        intent, detail = self._plan_loot_hop(origin, pile)
        self._status(f"{name} — {detail}")
        if intent is None:
            return False
        self._act(intent)
        time.sleep(0.02)
        return True

    def _leader_loot_item(self, origin: Any, leader_tile: tuple[int, int], allow: int) -> Any:
        from app._04_decision.combat_query import is_adena, memory_target_gone, object_absolute_tile
        from app._04_decision.ground_loot import ground_item_allowed, loot_ownership_allowed
        from app._04_decision.player_mode import LOOT_MODE_ADENA
        from app._03_world.space.world_coords import tile_chebyshev

        lx, ly = int(leader_tile[0]), int(leader_tile[1])
        best = None
        best_dist = 10**9
        adena_only = self.loot_mode == LOOT_MODE_ADENA
        for obj in self.world.items():
            if memory_target_gone(self.world, obj):
                continue
            if adena_only:
                if not is_adena(obj):
                    continue
            elif not ground_item_allowed(obj):
                continue
            if not loot_ownership_allowed(obj):
                continue
            try:
                tile = object_absolute_tile(obj, origin)
            except Exception:
                continue
            if not within_chebyshev(tile[0], tile[1], lx, ly, allow):
                continue
            dist = tile_chebyshev(int(origin.x), int(origin.y), int(tile[0]), int(tile[1]))
            if dist < best_dist:
                best = obj
                best_dist = dist
        return best

    def _plan_loot_hop(
        self,
        origin: Any,
        pile: tuple[int, int],
    ) -> tuple[Any, str]:
        from app._02_state import ActionType
        from app._02_state.objects import ObjectType
        from app._04_decision.combat_query import object_absolute_tile
        from app._04_decision.nav_config import get_terrain_map
        from app._04_decision.pathfinding import plan_travel_click
        from app._04_decision.types import ActionIntent

        terrain = get_terrain_map()
        if terrain is None:
            return None, "지형 없음"
        occupied: list[tuple[int, int]] = []
        for kind in (ObjectType.PLAYER, ObjectType.MONSTER, ObjectType.NPC):
            for obj in self.world.objects(kind):
                try:
                    occupied.append(object_absolute_tile(obj, origin))
                except Exception:
                    continue
        stand = choose_approach_tile(
            terrain.is_walkable,
            pile,
            1,
            occupied,
            self._rng,
            self._loot_stand,
        )
        if stand is None and terrain.is_walkable(int(pile[0]), int(pile[1])):
            stand = (int(pile[0]), int(pile[1]))
        if stand is None:
            self._loot_stand = None
            return None, "줍기 칸 없음"
        dest, _path, waypoint = plan_travel_click(terrain, origin, stand)
        if dest is None:
            self._loot_stand = None
            return None, "줍기 경로 없음"
        self._loot_stand = stand
        hop = waypoint if waypoint is not None else stand
        intent = ActionIntent(
            action=ActionType.TRAVELING,
            destination=dest,
            priority=0.45,
            reason=f"loot {stand[0]},{stand[1]}",
        )
        return intent, f"줍기 이동 {hop[0]},{hop[1]}"

    def _hunt(self, origin: Any, dist: int, name: str) -> None:
        from app._02_state import ActionType
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision import player_mode as pm
        from app._04_decision.combat_query import (
            nearest_attackable,
            nearest_lootable,
            object_absolute_tile,
        )
        from app._04_decision.types import ActionIntent

        item = nearest_lootable(
            self.world,
            loot_mode=self.loot_mode,
            farm=None,
            origin=origin,
            check_path=False,
            screen_only=True,
        )
        if item is not None:
            try:
                pile = object_absolute_tile(item, origin)
                near = tile_chebyshev(
                    int(origin.x), int(origin.y), int(pile[0]), int(pile[1])
                ) <= int(pm.LOOT_PICKUP_TILES)
            except Exception:
                near = False
            if near:
                self._status(f"{name} {dist}타일 — 줍기")
                self._act(
                    ActionIntent(
                        action=ActionType.PICKUP,
                        target_id=int(item.track_id),
                        priority=0.3,
                        reason="follow loot",
                    )
                )
                time.sleep(0.02)
                return
        enemy = nearest_attackable(
            self.world,
            origin=origin,
            check_path=True,
            screen_only=True,
        )
        if enemy is None:
            self._status(f"{name} {dist}타일 — 볼 것 없음")
            time.sleep(0.05)
            return
        self._status(f"{name} {dist}타일 — 공격")
        self._act(
            ActionIntent(
                action=ActionType.ATTACK,
                target_id=int(enemy.track_id),
                priority=0.5,
                reason="follow attack",
            )
        )
        time.sleep(0.02)

    def _act(self, intent: Any) -> None:
        from app._05_action.cursor_verify import is_cursor_paralyzed

        if is_cursor_paralyzed():
            self._lift_mouse()
            self._status("커서 잠김")
            return
        status, _rect, bounds = self._sample_capture()
        if status != "ok" or bounds is None or not getattr(bounds, "valid", False):
            self._status("게임 창 대기")
            return
        try:
            self.executor.execute(self.world, intent, bounds=bounds)
        except Exception as exc:
            self._log(f"클릭 실패: {exc}")

    def _find_target(self, params: FollowParams) -> Any:
        from app._02_state.objects import ObjectType

        if not params.target_ent or self.world is None:
            return None
        for obj in self.world.objects(ObjectType.PLAYER):
            if _player_key(obj) == params.target_ent:
                return obj
        if params.target_track_id is not None:
            for obj in self.world.objects(ObjectType.PLAYER):
                if int(obj.track_id) == int(params.target_track_id):
                    return obj
        return None

    def _emit_players(self) -> None:
        try:
            rows = self._player_rows()
        except Exception as exc:
            self._log(f"갱신 실패: {exc}")
            return
        self._on_players(rows)
        self._log(f"주변 플레이어 {len(rows)}명")

    def _read_players(self) -> tuple[list[dict[str, Any]], str]:
        with self._busy:
            self._ensure_runtime()
            applied = self._capture()
            if applied is None:
                return [], "게임 메모리 없음"
            rows = self._player_rows()
            return rows, f"주변 플레이어 {len(rows)}명"

    def _player_rows(self) -> list[dict[str, Any]]:
        from app._02_state.objects import ObjectType
        from app._03_world.space.world_coords import tile_chebyshev
        from app._04_decision.combat_query import object_absolute_tile

        origin = getattr(self.blackboard, "world_origin", None)
        rows: list[dict[str, Any]] = []
        for obj in self.world.objects(ObjectType.PLAYER):
            dist = None
            tile = None
            if origin is not None:
                try:
                    tile = object_absolute_tile(obj, origin)
                    dist = tile_chebyshev(
                        int(origin.x), int(origin.y), int(tile[0]), int(tile[1])
                    )
                except Exception:
                    tile = None
                    dist = None
            rows.append(
                {
                    "ent": _player_key(obj),
                    "name": _player_name(obj),
                    "track_id": int(obj.track_id),
                    "dist": dist,
                    "tile": tile,
                }
            )
        rows.sort(key=lambda row: (row["dist"] is None, row["dist"] or 0, row["name"]))
        return rows

    def _capture(self) -> Any:
        from app._03_world.merge.apply_perception import apply_perception_buffer
        from app._04_decision.live_map_pack import ensure_navigation_for_live_map_id

        status, rect, _bounds = self._sample_capture()
        if status == "minimized":
            self._status("게임 창이 최소화됨")
            return None
        if status != "ok":
            self._status("게임 창 대기")
            return None
        buffer = self.sensors.capture_tick()
        applied = apply_perception_buffer(
            self.world,
            self.blackboard,
            buffer,
            content=rect,
        )
        if applied.live_map_id is not None:
            try:
                ensure_navigation_for_live_map_id(
                    self.blackboard,
                    self.config,
                    int(applied.live_map_id),
                    snapshot=applied.live_map_snap,
                )
            except Exception as exc:
                self._log(f"맵 지형: {exc}")
        return applied

    def _sample_capture(self) -> tuple[str, Any, Any]:
        capture = self.capture
        if capture is None:
            return "no_window", None, None
        status = capture.refresh_click_bounds()
        return status, capture.content_rect, capture.content_bounds

    def _ensure_runtime(self) -> None:
        if self._runtime_ready and self.sensors is not None and self.world is not None:
            return
        with self._busy:
            if self._runtime_ready and self.sensors is not None and self.world is not None:
                return
            self._boot()
            self._runtime_ready = True

    def _boot(self) -> None:
        from tool.utils import load_config
        from settings.profile import load_profile
        from app._02_state import CharacterType
        from app._03_world.constants import configure_species_filter
        from app._03_world.merge.track import create_game_state
        from app._04_decision.blackboard import Blackboard
        from app._04_decision.configure import (
            apply_action_executor_options,
            configure_action,
            configure_decision,
        )
        from app._04_decision.dungeon import set_dungeon_mode_override
        from app._04_decision.nav_config import configure_navigation, set_loot_mode
        from app._05_action.controller import ActionExecutor
        from app._01_perception.sensors import PerceptionSensors, set_shared_sensors
        from session.perception_capture import open_perception_capture

        profile = load_profile()
        config = load_config()
        if not isinstance(config, dict):
            config = {}
        nav = dict(config.get("navigation") or {})
        nav["active_map"] = str(getattr(profile, "active_map", "") or "talking_island")
        config["navigation"] = nav
        set_dungeon_mode_override(None)
        configure_species_filter(
            getattr(profile, "species_filter_mode", "blacklist"),
            getattr(profile, "species_blacklist", []),
            getattr(profile, "species_whitelist", []),
        )
        configure_decision(config)
        configure_action(config)
        configure_navigation(config)
        self.loot_mode = set_loot_mode(str(getattr(profile, "loot_mode", "") or "all_items"))
        try:
            character = CharacterType(str(profile.character or "mage").strip().lower())
        except ValueError:
            character = CharacterType.MAGE
        world = create_game_state(character)
        world.hotbar_layout = getattr(profile, "hotbar_layout", None) or {}
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
        executor.hotbar_layout = world.hotbar_layout
        try:
            from app._05_action.mouse import prepare_capture

            prepare_capture()
        except Exception as exc:
            self._log(f"입력 준비: {exc}")
        self.config = config
        self.world = world
        self.blackboard = blackboard
        self.sensors = sensors
        self.capture = capture
        self.executor = executor
        self._log(f"준비됨 ({character.value}, 루팅 {self.loot_mode})")

    def _shutdown_runtime(self) -> None:
        self._lift_mouse()
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
        capture = self.capture
        self.capture = None
        self.sensors = None
        self.executor = None
        self._runtime_ready = False
        if capture is not None:
            close = getattr(capture, "close", None) or getattr(capture, "stop", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
