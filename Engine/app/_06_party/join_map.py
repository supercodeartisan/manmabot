"""Cross-map join: WorldNav toward the leader's PartySubsystem pose."""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger("party.member")

# Re-arm if leader pose drifts this far (Chebyshev) while joining.
_REPLAN_TILES = 24


class PartyJoinNav:
    """Owns a ``WorldNavSession`` aimed at the leader's map (+ optional xy).

    The session is also stashed on ``blackboard.scratch[SCRATCH_WORLD_NAV]`` so
    gate / talking-scroll / NPC-teleporter hooks in the session loop work.
    """

    def __init__(self) -> None:
        self.session: Any = None
        self.target_key: Optional[tuple[int, Optional[int], Optional[int]]] = None
        self.last_error: str = ""
        self._blackboard: Any = None

    @property
    def active(self) -> bool:
        sess = self.session
        return sess is not None and bool(getattr(sess, "active", False))

    def clear(self) -> None:
        self._drop_scratch_session()
        self.session = None
        self.target_key = None
        self.last_error = ""
        self._blackboard = None

    def _drop_scratch_session(self) -> None:
        bb = self._blackboard
        sess = self.session
        if bb is None or sess is None:
            return
        try:
            from app._04_decision.world_nav import SCRATCH_WORLD_NAV

            if bb.scratch.get(SCRATCH_WORLD_NAV) is sess:
                bb.scratch.pop(SCRATCH_WORLD_NAV, None)
        except Exception:
            pass

    def _stash_session(self, blackboard: Any, session: Any) -> None:
        from app._04_decision.world_nav import SCRATCH_WORLD_NAV

        self._blackboard = blackboard
        self.session = session
        blackboard.scratch[SCRATCH_WORLD_NAV] = session

    def tick(
        self,
        game_state: Any,
        blackboard: Any,
        *,
        dest_map: int,
        dest_x: Optional[int],
        dest_y: Optional[int],
        reason: str = "party_join_leader",
    ) -> Any:
        """Advance join nav; return an ActionIntent (may be IDLE)."""
        from app._02_state.enums import ActionType
        from app._04_decision.talking_scroll import talking_scroll_available
        from app._04_decision.world_nav import planner_api as api
        from app._04_decision.world_nav.session import (
            WorldNavSession,
            live_pose_from_state,
        )

        from .types import ActionIntent

        if blackboard is None:
            return ActionIntent(
                action=ActionType.IDLE,
                reason="party_member:join_map_no_blackboard",
            )

        key = (
            int(dest_map),
            int(dest_x) if dest_x is not None else None,
            int(dest_y) if dest_y is not None else None,
        )
        need_arm = self.session is None or not getattr(self.session, "active", False)
        if not need_arm and self.target_key is not None and self.target_key != key:
            old_m, old_x, old_y = self.target_key
            if int(old_m) != int(key[0]):
                need_arm = True
            elif (
                old_x is not None
                and old_y is not None
                and key[1] is not None
                and key[2] is not None
                and max(abs(int(old_x) - int(key[1])), abs(int(old_y) - int(key[2])))
                >= _REPLAN_TILES
            ):
                need_arm = True

        if need_arm:
            pose = live_pose_from_state(game_state)
            if pose is None:
                self.last_error = "waiting_pose"
                return ActionIntent(
                    action=ActionType.IDLE,
                    priority=0.4,
                    reason="party_member:join_map_waiting_pose",
                )
            if key[1] is not None and key[2] is not None:
                goal = api.point_goal(int(key[0]), int(key[1]), int(key[2]))
            else:
                goal = api.map_goal(int(key[0]))
            adena = None
            try:
                from app._04_decision.hunt_area import current_adena

                adena = current_adena(game_state)
            except Exception:
                adena = None
            session = WorldNavSession()
            ok = session.begin(
                pose,
                goal,
                reason=reason,
                has_talking_scroll=talking_scroll_available(),
                adena=adena,
            )
            if not ok:
                self._drop_scratch_session()
                self.session = None
                self.target_key = None
                self.last_error = str(session.error or "plan_fail")
                _log.warning("party join map plan fail: %s", self.last_error)
                return ActionIntent(
                    action=ActionType.IDLE,
                    priority=0.4,
                    reason=f"party_member:join_map_fail {self.last_error}",
                )
            self._stash_session(blackboard, session)
            self.target_key = key
            self.last_error = ""
            _log.info(
                "party join map armed map=%s xy=%s,%s steps=%s",
                key[0],
                key[1],
                key[2],
                len(session.plan.steps) if session.plan else 0,
            )

        blackboard.intent = None
        status = self.session.tick(game_state, blackboard)
        phase = str(getattr(self.session, "phase", "") or "")
        if phase == "done":
            self.clear()
            return ActionIntent(
                action=ActionType.IDLE,
                priority=0.3,
                reason="party_member:join_map_arrived",
            )
        if phase == "fail":
            err = str(getattr(self.session, "error", None) or "nav_fail")
            self.clear()
            self.last_error = err
            return ActionIntent(
                action=ActionType.IDLE,
                priority=0.4,
                reason=f"party_member:join_map_fail {err}",
            )
        intent = getattr(blackboard, "intent", None)
        if intent is not None:
            why = str(getattr(intent, "reason", "") or "")
            if not why.startswith("party_member:"):
                try:
                    intent.reason = f"party_member:join_map {why}".strip()
                except Exception:
                    pass
            return intent
        _ = status
        return ActionIntent(
            action=ActionType.IDLE,
            priority=0.4,
            reason="party_member:join_map_tick",
        )


__all__ = ["PartyJoinNav"]
