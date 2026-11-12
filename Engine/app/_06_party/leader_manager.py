"""Party leader decide loop.

Combat, healing, and the travel session still use the existing action tools.
The hunt schedule is :class:`PartyLeaderSchedule`. This module does not
install the solo routine cursor and does not read ``profile.routine``.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from app._06_party.leader_schedule import PartyLeaderSchedule
from app._06_party.party_log import get_logger as _party_logger

_log = _party_logger("leader")

# A party walk is dropped only when the body has never stood on its start.
# The first second covers a gate whose map id flips before xy, and a scroll
# land whose pose is still the old tile. Once the body has been within this
# many tiles of ``from`` on that map, walking farther is the route itself.
_WALK_FROM_LAG_TILES = 24
_WALK_FROM_LAG_S = 1.0


class PartyLeaderManager:
    """Leader tick. The party document chooses the mark. Solo decide hunts it."""

    def __init__(self, decision: Any) -> None:
        self.decision = decision
        self.schedule = PartyLeaderSchedule([])
        self._mounted: Optional[tuple] = None
        self._retry_at = 0.0
        self._from_far_since = 0.0
        self._walk_start_near: Optional[tuple] = None
        # turret only while the live tile is a party-map point.
        self.hunt_mode = "moving"
        self.on_area = False
        self.turret_anchor: Optional[tuple[int, int]] = None
        self._plan_motion: Optional[str] = None

    def decide(self, world: Any) -> Any:
        return self.decision.decide(world)

    def arm(self, routine: Any) -> int:
        """Keep the party document on this leader. The solo cursor stays unset."""
        self.schedule = PartyLeaderSchedule.from_routine(routine)
        self._mounted = None
        self._retry_at = 0.0
        self._from_far_since = 0.0
        self._walk_start_near = None
        self._plan_motion = None
        self._set_place("moving")
        blackboard = self.decision.blackboard
        scratch = getattr(blackboard, "scratch", None)
        if isinstance(scratch, dict):
            scratch.pop("routine_cursor", None)
            scratch.pop("need_world_nav", None)
            scratch["party_player_ring"] = True
            scratch["party_point_arrival"] = self._on_point_arrival
            scratch.pop("party_area_border", None)
            from app._04_decision.behaviors.party_turret import release_turret_routine

            release_turret_routine(blackboard)
        return len(self.schedule.rows)

    def prepare(self, world: Any, rally: Any = None) -> None:
        """Walk to the current party mark, then count the row's minutes there."""
        self._set_place("moving")
        schedule = self.schedule
        blackboard = self.decision.blackboard
        row = schedule.current()
        if row is None:
            self._release_turret_routine(blackboard)
            return
        from app._04_decision.world_nav.session import live_pose_from_state

        pose = live_pose_from_state(world)
        if pose is None:
            return
        scratch = blackboard.scratch
        scratch["party_rally_wait"] = False
        # After the stand, a new party route walks. Scroll and NPC teleport
        # already ran to reach that stand. Inside the farm, later marks may
        # scroll again.
        if (
            rally is not None
            and bool(getattr(rally, "stood", False))
            and bool(getattr(rally, "done", False))
        ):
            if self._inside(row, pose):
                scratch.pop("party_rally_walk_only", None)
            else:
                scratch["party_rally_walk_only"] = True
        scratch.pop("routine_cursor", None)
        scratch["party_point_arrival"] = self._on_point_arrival
        # Arrived turret stays the hunt. A step outside the 5×5 walks back
        # through that module. It does not open another world-nav route.
        point_held = self._point_routine_held(blackboard)
        border_held = self._area_border_held(blackboard)
        if point_held or border_held:
            self._drop_open_travel(scratch)
        now = time.monotonic()
        if rally is not None and str(getattr(rally, "state", "") or "") == "waiting":
            scratch["party_rally_wait"] = True
            inside = self._inside(row, pose)
            # Already inside the farm, with no teleporter on the route: hunt
            # from this tile after the stand. A teleporter route, and a walk
            # that has not entered the farm, keeps the plan so it can resume.
            if inside and not bool(getattr(rally, "had_teleport", False)):
                self._drop_open_travel(scratch)
            schedule.note_inside(now, inside, holding=True)
            schedule.note_mark(now, inside, holding=True)
            if schedule.dungeon_plan():
                schedule.note_plan_stage(now, running=False, at_point=False)
            self._mount(blackboard, row)
            return
        if not point_held and self._travel_active(scratch):
            if (
                not self._release_stale_party_walk(scratch, pose)
                and not schedule.dungeon_plan()
            ):
                return
        if not point_held and self._rally_walk_pending(rally, row, pose):
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            if schedule.dungeon_plan():
                schedule.note_plan_stage(now, running=False, at_point=False)
            self._set_place("moving")
            self._arm_travel(blackboard, world, pose)
            return
        if schedule.dungeon_plan():
            self._drive_dungeon_plan(world, row, pose, now)
            return
        if self._inside(row, pose):
            scratch.pop("party_area_border", None)
            self._apply_place(row, pose)
            if self.hunt_mode == "turret":
                self._hold_turret_routine(blackboard)
            self._mount(blackboard, row)
            schedule.note_inside(now, True)
            schedule.note_mark(now, True)
            if schedule.due(now) and schedule.advance():
                self._mounted = None
                self._set_place("moving")
                self._clear_travel(scratch)
                self._release_turret_routine(blackboard)
                self._arm_travel(blackboard, world, pose)
                return
            if schedule.mark_due(now) and schedule.advance_mark():
                self._set_place("moving")
                self._clear_travel(scratch)
                self._release_turret_routine(blackboard)
                self._arm_travel(blackboard, world, pose)
                return
            self._clear_travel(scratch)
            self._farm(blackboard)
            return
        if point_held:
            self._pin_point_anchor(row, pose)
            self._mount(blackboard, row)
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            self._farm(blackboard)
            return
        # Still on the way to the dot. A fight outside the 5×5 finishes, then
        # the route to the point starts.
        if self._finish_point_target(world, row, pose):
            self._pin_point_anchor(row, pose)
            self._mount(blackboard, row)
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            self._clear_travel(scratch)
            self._farm(blackboard)
            return
        if border_held:
            self._mount(blackboard, row)
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            self._farm(blackboard)
            return
        schedule.note_inside(now, False)
        schedule.note_mark(now, False)
        self._arm_travel(blackboard, world, pose)

    def _rally_walk_pending(self, rally: Any, row: dict[str, Any], pose: Any) -> bool:
        """Start-rally still owes the walk that reveals the meet tile."""
        del row
        if rally is None or str(getattr(rally, "state", "") or "") != "await_mark":
            return False
        return not self._at_meet(rally, pose)

    def _at_meet(self, rally: Any, pose: Any) -> bool:
        """True within one tile of the meet tile chosen from the route."""
        point = getattr(rally, "meet", None)
        if point is None:
            return False
        try:
            if int(pose.map_id) != int(point[0]):
                return False
            gap = max(
                abs(int(pose.x) - int(point[1])),
                abs(int(pose.y) - int(point[2])),
            )
        except (TypeError, ValueError, AttributeError):
            return False
        return gap <= 1

    def _hold_turret_routine(self, blackboard: Any) -> None:
        from app._04_decision.behaviors.party_turret import hold_turret_routine

        hold_turret_routine(blackboard)

    def _point_routine_held(self, blackboard: Any) -> bool:
        """True after this point was arrived, until its time ends."""
        mark = self.schedule.current_mark()
        if mark is None or str(mark.get("shape") or "") != "point":
            return False
        from app._04_decision.behaviors.party_turret import turret_routine_held

        return turret_routine_held(blackboard)

    @staticmethod
    def _drop_open_travel(scratch: dict) -> None:
        """Drop a route that the arrived turret must not keep walking."""
        scratch.pop("world_nav_session", None)
        scratch.pop("need_world_nav", None)

    def _release_turret_routine(self, blackboard: Any) -> None:
        from app._04_decision.behaviors.party_turret import release_turret_routine

        release_turret_routine(blackboard)

    def _set_place(
        self,
        mode: str,
        *,
        on_area: bool = False,
        anchor: Optional[tuple[int, int]] = None,
    ) -> None:
        self.hunt_mode = "turret" if mode == "turret" else "moving"
        self.on_area = bool(on_area) and self.hunt_mode != "turret"
        self.turret_anchor = anchor if self.hunt_mode == "turret" else None

    def _on_point_arrival(self, blackboard: Any, reason: str) -> bool:
        """Arm turret when a party-point walk ends inside that dot's 5×5.

        ``prepare`` already returned while the walk was still active, so the
        farming handoff in this same tick would otherwise enter the previous
        mark. The flag is set before that handoff.
        """
        if str(reason or "") != "party_schedule":
            return False
        self._note_area_border(blackboard)
        row = self.schedule.current()
        if row is None:
            return False
        origin = getattr(blackboard, "world_origin", None)
        if origin is None:
            return False
        from app._04_decision.behaviors.party_turret import set_party_turret
        from app._04_decision.world_nav import pack_ids
        from app._06_party.leader_schedule import POINT_BOX_TILES, mark_center

        if self.schedule.dungeon_plan():
            if str((self.schedule.current_plan_entry() or {}).get("type") or "") != "point":
                return False
            center = self.schedule.plan_point_xy()
            if center is None:
                return False
            ax, ay = center
        else:
            mark = self.schedule.current_mark()
            if mark is None or str(mark.get("shape") or "") != "point":
                return False
            ax, ay = mark_center(mark)
        try:
            gap = max(abs(int(origin.x) - ax), abs(int(origin.y) - ay))
        except (TypeError, ValueError):
            return False
        if gap > int(POINT_BOX_TILES):
            return False
        mid = pack_ids.pack_id_to_map_id(str(row.get("map_id") or ""))
        if mid is None:
            return False
        self._set_place("turret", anchor=(ax, ay))
        set_party_turret(
            blackboard,
            True,
            map_id=int(mid),
            anchor=(ax, ay),
        )
        self._hold_turret_routine(blackboard)
        return True

    def _note_area_border(self, blackboard: Any) -> None:
        """Remember a walk that ended one tile outside the current area.

        The walk is already finished by the one-tile arrival rule. The same
        mark is not armed again while that arrival is still the route. Entering
        the area clears it. A point mark keeps its own 5×5 hold.
        """
        row = self.schedule.current()
        mark = self.schedule.current_mark()
        if row is None or mark is None or str(mark.get("shape") or "") == "point":
            return
        goal = self.schedule.goal_nav()
        origin = getattr(blackboard, "world_origin", None)
        if goal is None or origin is None:
            return
        from app._04_decision.world_nav.session import ARRIVE_TILES

        try:
            gap = max(
                abs(int(origin.x) - int(goal[1])),
                abs(int(origin.y) - int(goal[2])),
            )
        except (TypeError, ValueError):
            return
        if gap > int(ARRIVE_TILES):
            return
        blackboard.scratch["party_area_border"] = (
            str(row.get("map_id") or ""),
            int(self.schedule.index),
            int(self.schedule.mark_index),
            int(goal[1]),
            int(goal[2]),
        )
        _log.info(
            "party schedule border hold goal=%s,%s at=%s,%s",
            int(goal[1]),
            int(goal[2]),
            int(origin.x),
            int(origin.y),
        )

    def _area_border_held(self, blackboard: Any) -> bool:
        """True after this area's walk arrived on the tile just outside it."""
        scratch = getattr(blackboard, "scratch", None)
        if not isinstance(scratch, dict):
            return False
        held = scratch.get("party_area_border")
        row = self.schedule.current()
        mark = self.schedule.current_mark()
        goal = self.schedule.goal_nav()
        if row is None or mark is None or goal is None or not isinstance(held, tuple):
            scratch.pop("party_area_border", None)
            return False
        if str(mark.get("shape") or "") == "point":
            scratch.pop("party_area_border", None)
            return False
        current = (
            str(row.get("map_id") or ""),
            int(self.schedule.index),
            int(self.schedule.mark_index),
            int(goal[1]),
            int(goal[2]),
        )
        if tuple(held) != current:
            scratch.pop("party_area_border", None)
            return False
        return True

    def _apply_place(self, row: dict[str, Any], pose: Any) -> None:
        """Turret inside a dot's 5×5. An area is moving hunt. Travel stays moving."""
        nav = self._nav_xy(str(row.get("map_id") or ""), pose)
        if nav is None:
            self._set_place("moving")
            return
        mark = self.schedule.current_mark()
        if mark is not None and str(mark.get("shape") or "") == "point":
            from app._06_party.leader_schedule import mark_center

            self._set_place("turret", anchor=mark_center(mark))
            return
        self._set_place("moving", on_area=True)

    def _pin_point_anchor(self, row: dict[str, Any], pose: Any) -> None:
        """Keep the current dot as the turret center while a fight outside its box ends."""
        del row, pose
        from app._06_party.leader_schedule import mark_center

        mark = self.schedule.current_mark()
        if mark is None:
            self._set_place("moving")
            return
        self._set_place("turret", anchor=mark_center(mark))

    def _finish_point_target(self, world: Any, row: dict[str, Any], pose: Any) -> bool:
        """True when the current mark is a dot and its monster is still alive."""
        mark = self.schedule.current_mark()
        if mark is None or str(mark.get("shape") or "") != "point":
            return False
        if not self._on_row_map(row, pose):
            return False
        nav = self._nav_xy(str(row.get("map_id") or ""), pose)
        if nav is None or self.schedule.inside_current_nav(nav[0], nav[1]):
            return False
        return self._hunt_target_alive(world)

    def _inside(self, row: dict[str, Any], pose: Any) -> bool:
        if not self._on_row_map(row, pose):
            return False
        marks = self.schedule.marks()
        if not marks:
            return True
        nav = self._nav_xy(str(row.get("map_id") or ""), pose)
        if nav is None:
            return False
        return self.schedule.inside_current_nav(nav[0], nav[1])

    def _on_row_map(self, row: dict[str, Any], pose: Any) -> bool:
        from app._04_decision.world_nav import pack_ids

        mid = pack_ids.pack_id_to_map_id(str(row.get("map_id") or ""))
        if mid is None:
            return False
        try:
            return int(pose.map_id) == int(mid)
        except (TypeError, ValueError, AttributeError):
            return False

    def _nav_xy(self, pack_id: str, pose: Any) -> Optional[tuple[int, int]]:
        from app._04_decision.world_nav import pack_ids

        try:
            return pack_ids.abs_to_nav(pack_id, int(pose.x), int(pose.y))
        except (TypeError, ValueError, AttributeError):
            return None

    def _mark_rects(self) -> list[dict[str, int | str]]:
        from app._06_party.leader_schedule import point_farm_bounds

        rects: list[dict[str, int | str]] = []
        for mark in self.schedule.marks():
            x0, y0, x1, y1 = point_farm_bounds(mark)
            rects.append(
                {
                    "name": str(mark["name"]),
                    "region": "",
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                }
            )
        return rects

    def _farms_are_marks(self, rects: list[dict[str, int | str]]) -> bool:
        """True when the live farm list is still this row's party marks."""
        from app._04_decision.nav_config import get_farm_areas

        live = get_farm_areas()
        if len(live) != len(rects):
            return False
        for got, want in zip(live, rects):
            if (
                str(getattr(got, "name", "") or "") != str(want["name"])
                or int(got.x0) != int(want["x0"])
                or int(got.y0) != int(want["y0"])
                or int(got.x1) != int(want["x1"])
                or int(got.y1) != int(want["y1"])
            ):
                return False
        return True

    def _mount(self, blackboard: Any, row: dict[str, Any]) -> None:
        marks = self.schedule.marks()
        key = (
            str(row.get("id") or ""),
            tuple(str(mark["name"]) for mark in marks),
            int(self.schedule.mark_index),
        )
        blackboard.farm_area_index = int(self.schedule.mark_index)
        rects = self._mark_rects()
        # A map reload replaces these rects with the solo yaml. Put the
        # party marks back before the hunt tick reads the active farm.
        if self._mounted == key and self._farms_are_marks(rects):
            return
        scratch = blackboard.scratch
        cfg = scratch.get("runtime_config")
        if not isinstance(cfg, dict):
            cfg = {}
            scratch["runtime_config"] = cfg
        nav = dict(cfg.get("navigation") or {})
        nav["active_map"] = str(row.get("map_id") or "")
        if rects:
            nav["farm_areas"] = rects
            nav.pop("farm_areas_file", None)
        cfg["navigation"] = nav
        scratch["runtime_config"] = cfg
        if rects:
            from app._04_decision.nav_config import _load_farms_and_home

            _load_farms_and_home(nav)
        from app._04_decision.behaviors.search_hop import clear_search_hop

        clear_search_hop(blackboard)
        from app._04_decision import player_mode as pm

        pm.HUNT_MAP_ID = str(row.get("map_id") or "")
        scratch["routine_kind"] = str(row.get("kind") or "battle")
        blackboard.farm_area_index = int(self.schedule.mark_index)
        self._mounted = key
        mark = self.schedule.current_mark()
        _log.info(
            "party schedule row=%s map=%s mark=%s/%s name=%s",
            self.schedule.index,
            row.get("map_id"),
            self.schedule.mark_index,
            len(rects),
            "" if mark is None else mark.get("name"),
        )

    def _scroll_landing(self, scratch: dict) -> bool:
        from app._04_decision.talking_scroll import SCRATCH_SCROLL_ARRIVAL

        return bool(scratch.get(SCRATCH_SCROLL_ARRIVAL))

    def _walk_start_key(self, session: Any, step_i: int, frm: dict) -> tuple:
        try:
            mid = int(frm["mapId"])
        except (TypeError, ValueError, KeyError):
            mid = None
        try:
            xy = (int(frm["x"]), int(frm["y"]))
        except (TypeError, ValueError, KeyError):
            xy = None
        return (id(session), int(step_i), mid, xy)

    def _party_walk_from_far(self, session: Any, pose: Any) -> bool:
        """True when this walk's start has never been the live tile.

        A start the body has already stood on stays, including after the body
        walks away from it. A different map, or a same-map gap past the lag,
        is a start the body has not reached.
        """
        if str(getattr(session, "reason", "") or "") != "party_schedule":
            return False
        plan = getattr(session, "plan", None)
        steps = getattr(plan, "steps", None) or []
        try:
            step_i = int(getattr(session, "step_i", 0) or 0)
        except (TypeError, ValueError):
            return False
        if step_i < 0 or step_i >= len(steps):
            return False
        step = steps[step_i]
        if str(getattr(step, "op", "") or "") != "walk":
            return False
        detail = getattr(step, "detail", None)
        if not isinstance(detail, dict):
            return False
        frm = detail.get("from")
        if not isinstance(frm, dict):
            return False
        key = self._walk_start_key(session, step_i, frm)
        if key == self._walk_start_near:
            return False
        try:
            if int(frm.get("mapId", pose.map_id)) != int(pose.map_id):
                return True
            gap = max(
                abs(int(pose.x) - int(frm["x"])),
                abs(int(pose.y) - int(frm["y"])),
            )
        except (TypeError, ValueError, AttributeError):
            return False
        if gap > _WALK_FROM_LAG_TILES:
            return True
        self._walk_start_near = key
        return False

    def _release_stale_party_walk(self, scratch: dict, pose: Any) -> bool:
        """Drop a party walk whose start the body has never reached.

        The first second matches the gate-lag idle in ``_start_walk``. After
        that the live tile is the landing, so the next ``prepare`` arms from it.
        A walk that already began on the live tile is left to finish.
        """
        session = scratch.get("world_nav_session")
        if session is None or not self._party_walk_from_far(session, pose):
            self._from_far_since = 0.0
            return False
        now = time.monotonic()
        if self._from_far_since <= 0.0:
            self._from_far_since = now
            return False
        if now - self._from_far_since < _WALK_FROM_LAG_S:
            return False
        self._from_far_since = 0.0
        self._walk_start_near = None
        session.fail("party walk from is not the live tile")
        self._clear_travel(scratch)
        _log.info(
            "party schedule dropped walk from a pre-land tile at (%s,%s)",
            getattr(pose, "x", "?"),
            getattr(pose, "y", "?"),
        )
        return True

    def _arm_travel(self, blackboard: Any, world: Any, pose: Any) -> None:
        scratch = blackboard.scratch
        if self._scroll_landing(scratch):
            return
        if self._travel_active(scratch):
            return
        now = time.monotonic()
        if now < self._retry_at:
            return
        goal = self._travel_goal()
        if goal is None:
            return
        from app._04_decision.hunt_area import current_adena
        from app._04_decision.talking_scroll import talking_scroll_available
        from app._04_decision.world_nav.hooks import ensure_world_nav_mode
        from app._04_decision.world_nav.session import WorldNavSession

        session = WorldNavSession()
        try:
            adena = current_adena(world)
        except Exception:
            adena = None
        walk_only = bool(scratch.get("party_rally_walk_only"))
        ok = session.begin(
            pose,
            goal,
            reason="party_schedule",
            has_talking_scroll=False if walk_only else talking_scroll_available(),
            adena=adena,
            use_npc_teleporters=not walk_only,
        )
        if not ok:
            if bool(goal.is_satisfied(pose)):
                return
            self._retry_at = now + 5.0
            _log.info("party schedule plan failed: %s", session.error or "no plan")
            return
        scratch["world_nav_session"] = session
        scratch.pop("need_world_nav", None)
        ensure_world_nav_mode(blackboard)
        mark = self.schedule.current_mark()
        _log.info(
            "party schedule walk row=%s mark=%s name=%s steps=%s",
            self.schedule.index,
            self.schedule.mark_index,
            "" if mark is None else mark.get("name"),
            len(session.plan.steps) if session.plan else 0,
        )

    def _drive_dungeon_plan(self, world: Any, row: dict[str, Any], pose: Any, now: float) -> None:
        """Run the saved dungeon_plan entry. Legacy rows never reach this."""
        schedule = self.schedule
        blackboard = self.decision.blackboard
        scratch = blackboard.scratch
        paused = self._plan_clock_paused(world, row, pose)
        on_map = self._on_row_map(row, pose) and self._plan_map_identity_ok(row)
        nav = self._nav_xy(str(row.get("map_id") or ""), pose) if on_map else None
        schedule.note_inside(now, on_map and not paused)
        if schedule.due(now) and schedule.advance():
            self._mounted = None
            self._set_place("moving")
            self._clear_plan_motion(blackboard)
            self._release_turret_routine(blackboard)
            self._clear_plan_scratch(scratch)
            nxt = schedule.current()
            if nxt is not None and schedule.dungeon_plan():
                self._drive_dungeon_plan(world, nxt, pose, now)
            elif nxt is not None:
                self._arm_travel(blackboard, world, pose)
            return
        was_bound = schedule.patrol_waypoint_index is not None
        if nav is not None:
            schedule.bind_patrol_waypoint(nav[0], nav[1])
            if was_bound:
                schedule.note_patrol_arrival(nav[0], nav[1])
        at_point = nav is not None and schedule.point_contains(nav[0], nav[1])
        schedule.note_plan_stage(now, running=on_map and not paused, at_point=at_point)
        self._log_plan_errors()
        if not schedule.finished and schedule.stage_due(now):
            schedule.advance_plan_stage()
            self._log_plan_errors()
            self._clear_plan_motion(blackboard)
            if nav is not None:
                schedule.bind_patrol_waypoint(nav[0], nav[1])
        self._publish_plan(blackboard)
        if paused or not on_map or schedule.plan_invalid:
            # A published tile is this pack's nav grid. On another map it would
            # be a different origin, so the hop stays unpublished.
            snap = scratch.get("party_dungeon_plan")
            if isinstance(snap, dict):
                scratch["party_dungeon_plan"] = {**snap, "goal": None}
        if on_map and not paused and not schedule.plan_invalid:
            entry_now = schedule.current_plan_entry()
            kind_now = "" if entry_now is None else str(entry_now.get("type") or "")
            self._drop_plan_conflicting_walk(
                scratch,
                allow_point_walk=kind_now == "point" and not schedule.point_arrived,
            )
        if paused or not on_map or schedule.plan_invalid:
            self._release_turret_routine(blackboard)
            self._set_place("moving")
            return
        entry = schedule.current_plan_entry()
        kind = "" if entry is None else str(entry.get("type") or "")
        combat = self._hunt_target_alive(world)
        if kind == "point" and schedule.point_arrived:
            center = schedule.plan_point_xy()
            if center is not None:
                self._hold_plan_turret(blackboard, row, center)
            self._drop_open_travel(scratch)
            self._install_plan_farms(blackboard, row, self._plan_point_rects())
            self._farm(blackboard)
            return
        if combat:
            schedule.stage_state = "transition"
            self._farm(blackboard)
            return
        if kind == "point":
            self._release_turret_routine(blackboard)
            self._set_place("moving")
            self._install_plan_farms(blackboard, row, self._plan_point_rects())
            self._plan_motion = "point"
            self._arm_travel(blackboard, world, pose)
            self._plan_motion = None
            return
        self._release_turret_routine(blackboard)
        self._set_place("moving")
        self._install_plan_farms(blackboard, row, [])
        self._farm(blackboard)

    def _plan_map_identity_ok(self, row: dict[str, Any]) -> bool:
        """The active entry's pack and game map id name this row's grid.

        Live map id is compared with the row pack before any tile is read.
        An entry that names another pack or another game map id does not
        borrow this origin.
        """
        entry = self.schedule.current_plan_entry()
        if entry is None:
            return True
        from app._04_decision.world_nav import pack_ids

        row_pack = str(row.get("map_id") or "").strip()
        ident = str(entry.get("id") or self.schedule.plan_index)
        entry_pack = entry.get("pack_id")
        if isinstance(entry_pack, str) and entry_pack.strip() and entry_pack.strip() != row_pack:
            self.schedule._remember_plan_error(
                f"dungeon plan {ident} pack {entry_pack.strip()} does not match row {row_pack}"
            )
            return False
        if "game_map_id" not in entry:
            return True
        raw_game = entry.get("game_map_id")
        try:
            game_id = int(raw_game)
        except (TypeError, ValueError):
            game_id = None
        mid = pack_ids.pack_id_to_map_id(row_pack)
        if game_id is None or mid is None or isinstance(raw_game, bool) or int(mid) != game_id:
            self.schedule._remember_plan_error(
                f"dungeon plan {ident} game map {raw_game} does not match row {row_pack}"
            )
            return False
        return True

    def _plan_clock_paused(self, world: Any, row: dict[str, Any], pose: Any) -> bool:
        """Retreat, death, and a floor or map exit pause the stage clock."""
        del row, pose
        blackboard = self.decision.blackboard
        mode = getattr(blackboard, "player_mode", None)
        if str(getattr(mode, "value", mode) or "") == "retreating":
            return True
        scratch = getattr(blackboard, "scratch", None)
        if isinstance(scratch, dict) and scratch.get("post_respawn_retreat"):
            return True
        try:
            from app._04_decision.mode_control import is_hp_zero

            if is_hp_zero(world):
                return True
        except Exception:
            return False
        return False

    def _plan_point_rects(self) -> list[dict[str, int | str]]:
        from app._06_party.leader_schedule import point_farm_bounds

        center = self.schedule.plan_point_xy()
        if center is None:
            return []
        mark = {
            "name": str((self.schedule.current_plan_entry() or {}).get("name") or "point"),
            "shape": "point",
            "x0": center[0],
            "y0": center[1],
            "x1": center[0],
            "y1": center[1],
        }
        x0, y0, x1, y1 = point_farm_bounds(mark)
        return [{"name": mark["name"], "region": "", "x0": x0, "y0": y0, "x1": x1, "y1": y1}]

    def _hold_plan_turret(self, blackboard: Any, row: dict[str, Any], anchor: tuple[int, int]) -> None:
        from app._04_decision.behaviors.party_turret import set_party_turret
        from app._04_decision.world_nav import pack_ids

        self._set_place("turret", anchor=anchor)
        mid = pack_ids.pack_id_to_map_id(str(row.get("map_id") or ""))
        if mid is None:
            return
        set_party_turret(blackboard, True, map_id=int(mid), anchor=anchor)
        self._hold_turret_routine(blackboard)

    def _install_plan_farms(
        self, blackboard: Any, row: dict[str, Any], rects: list[dict[str, int | str]]
    ) -> None:
        scratch = blackboard.scratch
        cfg = scratch.get("runtime_config")
        if not isinstance(cfg, dict):
            cfg = {}
            scratch["runtime_config"] = cfg
        nav = dict(cfg.get("navigation") or {})
        nav["active_map"] = str(row.get("map_id") or "")
        nav["farm_areas"] = list(rects)
        nav.pop("farm_areas_file", None)
        cfg["navigation"] = nav
        scratch["runtime_config"] = cfg
        if rects:
            from app._04_decision.nav_config import _load_farms_and_home

            _load_farms_and_home(nav)
        from app._04_decision import player_mode as pm

        pm.HUNT_MAP_ID = str(row.get("map_id") or "")
        scratch["routine_kind"] = str(row.get("kind") or "battle")
        blackboard.farm_area_index = 0

    def _log_plan_errors(self) -> None:
        pending = list(self.schedule.plan_errors)
        if not pending:
            return
        self.schedule.plan_errors.clear()
        for message in pending:
            _log.error("%s", message)

    def _publish_plan(self, blackboard: Any) -> None:
        snap = self.schedule.motion_snapshot()
        scratch = blackboard.scratch
        previous = scratch.get("party_plan_generation")
        if snap is None:
            self._clear_plan_scratch(scratch)
            return
        scratch["party_dungeon_plan"] = snap
        scratch["party_dungeon_plan_owns_motion"] = True
        generation = snap.get("generation")
        if previous is not None and generation != previous:
            self._clear_plan_motion(blackboard)
        scratch["party_plan_generation"] = generation

    def _drop_plan_conflicting_walk(self, scratch: dict, *, allow_point_walk: bool) -> None:
        """Drop a return route that is not the active point's own walk.

        A retreat resume arms ``post_retreat`` toward the legacy mark. While a
        dungeon plan is hunting, that session must not outrank the active entry.
        The walk to the current point stays.
        """
        session = scratch.get("world_nav_session")
        reason = str(getattr(session, "reason", "") or "")
        keep_point = (
            allow_point_walk
            and session is not None
            and self._travel_active(scratch)
            and reason == "party_schedule"
        )
        if keep_point:
            # The point walk is already a session. A retreat only leaves
            # need_world_nav, and the next world-nav tick would arm that
            # over this session once the session ends.
            scratch.pop("need_world_nav", None)
            return
        if session is not None and self._travel_active(scratch):
            self._drop_open_travel(scratch)
            return
        # finish_retreat only requests the return. The session is armed on
        # the following world-nav tick, which runs before the plan hop.
        scratch.pop("need_world_nav", None)

    def _clear_plan_scratch(self, scratch: dict) -> None:
        scratch.pop("party_dungeon_plan", None)
        scratch.pop("party_dungeon_plan_owns_motion", None)
        scratch.pop("party_plan_generation", None)

    def _clear_plan_motion(self, blackboard: Any) -> None:
        """Drop the previous stage's hop so it cannot retarget the new entry."""
        self._drop_open_travel(blackboard.scratch)
        if str(getattr(blackboard, "travel_purpose", "") or "") == "patrol":
            from app._04_decision.behaviors.travel import clear_travel

            clear_travel(blackboard)
            blackboard.travel_purpose = None
        from app._04_decision.mode_control import set_mode
        from app._04_decision.player_mode import PlayerMode

        if blackboard.player_mode is PlayerMode.TRAVELING:
            set_mode(blackboard, PlayerMode.FARMING)

    def _travel_goal(self) -> Any:
        from app._04_decision.world_nav import pack_ids
        from app._04_decision.world_nav import planner_api as api

        row = self.schedule.current()
        if row is None:
            return None
        pack_id = str(row.get("map_id") or "")
        mid = pack_ids.pack_id_to_map_id(pack_id)
        if mid is None:
            return None
        if self._plan_motion == "point":
            goal_nav = self.schedule.plan_point_goal_nav()
            if goal_nav is None:
                return None
        else:
            goal_nav = self.schedule.goal_nav()
        if goal_nav is None:
            return api.map_goal(int(mid))
        _pack, nx, ny = goal_nav
        abs_xy = pack_ids.nav_to_abs(pack_id, nx, ny)
        if abs_xy is None:
            return api.map_goal(int(mid))
        return api.point_goal(int(mid), int(abs_xy[0]), int(abs_xy[1]))

    @staticmethod
    def _travel_active(scratch: dict) -> bool:
        session = scratch.get("world_nav_session")
        phase = str(getattr(session, "phase", "") or "")
        return session is not None and phase not in ("", "done", "fail", "idle")

    @staticmethod
    def _clear_travel(scratch: dict) -> None:
        session = scratch.get("world_nav_session")
        phase = str(getattr(session, "phase", "") or "")
        if phase in ("done", "fail", "idle"):
            scratch.pop("world_nav_session", None)
        scratch.pop("need_world_nav", None)

    def _hunt_target_alive(self, world: Any) -> bool:
        blackboard = self.decision.blackboard
        tid = getattr(blackboard, "current_target_id", None)
        if tid is None or world is None:
            return False
        try:
            from app._04_decision.behaviors.combat import sticky_target_alive

            return bool(sticky_target_alive(world, int(tid)))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _farm(blackboard: Any) -> None:
        from app._04_decision.mode_control import set_mode
        from app._04_decision.player_mode import PlayerMode

        if blackboard.player_mode is PlayerMode.WORLD_NAV:
            set_mode(blackboard, PlayerMode.FARMING)


__all__ = ["PartyLeaderManager"]
