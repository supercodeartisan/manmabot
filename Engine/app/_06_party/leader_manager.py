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


class PartyLeaderManager:
    """Leader tick. The party document chooses the mark. Solo decide hunts it."""

    def __init__(self, decision: Any) -> None:
        self.decision = decision
        self.schedule = PartyLeaderSchedule([])
        self._mounted: Optional[tuple] = None
        self._retry_at = 0.0
        # turret only while the live tile is a party-map point.
        self.hunt_mode = "moving"
        self.on_area = False
        self.turret_anchor: Optional[tuple[int, int]] = None

    def decide(self, world: Any) -> Any:
        return self.decision.decide(world)

    def arm(self, routine: Any) -> int:
        """Keep the party document on this leader. The solo cursor stays unset."""
        self.schedule = PartyLeaderSchedule.from_routine(routine)
        self._mounted = None
        self._retry_at = 0.0
        self._set_place("moving")
        blackboard = self.decision.blackboard
        scratch = getattr(blackboard, "scratch", None)
        if isinstance(scratch, dict):
            scratch.pop("routine_cursor", None)
            scratch.pop("need_world_nav", None)
            scratch["party_point_arrival"] = self._on_point_arrival
        return len(self.schedule.rows)

    def prepare(self, world: Any, rally: Any = None) -> None:
        """Walk to the current party mark, then count the row's minutes there."""
        self._set_place("moving")
        schedule = self.schedule
        row = schedule.current()
        if row is None:
            return
        from app._04_decision.world_nav.session import live_pose_from_state

        pose = live_pose_from_state(world)
        if pose is None:
            return
        blackboard = self.decision.blackboard
        scratch = blackboard.scratch
        scratch.pop("routine_cursor", None)
        scratch["party_point_arrival"] = self._on_point_arrival
        if self._travel_active(scratch):
            return
        now = time.monotonic()
        if self._rally_walk_pending(rally, row, pose):
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            self._set_place("moving")
            self._arm_travel(blackboard, world, pose)
            return
        if self._inside(row, pose):
            self._apply_place(row, pose)
            self._mount(blackboard, row)
            if rally is not None and getattr(rally, "state", "") == "await_mark":
                rally.note_arrived(self._arrival_point(row, pose))
            holding = rally is not None and getattr(rally, "state", "") == "waiting"
            schedule.note_inside(now, True, holding=holding)
            schedule.note_mark(now, True, holding=holding)
            if not holding and schedule.due(now) and schedule.advance():
                self._mounted = None
                self._set_place("moving")
                self._clear_travel(scratch)
                self._arm_travel(blackboard, world, pose)
                return
            if not holding and schedule.mark_due(now) and schedule.advance_mark():
                self._set_place("moving")
                self._clear_travel(scratch)
                self._arm_travel(blackboard, world, pose)
                return
            self._clear_travel(scratch)
            self._farm(blackboard)
            return
        # Left the dot's 5×5 with a fight still going: finish it, then walk back.
        if self._finish_point_target(world, row, pose):
            self._pin_point_anchor(row, pose)
            self._mount(blackboard, row)
            schedule.note_inside(now, False)
            schedule.note_mark(now, False)
            self._clear_travel(scratch)
            self._farm(blackboard)
            return
        schedule.note_inside(now, False)
        schedule.note_mark(now, False)
        self._arm_travel(blackboard, world, pose)

    def _rally_walk_pending(self, rally: Any, row: dict[str, Any], pose: Any) -> bool:
        """Start-rally still owes the walk to the mark point."""
        if rally is None or str(getattr(rally, "state", "") or "") != "await_mark":
            return False
        return not self._at_rally_point(row, pose)

    def _at_rally_point(self, row: dict[str, Any], pose: Any) -> bool:
        """True within one tile of the mark point. That matches the walk arrival."""
        point = self._arrival_point(row, pose)
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
        row = self.schedule.current()
        mark = self.schedule.current_mark()
        if row is None or mark is None or str(mark.get("shape") or "") != "point":
            return False
        origin = getattr(blackboard, "world_origin", None)
        if origin is None:
            return False
        from app._04_decision.behaviors.party_turret import set_party_turret
        from app._04_decision.world_nav import pack_ids
        from app._06_party.leader_schedule import POINT_BOX_TILES, mark_center

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

    def _arrival_point(self, row: dict[str, Any], pose: Any) -> tuple[int, int, int]:
        from app._04_decision.world_nav import pack_ids

        goal = self.schedule.goal_nav()
        if goal is not None:
            pack_id, nx, ny = goal
            abs_xy = pack_ids.nav_to_abs(pack_id, nx, ny)
            mid = pack_ids.pack_id_to_map_id(pack_id)
            if abs_xy is not None and mid is not None:
                return int(mid), int(abs_xy[0]), int(abs_xy[1])
        return int(pose.map_id), int(pose.x), int(pose.y)

    def _mount(self, blackboard: Any, row: dict[str, Any]) -> None:
        marks = self.schedule.marks()
        key = (
            str(row.get("id") or ""),
            tuple(str(mark["name"]) for mark in marks),
            int(self.schedule.mark_index),
        )
        blackboard.farm_area_index = int(self.schedule.mark_index)
        if self._mounted == key:
            return
        from app._06_party.leader_schedule import point_farm_bounds

        rects = []
        for mark in marks:
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

    def _arm_travel(self, blackboard: Any, world: Any, pose: Any) -> None:
        scratch = blackboard.scratch
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
        ok = session.begin(
            pose,
            goal,
            reason="party_schedule",
            has_talking_scroll=talking_scroll_available(),
            adena=adena,
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
