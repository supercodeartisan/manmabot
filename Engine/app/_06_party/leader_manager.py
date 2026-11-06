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
        if self._travel_active(scratch):
            return
        now = time.monotonic()
        if self._inside(row, pose):
            self._apply_place(row, pose)
            self._mount(blackboard, row)
            if rally is not None and getattr(rally, "state", "") == "await_mark":
                rally.note_arrived(self._arrival_point(row, pose))
            holding = rally is not None and getattr(rally, "state", "") == "waiting"
            schedule.note_inside(now, True, holding=holding)
            if not holding and schedule.due(now) and schedule.advance():
                self._mounted = None
                self._set_place("moving")
                self._clear_travel(scratch)
                self._arm_travel(blackboard, world, pose)
                return
            self._clear_travel(scratch)
            self._farm(blackboard)
            return
        schedule.note_inside(now, False)
        self._arm_travel(blackboard, world, pose)

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

    def _apply_place(self, row: dict[str, Any], pose: Any) -> None:
        """Turret on a point tile. An area is moving hunt. Travel stays moving."""
        nav = self._nav_xy(str(row.get("map_id") or ""), pose)
        if nav is None:
            self._set_place("moving")
            return
        place = self.schedule.place_nav(nav[0], nav[1])
        if place == "point":
            self._set_place("turret", anchor=self._point_anchor(row, nav, pose))
            return
        self._set_place("moving", on_area=place == "area")

    def _point_anchor(
        self,
        row: dict[str, Any],
        nav: tuple[int, int],
        pose: Any,
    ) -> tuple[int, int]:
        from app._04_decision.world_nav import pack_ids

        abs_xy = pack_ids.nav_to_abs(str(row.get("map_id") or ""), int(nav[0]), int(nav[1]))
        if abs_xy is not None:
            return int(abs_xy[0]), int(abs_xy[1])
        return int(pose.x), int(pose.y)

    def _inside(self, row: dict[str, Any], pose: Any) -> bool:
        if not self._on_row_map(row, pose):
            return False
        marks = self.schedule.marks()
        if not marks:
            return True
        nav = self._nav_xy(str(row.get("map_id") or ""), pose)
        if nav is None:
            return False
        return self.schedule.inside_nav(nav[0], nav[1])

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
        )
        if self._mounted == key:
            return
        rects = [
            {
                "name": str(mark["name"]),
                "region": "",
                "x0": int(mark["x0"]),
                "y0": int(mark["y0"]),
                "x1": int(mark["x1"]),
                "y1": int(mark["y1"]),
            }
            for mark in marks
        ]
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
        from app._04_decision import player_mode as pm

        pm.HUNT_MAP_ID = str(row.get("map_id") or "")
        scratch["routine_kind"] = str(row.get("kind") or "battle")
        blackboard.farm_area_index = 0
        self._mounted = key
        _log.info(
            "party schedule row=%s map=%s marks=%s",
            self.schedule.index,
            row.get("map_id"),
            len(rects),
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
        _log.info(
            "party schedule walk row=%s steps=%s",
            self.schedule.index,
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

    @staticmethod
    def _farm(blackboard: Any) -> None:
        from app._04_decision.mode_control import set_mode
        from app._04_decision.player_mode import PlayerMode

        if blackboard.player_mode is PlayerMode.WORLD_NAV:
            set_mode(blackboard, PlayerMode.FARMING)


__all__ = ["PartyLeaderManager"]
