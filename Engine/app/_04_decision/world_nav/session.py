"""Cooperative world-nav session for the main decision tick."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app._03_world import ActionType
from app._03_world.merge.memory_sync import (
    player_game_xy_from_snapshot,
    player_map_id_from_snapshot,
)
from app._02_state.objects import Position
from app._04_decision.behavior_tree import Status
from app._04_decision.behaviors.travel import (
    SCRATCH_WORLD_NAV_SHORT_WALK,
    clear_travel,
    emit_travel_hop,
    start_travel,
    travel_arrived,
)

from . import pack_ids
from . import planner_api as api

PURPOSE_WORLD_NAV = "world_nav"
# Transition / gate cells in map_transitions may be non-walkable on nav.png.
# Path to a walkable tile within this Chebyshev radius; same radius = arrived.
ARRIVE_TILES = 1
SCROLL_LAND_SLACK = 8
SCROLL_LAND_TIMEOUT_S = 25.0
# After talking-scroll pose lands: stand still before walk / NPC click.
SCROLL_LAND_SETTLE_S = 2.0
TRANSITION_APPROACH = 5
# After teleporter SHOP_RUN clicks finish: min wait, then poll until live xy
# leaves the NPC cell (same mapId — dungeon shutter TPs do not change mapId).
NPC_TP_SETTLE_S = 1.0
NPC_TP_LAND_MOVE_TILES = 15
NPC_TP_LAND_TIMEOUT_S = 12.0
NPC_TP_TIMEOUT_S = 60.0
NPC_TP_APPROACH = 7  # SHOP_ARRIVE_TILES — walk step should already be at NPC


def _chev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def _snap_nav_walkable(
    nav: tuple[int, int],
    *,
    max_r: int = ARRIVE_TILES,
) -> tuple[int, int] | None:
    """Nearest walkable nav tile within ``max_r`` (inclusive of exact cell)."""
    from app._04_decision.nav_config import get_terrain_map

    terrain = get_terrain_map()
    if terrain is None:
        return (int(nav[0]), int(nav[1]))
    x, y = int(nav[0]), int(nav[1])
    if terrain.is_walkable(x, y):
        return (x, y)
    best: tuple[int, int] | None = None
    best_d = 10**9
    for r in range(1, max(1, int(max_r)) + 1):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                nx, ny = x + dx, y + dy
                if not terrain.is_walkable(nx, ny):
                    continue
                d = _chev(x, y, nx, ny)
                if d < best_d:
                    best_d = d
                    best = (nx, ny)
        if best is not None:
            return best
    return None


def live_pose_from_state(state: Any, *, fresh: bool = False) -> Any | None:
    """Build pose from monitor ``mapId`` + tile xy.

    ``mapId`` comes only from realtime_monitor (MapSubsystem). On a normal tick,
    tile xy prefers print_state; monitor ``pos`` is the fallback.

    ``fresh=True`` means *pull a new snapshot now* with ``snapshot(fresh=False)``.
    It must NOT call the DLL ``fresh`` flag (that runs ``discoverNow`` and can
    hang 28–70s). Required while a blocking gate click runs on the worker —
    ``last_memory_snapshot`` / print_state are otherwise frozen for the whole
    TRANSITION_WAIT_S window (false ``mapId did not become N`` after a real land).
    """
    snap = getattr(state, "last_memory_snapshot", None)
    if fresh:
        try:
            from app._01_perception.sensors import shared_sensors

            # Pull-now only: full player block includes MapSubsystem mapId (~20ms).
            # Never pass fresh=True into the DLL here.
            fresh_snap = shared_sensors().pull_player()
            if isinstance(fresh_snap, dict) and fresh_snap.get("player"):
                snap = fresh_snap
                try:
                    state.last_memory_snapshot = fresh_snap
                except Exception:
                    pass
        except Exception:
            pass
    if not isinstance(snap, dict):
        return None
    mid = player_map_id_from_snapshot(snap)
    print_snap = getattr(state, "last_print_state", None)
    if fresh:
        # print_state is also frozen during the blocking gate wait.
        xy = player_game_xy_from_snapshot(snap)
        if xy is None and isinstance(print_snap, dict):
            xy = player_game_xy_from_snapshot(print_snap)
    else:
        xy = (
            player_game_xy_from_snapshot(print_snap)
            if isinstance(print_snap, dict)
            else None
        )
        if xy is None:
            xy = player_game_xy_from_snapshot(snap)
    if xy is None or mid is None:
        return None
    return api.Pose(int(mid), int(xy[0]), int(xy[1]))


@dataclass
class WorldNavSession:
    reason: str = ""
    plan: Any = None
    step_i: int = 0
    phase: str = "idle"  # idle|walk|scroll|scroll_settle|gate_approach|gate_click|npc_teleporter|npc_teleporter_settle|done|fail
    error: str | None = None
    scroll_started_at: float = 0.0
    scroll_landed_at: float = 0.0
    scroll_target: tuple[int, int, int] | None = None  # map,x,y
    gate: dict[str, Any] | None = None
    tp_behavior_id: str = ""
    tp_expect_map_id: int | None = None
    tp_started_at: float = 0.0
    tp_settle_until: float = 0.0
    tp_settle_started_at: float = 0.0
    tp_baseline_xy: tuple[int, int] | None = None
    done_ok: bool = False

    def begin(
        self,
        start: Any,
        goal: Any,
        *,
        reason: str,
        has_talking_scroll: bool = True,
        adena: int | None = None,
        use_npc_teleporters: bool = True,
    ) -> bool:
        self.reason = reason
        self.step_i = 0
        self.error = None
        self.done_ok = False
        self.gate = None
        self.scroll_target = None
        self.scroll_landed_at = 0.0
        self.tp_behavior_id = ""
        self.tp_expect_map_id = None
        self.tp_started_at = 0.0
        self.tp_settle_until = 0.0
        self.tp_settle_started_at = 0.0
        self.tp_baseline_xy = None
        self.plan = api.plan(
            start,
            goal,
            has_talking_scroll=has_talking_scroll,
            adena=adena,
            use_npc_teleporters=use_npc_teleporters,
        )
        tokens = api.state_tokens()
        if not self.plan.ok or not self.plan.steps:
            self.phase = "fail"
            self.error = str(self.plan.error or "no plan")
            api.emit_state(
                tokens.PLAN_FAIL,
                reason=reason,
                error=self.error,
                start=f"map{start.map_id},{start.x},{start.y}",
            )
            return False
        end = self.plan.end_pose
        api.emit_state(
            tokens.PLAN_OK,
            reason=reason,
            cost=self.plan.total_cost_tiles,
            steps=len(self.plan.steps),
            start=f"map{start.map_id},{start.x},{start.y}",
            end=None
            if end is None
            else f"map{end.map_id},{end.x},{end.y}",
        )
        api.emit_state(
            tokens.RUN_START,
            reason=reason,
            steps=len(self.plan.steps),
            cost=self.plan.total_cost_tiles,
        )
        self.phase = "ready"
        return True

    @property
    def active(self) -> bool:
        return self.phase not in ("idle", "done", "fail") and self.plan is not None

    def fail(self, message: str) -> None:
        self.phase = "fail"
        self.error = message
        self.done_ok = False
        tokens = api.state_tokens()
        api.emit_state(tokens.RUN_FAIL, reason=self.reason, error=message)

    def complete(self) -> None:
        self.phase = "done"
        self.done_ok = True
        tokens = api.state_tokens()
        api.emit_state(tokens.RUN_DONE, reason=self.reason, steps=self.step_i)

    def tick(self, state: Any, blackboard: Any) -> Status | None:
        """Advance one step; emit intents on blackboard. None when finished."""
        if self.phase in ("done", "fail", "idle"):
            return None
        if self.plan is None or not self.plan.steps:
            self.fail("empty plan")
            return Status.FAILURE

        # Teleporter shop wait / settle can proceed without a fresh pose.
        if self.phase == "npc_teleporter":
            return self._tick_npc_teleporter_wait(blackboard)
        if self.phase == "npc_teleporter_settle":
            return self._tick_npc_teleporter_settle(state, blackboard)

        pose = live_pose_from_state(state)
        if pose is None:
            blackboard.current_goal = "world_nav"
            blackboard.emit(
                ActionType.IDLE,
                priority=0.4,
                reason="world nav waiting pose",
            )
            return Status.SUCCESS

        # Scroll landing wait
        if self.phase == "scroll":
            return self._tick_scroll_wait(pose, blackboard)

        if self.phase == "scroll_settle":
            return self._tick_scroll_settle(pose, blackboard)

        if self.phase == "gate_click":
            # GATE intent → ActionExecutor.run_gate_click (not worker side-channel).
            if self.gate is None:
                self.fail("gate payload missing")
                return Status.FAILURE
            return self._emit_gate(blackboard)

        if self.step_i >= len(self.plan.steps):
            self.complete()
            return None

        step = self.plan.steps[self.step_i]
        tokens = api.state_tokens()
        if self.phase == "ready":
            api.emit_state(
                tokens.STEP_BEGIN,
                i=self.step_i + 1,
                n=len(self.plan.steps),
                op=step.op,
                summary=step.summary(),
            )
            if step.op == "walk":
                return self._start_walk(step, pose, blackboard, state)
            if step.op == "talking_scroll":
                return self._start_scroll(step, blackboard)
            if step.op == "map_transition":
                return self._start_transition(step, pose, blackboard, state)
            if step.op == "npc_teleporter":
                return self._start_npc_teleporter(step, pose, blackboard)
            self.fail(f"unknown op={step.op}")
            return Status.FAILURE

        if self.phase == "walk":
            return self._tick_walk(step, pose, blackboard, state)

        if self.phase == "gate_approach":
            return self._tick_gate_approach(step, pose, blackboard, state)

        return Status.SUCCESS

    def _snap_live_origin(self, blackboard: Any) -> bool:
        """If player nav cell is non-walkable, move origin to nearest walkable ≤2.

        Gate land cells in map_transitions are often blocked on nav.png; without
        this, post-transition walk gets immediate no_path from an unwalkable start.
        """
        from app._03_world.space.world_coords import WorldOrigin
        from app._04_decision.nav_config import get_terrain_map
        from app.bot_log import get_logger

        terrain = get_terrain_map()
        if terrain is None:
            return True
        ox = int(blackboard.world_origin.x)
        oy = int(blackboard.world_origin.y)
        if terrain.is_walkable(ox, oy):
            return True
        snapped = _snap_nav_walkable((ox, oy), max_r=ARRIVE_TILES)
        if snapped is None:
            get_logger("nav").warning(
                "live origin (%s,%s) unwalkable, no snap within %s",
                ox,
                oy,
                ARRIVE_TILES,
            )
            return False
        get_logger("nav").info(
            "live origin snap (%s,%s)→%s (r≤%s)",
            ox,
            oy,
            snapped,
            ARRIVE_TILES,
        )
        blackboard.world_origin = WorldOrigin(x=snapped[0], y=snapped[1])
        return True

    def _finish_walk_step(self, blackboard: Any, *, map_id: int, gx: int, gy: int) -> Status:
        tokens = api.state_tokens()
        api.emit_state(tokens.WALK_ARRIVE, map=map_id, x=gx, y=gy)
        api.emit_state(
            tokens.STEP_OK,
            i=self.step_i + 1,
            n=len(self.plan.steps),
            op="walk",
        )
        clear_travel(blackboard)
        blackboard.scratch.pop(SCRATCH_WORLD_NAV_SHORT_WALK, None)
        self.step_i += 1
        self.phase = "ready"
        return Status.SUCCESS

    def _start_walk(self, step: Any, pose: Any, blackboard: Any, state: Any) -> Status:
        det = step.detail
        to = det["to"]
        map_id = int(to["mapId"])
        gx, gy = int(to["x"]), int(to["y"])
        if pose.map_id != map_id:
            self.fail(f"walk on wrong map{pose.map_id} want map{map_id}")
            return Status.FAILURE
        # After a gate, mapId can update a tick before absolute xy. Walking from
        # the old cell on the new pack yields no_path (e.g. TI 32477 on F1).
        frm = det.get("from")
        if isinstance(frm, dict):
            try:
                fx, fy = int(frm["x"]), int(frm["y"])
            except (TypeError, ValueError):
                fx = fy = None
            if fx is not None and _chev(pose.x, pose.y, fx, fy) > 24:
                return self._idle(blackboard, "world nav wait land xy")
        # Already at the walk goal — skip hop. After a talking-scroll land the
        # teleporter NPC is usually within click range, so skip walking to it.
        skip_r = ARRIVE_TILES
        nxt_i = self.step_i + 1
        if nxt_i < len(self.plan.steps):
            nxt = self.plan.steps[nxt_i]
            if str(getattr(nxt, "op", "") or "") == "npc_teleporter":
                skip_r = NPC_TP_APPROACH
        if _chev(pose.x, pose.y, gx, gy) <= skip_r:
            tokens = api.state_tokens()
            api.emit_state(tokens.WALK_START, map=map_id, x=gx, y=gy)
            return self._finish_walk_step(blackboard, map_id=map_id, gx=gx, gy=gy)
        pack_id = pack_ids.map_id_to_pack_id(map_id)
        if pack_id is None:
            self.fail(f"no pack for map{map_id}")
            return Status.FAILURE
        nav = pack_ids.abs_to_nav(pack_id, gx, gy)
        if nav is None:
            self.fail("abs_to_nav failed")
            return Status.FAILURE
        # Active pack must match before travel (sync; async raced dungeon origin).
        if not self._ensure_map_pack(blackboard, pack_id):
            return self._idle(blackboard, "world nav wait pack")
        snapped = _snap_nav_walkable(nav, max_r=ARRIVE_TILES)
        if snapped is None:
            self.fail(
                f"no walkable tile within {ARRIVE_TILES} of "
                f"({gx},{gy}) nav={nav}"
            )
            return Status.FAILURE
        if snapped != nav:
            from app.bot_log import get_logger

            get_logger("nav").info(
                "walk goal snap nav %s→%s (abs %s,%s unwalkable, r≤%s)",
                nav,
                snapped,
                gx,
                gy,
                ARRIVE_TILES,
            )
            nav = snapped
        # Landing / transition cells are often non-walkable — snap live origin too.
        if not self._snap_live_origin(blackboard):
            return self._idle(blackboard, "world nav wait start walkable")
        tokens = api.state_tokens()
        api.emit_state(tokens.WALK_START, map=map_id, x=gx, y=gy)
        clear_travel(blackboard)
        prev = self.plan.steps[self.step_i - 1] if self.step_i > 0 else None
        after_scroll = (
            prev is not None and str(getattr(prev, "op", "") or "") == "talking_scroll"
        )
        if after_scroll:
            blackboard.scratch[SCRATCH_WORLD_NAV_SHORT_WALK] = True
        else:
            blackboard.scratch.pop(SCRATCH_WORLD_NAV_SHORT_WALK, None)
        start_travel(blackboard, nav, reason=f"world nav walk ({self.reason})")
        blackboard.travel_purpose = PURPOSE_WORLD_NAV
        self.phase = "walk"
        # Standing on/near snapped walkable tile: travel reports already_arrived.
        if travel_arrived(blackboard):
            return self._finish_walk_step(blackboard, map_id=map_id, gx=gx, gy=gy)
        emit_travel_hop(
            blackboard, reason="world nav walk", priority=0.6, state=state
        )
        if blackboard.intent is not None:
            return Status.SUCCESS
        miss = str(blackboard.scratch.get("travel_hop_miss") or "")
        if miss in ("already_arrived", "hop_arrive_final"):
            return self._finish_walk_step(blackboard, map_id=map_id, gx=gx, gy=gy)
        return self._idle(blackboard, "world nav walk hop")

    def _tick_walk(self, step: Any, pose: Any, blackboard: Any, state: Any) -> Status:
        to = step.detail["to"]
        map_id = int(to["mapId"])
        gx, gy = int(to["x"]), int(to["y"])
        if pose.map_id != map_id:
            blackboard.scratch.pop(SCRATCH_WORLD_NAV_SHORT_WALK, None)
            self.fail(f"left map during walk (map{pose.map_id})")
            return Status.FAILURE
        if _chev(pose.x, pose.y, gx, gy) <= ARRIVE_TILES or travel_arrived(blackboard):
            return self._finish_walk_step(blackboard, map_id=map_id, gx=gx, gy=gy)
        ok = emit_travel_hop(
            blackboard, reason="world nav walk", priority=0.6, state=state
        )
        if blackboard.intent is not None:
            return Status.SUCCESS
        if not ok:
            miss = str(blackboard.scratch.get("travel_hop_miss") or "hop_false")
            # Snapped goal: travel may say arrived while abs chev to transition is 3.
            if miss in ("already_arrived", "hop_arrive_final"):
                return self._finish_walk_step(blackboard, map_id=map_id, gx=gx, gy=gy)
            tokens = api.state_tokens()
            api.emit_state(tokens.WALK_FAIL, map=map_id, x=gx, y=gy, error=miss)
            blackboard.scratch.pop(SCRATCH_WORLD_NAV_SHORT_WALK, None)
            self.fail(f"walk hop failed {miss}")
            return Status.FAILURE
        return self._idle(blackboard, "world nav walk")

    def _start_scroll(self, step: Any, blackboard: Any) -> Status:
        from app._04_decision.talking_scroll import emit_talking_scroll_uv

        det = step.detail
        to = det["to"]
        map_id = int(to["mapId"])
        tx, ty = int(to["x"]), int(to["y"])
        ui = det.get("ui") or {}
        click = ui.get("click") or {}
        snap = ui.get("snapshot_size") or {"width": 800, "height": 600}
        try:
            cx = float(click["x"]) / float(snap["width"])
            cy = float(click["y"]) / float(snap["height"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            self.fail(f"scroll ui.click missing: {exc}")
            return Status.FAILURE
        wheels = int(ui.get("scroll_times") or 0)
        label = det.get("label") or ""
        tokens = api.state_tokens()
        api.emit_state(
            tokens.SCROLL_START,
            dest=label,
            map=map_id,
            x=tx,
            y=ty,
            wheels=wheels,
        )
        pack_id = pack_ids.map_id_to_pack_id(map_id)
        status = emit_talking_scroll_uv(
            blackboard,
            destination=Position(x=cx, y=cy),
            reason=f"world nav scroll {label}",
            land_map_id=map_id,
            land_pack_id=pack_id,
            land_x=tx,
            land_y=ty,
            scroll_times=wheels,
        )
        if status is Status.FAILURE:
            api.emit_state(tokens.SCROLL_FAIL, map=map_id, error="emit failed")
            self.fail("talking scroll emit failed")
            return Status.FAILURE
        self.scroll_started_at = time.time()
        self.scroll_target = (map_id, tx, ty)
        self.phase = "scroll"
        return Status.SUCCESS

    def _tick_scroll_wait(self, pose: Any, blackboard: Any) -> Status:
        tokens = api.state_tokens()
        if self.scroll_target is None:
            self.fail("scroll target missing")
            return Status.FAILURE
        map_id, tx, ty = self.scroll_target
        if pose.map_id == map_id and _chev(pose.x, pose.y, tx, ty) <= SCROLL_LAND_SLACK:
            api.emit_state(
                tokens.SCROLL_LAND,
                map=map_id,
                x=pose.x,
                y=pose.y,
            )
            api.emit_state(
                tokens.SCROLL_SETTLE,
                map=map_id,
                wait_s=round(SCROLL_LAND_SETTLE_S, 2),
            )
            self.scroll_landed_at = time.time()
            self.phase = "scroll_settle"
            return self._tick_scroll_settle(pose, blackboard)
        if time.time() - self.scroll_started_at > SCROLL_LAND_TIMEOUT_S:
            err = (
                f"scroll land timeout at map{pose.map_id} ({pose.x},{pose.y}) "
                f"want map{map_id} ({tx},{ty})"
            )
            api.emit_state(tokens.SCROLL_FAIL, error=err)
            self.fail(err)
            return Status.FAILURE
        return self._idle(blackboard, "world nav scroll land")

    def _tick_scroll_settle(self, pose: Any, blackboard: Any) -> Status:
        if self.scroll_target is None:
            self.fail("scroll target missing")
            return Status.FAILURE
        map_id, _tx, _ty = self.scroll_target
        pack_id = pack_ids.map_id_to_pack_id(map_id)
        if pack_id and not self._ensure_map_pack(blackboard, pack_id):
            return self._idle(blackboard, "world nav wait pack")
        if time.time() - self.scroll_landed_at < SCROLL_LAND_SETTLE_S:
            return self._idle(blackboard, "world nav scroll settle")
        tokens = api.state_tokens()
        api.emit_state(
            tokens.STEP_OK,
            i=self.step_i + 1,
            n=len(self.plan.steps),
            op="talking_scroll",
        )
        self.step_i += 1
        self.phase = "ready"
        self.scroll_target = None
        return Status.SUCCESS

    def _start_transition(
        self, step: Any, pose: Any, blackboard: Any, state: Any
    ) -> Status:
        det = step.detail
        frm, to = det["from"], det["to"]
        from_map = int(frm["mapId"])
        fx, fy = int(frm["x"]), int(frm["y"])
        to_map = int(to["mapId"])
        tx, ty = int(to["x"]), int(to["y"])
        edge = str(det.get("edge_id") or "")
        tokens = api.state_tokens()
        api.emit_state(
            tokens.TRANSITION_START,
            edge=edge,
            from_map=from_map,
            to_map=to_map,
        )
        if pose.map_id == to_map:
            api.emit_state(tokens.TRANSITION_LANDED, map=to_map, x=pose.x, y=pose.y)
            self.step_i += 1
            self.phase = "ready"
            return Status.SUCCESS
        if pose.map_id != from_map:
            self.fail(f"transition wrong map{pose.map_id} want {from_map}")
            return Status.FAILURE
        pack_id = pack_ids.map_id_to_pack_id(from_map)
        if pack_id is None:
            self.fail(f"no pack map{from_map}")
            return Status.FAILURE
        if not self._ensure_map_pack(blackboard, pack_id):
            return self._idle(blackboard, "world nav wait pack")
        nav = pack_ids.abs_to_nav(pack_id, fx, fy)
        if nav is None:
            self.fail("entrance abs_to_nav failed")
            return Status.FAILURE
        snapped = _snap_nav_walkable(nav, max_r=ARRIVE_TILES)
        if snapped is None:
            self.fail(
                f"no walkable tile within {ARRIVE_TILES} of gate "
                f"({fx},{fy}) nav={nav}"
            )
            return Status.FAILURE
        if snapped != nav:
            from app.bot_log import get_logger

            get_logger("nav").info(
                "gate approach snap nav %s→%s (entrance %s,%s, r≤%s)",
                nav,
                snapped,
                fx,
                fy,
                ARRIVE_TILES,
            )
            nav = snapped
        if not self._snap_live_origin(blackboard):
            return self._idle(blackboard, "world nav wait start walkable")
        self.gate = {
            "from_map": from_map,
            "to_map": to_map,
            "fx": fx,
            "fy": fy,
            "tx": tx,
            "ty": ty,
            "edge": edge,
            "pack_id": pack_id,
        }
        clear_travel(blackboard)
        start_travel(
            blackboard, nav, reason=f"world nav approach gate {edge}"
        )
        blackboard.travel_purpose = PURPOSE_WORLD_NAV
        self.phase = "gate_approach"
        # Already at entrance (snapped / ≤ approach) → queue GATE click.
        if (
            _chev(pose.x, pose.y, fx, fy) <= TRANSITION_APPROACH
            or travel_arrived(blackboard)
        ):
            clear_travel(blackboard)
            self.phase = "gate_click"
            return self._emit_gate(blackboard)
        emit_travel_hop(
            blackboard,
            reason="world nav gate approach",
            priority=0.6,
            state=state,
        )
        return Status.SUCCESS if blackboard.intent is not None else self._idle(
            blackboard, "world nav gate approach"
        )

    def _tick_gate_approach(
        self, step: Any, pose: Any, blackboard: Any, state: Any
    ) -> Status:
        assert self.gate is not None
        g = self.gate
        if pose.map_id == int(g["to_map"]):
            tokens = api.state_tokens()
            api.emit_state(
                tokens.TRANSITION_LANDED,
                map=g["to_map"],
                x=pose.x,
                y=pose.y,
            )
            clear_travel(blackboard)
            self.step_i += 1
            self.phase = "ready"
            self.gate = None
            return Status.SUCCESS
        if pose.map_id != int(g["from_map"]):
            self.fail(f"left map before gate (map{pose.map_id})")
            return Status.FAILURE
        if _chev(pose.x, pose.y, int(g["fx"]), int(g["fy"])) <= TRANSITION_APPROACH:
            clear_travel(blackboard)
            self.phase = "gate_click"
            return self._emit_gate(blackboard)
        emit_travel_hop(
            blackboard,
            reason="world nav gate approach",
            priority=0.6,
            state=state,
        )
        return Status.SUCCESS if blackboard.intent is not None else self._idle(
            blackboard, "world nav gate approach"
        )

    def _start_npc_teleporter(self, step: Any, pose: Any, blackboard: Any) -> Status:
        """Emit SHOP_RUN teleporter; land xy read after settle (same map as NPC)."""
        from shop.behaviors import ACTION_TELEPORTER, behavior_by_id
        from shop.runtime import npc_content_uv

        det = step.detail
        bid = str(det.get("behavior_id") or "").strip()
        frm = det.get("from") or {}
        expect_map = int(det.get("land_map_id") or frm.get("mapId") or pose.map_id)
        nx, ny = int(frm.get("x", -1)), int(frm.get("y", -1))
        tokens = api.state_tokens()
        if not bid or nx < 0 or ny < 0:
            self.fail("npc_teleporter detail missing")
            return Status.FAILURE
        if pose.map_id != expect_map:
            self.fail(f"npc teleporter wrong map{pose.map_id} want map{expect_map}")
            return Status.FAILURE
        if _chev(pose.x, pose.y, nx, ny) > NPC_TP_APPROACH:
            self.fail(
                f"npc teleporter not near NPC ({pose.x},{pose.y}) "
                f"want ({nx},{ny}) r≤{NPC_TP_APPROACH}"
            )
            return Status.FAILURE
        behavior = behavior_by_id(bid)
        if behavior is None or str(behavior.action) != ACTION_TELEPORTER:
            self.fail(f"unknown teleporter behavior {bid}")
            return Status.FAILURE
        pack_id = pack_ids.map_id_to_pack_id(expect_map)
        if pack_id is None:
            self.fail(f"no pack for map{expect_map}")
            return Status.FAILURE
        if not self._ensure_map_pack(blackboard, pack_id):
            return self._idle(blackboard, "world nav wait pack")
        api.emit_state(
            tokens.NPC_TP_START,
            behavior=bid,
            map=expect_map,
            x=nx,
            y=ny,
            adena=det.get("adena_cost"),
            gate=det.get("gate_edge_id"),
        )
        blackboard.current_goal = "world_nav_teleporter"
        blackboard.emit(
            ActionType.SHOP_RUN,
            destination=npc_content_uv(behavior, blackboard.world_origin),
            priority=0.7,
            reason=f"world nav teleporter:{bid}",
            shop_behavior_id=bid,
            shop_qty=1,
            shop_kind="teleporter",
        )
        self.tp_behavior_id = bid
        self.tp_expect_map_id = expect_map
        self.tp_started_at = time.time()
        self.tp_settle_until = 0.0
        self.tp_settle_started_at = 0.0
        self.tp_baseline_xy = None
        self.phase = "npc_teleporter"
        return Status.SUCCESS

    def _tick_npc_teleporter_wait(self, blackboard: Any) -> Status:
        tokens = api.state_tokens()
        if time.time() - self.tp_started_at > NPC_TP_TIMEOUT_S:
            err = f"npc teleporter timeout behavior={self.tp_behavior_id}"
            api.emit_state(tokens.NPC_TP_FAIL, error=err)
            self.fail(err)
            return Status.FAILURE
        return self._idle(blackboard, "world nav teleporter shop")

    def note_npc_teleporter_ok(self, behavior_id: str = "") -> bool:
        """SHOP_RUN finished — settle, then wait until live xy leaves the NPC cell."""
        if self.phase != "npc_teleporter":
            return False
        bid = str(behavior_id or "").strip()
        if bid and self.tp_behavior_id and bid != self.tp_behavior_id:
            return False
        now = time.time()
        self.tp_settle_until = now + NPC_TP_SETTLE_S
        self.tp_settle_started_at = now
        baseline: tuple[int, int] | None = None
        if self.plan is not None and 0 <= self.step_i < len(self.plan.steps):
            frm = (self.plan.steps[self.step_i].detail or {}).get("from") or {}
            try:
                bx, by = int(frm.get("x", -1)), int(frm.get("y", -1))
            except (TypeError, ValueError):
                bx, by = -1, -1
            if bx >= 0 and by >= 0:
                baseline = (bx, by)
        self.tp_baseline_xy = baseline
        self.phase = "npc_teleporter_settle"
        return True

    def _tick_npc_teleporter_settle(self, state: Any, blackboard: Any) -> Status:
        tokens = api.state_tokens()
        if time.time() < self.tp_settle_until:
            return self._idle(blackboard, "world nav teleporter settle")
        pose = live_pose_from_state(state, fresh=True)
        if pose is None:
            return self._idle(blackboard, "world nav teleporter wait pose")
        expect = self.tp_expect_map_id
        if expect is not None and pose.map_id != int(expect):
            err = (
                f"npc teleporter land map{pose.map_id} want map{expect} "
                f"behavior={self.tp_behavior_id}"
            )
            api.emit_state(tokens.NPC_TP_FAIL, error=err)
            self.fail(err)
            return Status.FAILURE
        baseline = self.tp_baseline_xy
        if baseline is not None:
            moved = _chev(pose.x, pose.y, baseline[0], baseline[1])
            if moved <= NPC_TP_LAND_MOVE_TILES:
                if time.time() - self.tp_settle_started_at > NPC_TP_LAND_TIMEOUT_S:
                    err = (
                        f"npc teleporter land xy stuck near "
                        f"({baseline[0]},{baseline[1]}) "
                        f"live=({pose.x},{pose.y}) r={moved} "
                        f"need>{NPC_TP_LAND_MOVE_TILES} "
                        f"behavior={self.tp_behavior_id}"
                    )
                    api.emit_state(tokens.NPC_TP_FAIL, error=err)
                    self.fail(err)
                    return Status.FAILURE
                return self._idle(blackboard, "world nav teleporter wait land")
        pack_id = pack_ids.map_id_to_pack_id(pose.map_id)
        if pack_id and not self._ensure_map_pack(blackboard, pack_id):
            return self._idle(blackboard, "world nav wait pack")
        # Stamp nav origin from the landed abs cell so gate approach starts here.
        try:
            from app._03_world.merge.memory_sync import game_to_nav
            from app._03_world.space.world_coords import WorldOrigin

            nx, ny = game_to_nav(int(pose.x), int(pose.y))
            blackboard.world_origin = WorldOrigin(x=int(nx), y=int(ny))
        except Exception:
            pass
        step = self.plan.steps[self.step_i]
        det = step.detail if step is not None else {}
        dest = int(det.get("destination_dungeon") or 0)
        if dest > 0:
            rewritten = self._rewrite_next_gate_from_live_pose(
                pose, destination_dungeon=dest
            )
            if not rewritten:
                err = (
                    f"no ground_enter to map{dest} near "
                    f"map{pose.map_id}({pose.x},{pose.y}) after teleporter"
                )
                api.emit_state(tokens.NPC_TP_FAIL, error=err)
                self.fail(err)
                return Status.FAILURE
        api.emit_state(
            tokens.NPC_TP_LAND,
            behavior=self.tp_behavior_id,
            map=pose.map_id,
            x=pose.x,
            y=pose.y,
            dest=dest or None,
        )
        api.emit_state(
            tokens.STEP_OK,
            i=self.step_i + 1,
            n=len(self.plan.steps),
            op="npc_teleporter",
        )
        self.step_i += 1
        self.phase = "ready"
        self.tp_behavior_id = ""
        self.tp_expect_map_id = None
        self.tp_settle_until = 0.0
        self.tp_settle_started_at = 0.0
        self.tp_baseline_xy = None
        return Status.SUCCESS

    def _rewrite_next_gate_from_live_pose(
        self, pose: Any, *, destination_dungeon: int
    ) -> bool:
        """After TP land: pick nearest ground_enter for destination, patch next step."""
        from .npc_teleporters import nearest_ground_enter_for_destination
        from .ready.graph import load_graph

        if self.plan is None or self.step_i + 1 >= len(self.plan.steps):
            return False
        nxt = self.plan.steps[self.step_i + 1]
        if getattr(nxt, "op", "") != "map_transition":
            return False
        graph = load_graph()
        tr = nearest_ground_enter_for_destination(
            graph.transitions,
            from_map=int(pose.map_id),
            destination_dungeon=int(destination_dungeon),
            near_x=int(pose.x),
            near_y=int(pose.y),
        )
        if tr is None:
            return False
        nxt.detail = {
            "edge_id": tr.edge_id,
            "edge_type": tr.edge_type,
            "from": {"mapId": tr.from_map, "x": tr.from_x, "y": tr.from_y},
            "to": {"mapId": tr.to_map, "x": tr.to_x, "y": tr.to_y},
            "meta": dict(tr.meta or {}),
            "resolved_after_teleporter": True,
            "destination_dungeon": int(destination_dungeon),
        }
        return True

    def note_gate_result(self, ok: bool, pose: Any | None, error: str = "") -> None:
        tokens = api.state_tokens()
        if ok and pose is not None and self.gate is not None:
            api.emit_state(
                tokens.TRANSITION_LANDED,
                map=pose.map_id,
                x=pose.x,
                y=pose.y,
                edge=self.gate.get("edge"),
            )
            api.emit_state(
                tokens.STEP_OK,
                i=self.step_i + 1,
                n=len(self.plan.steps),
                op="map_transition",
            )
            self.step_i += 1
            self.phase = "ready"
            self.gate = None
            return
        api.emit_state(tokens.TRANSITION_FAIL, error=error or "gate fail")
        self.fail(error or "map transition gate failed")

    def _ensure_map_pack(self, blackboard: Any, pack_id: str) -> bool:
        """Load ``pack_id`` via central live-map sync before travel."""
        from app._04_decision.live_map_pack import ensure_navigation_for_pack_id
        from .hooks import SCRATCH_RUNTIME_CONFIG

        config = blackboard.scratch.get(SCRATCH_RUNTIME_CONFIG)
        if not isinstance(config, dict):
            return False
        ok, _msg = ensure_navigation_for_pack_id(blackboard, config, pack_id)
        return bool(ok)

    def _emit_gate(self, blackboard: Any) -> Status:
        """Emit ``ActionType.GATE`` for the pending map transition."""
        g = self.gate
        if not isinstance(g, dict):
            self.fail("gate payload missing")
            return Status.FAILURE
        from .hooks import SCRATCH_WORLD_NAV_GATE

        # Keep a copy for apply_gate_result / debug; executor reads Intent fields.
        blackboard.scratch[SCRATCH_WORLD_NAV_GATE] = dict(g)
        blackboard.current_goal = "world_nav_gate"
        blackboard.emit(
            ActionType.GATE,
            priority=0.55,
            reason="world nav gate",
            gate_entrance=(int(g["fx"]), int(g["fy"])),
            gate_expect_map_id=int(g["to_map"]),
            gate_expect_xy=(int(g["tx"]), int(g["ty"])),
            gate_from_map_id=int(g["from_map"]),
            gate_edge=str(g.get("edge") or ""),
        )
        return Status.SUCCESS

    def _idle(self, blackboard: Any, reason: str) -> Status:
        blackboard.current_goal = "world_nav"
        blackboard.emit(ActionType.IDLE, priority=0.4, reason=reason)
        return Status.SUCCESS
