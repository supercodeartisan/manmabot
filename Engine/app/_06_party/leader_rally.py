"""Leader start rally: where the party gathers on the first trip to the hunt.

- No teleport on the way (already on the hunt map, or a walk-only plan):
  send the leader's tile and wait there.
- Teleport on the way (NPC teleporter or talking scroll): send the planned
  landing of the last teleport, travel, then send the real landing tile and
  wait there.

Waits for every roster member, or 15 minutes, then continues. Used once per Start.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from websocket.party_orders import (
    STAGE_LANDED,
    STAGE_PLANNED,
    STAGE_START,
    Rally,
    rally_message,
)

TELEPORT_OPS = ("npc_teleporter", "talking_scroll")
WAIT_LOG_EVERY_S = 5.0
WAIT_TIMEOUT_S = 15 * 60


def last_teleport_index(plan: Any) -> Optional[int]:
    """Index of the last NPC-teleporter / talking-scroll step, or None."""
    steps = list(getattr(plan, "steps", None) or [])
    for i in range(len(steps) - 1, -1, -1):
        if str(getattr(steps[i], "op", "") or "") in TELEPORT_OPS:
            return i
    return None


def _point(raw: Any) -> Optional[tuple[int, int, int]]:
    if not isinstance(raw, dict):
        return None
    try:
        return int(raw["mapId"]), int(raw["x"]), int(raw["y"])
    except (KeyError, TypeError, ValueError):
        return None


def planned_landing(step: Any) -> Optional[tuple[int, int, int]]:
    """Planned ``to`` tile of a teleport step (map, x, y)."""
    return _point((getattr(step, "detail", None) or {}).get("to"))


def plan_start(plan: Any) -> Optional[tuple[int, int, int]]:
    return _point((getattr(plan, "meta", None) or {}).get("start"))


class LeaderStartRally:
    """off → await_plan → hold_at → waiting → done (or off → waiting → done)."""

    def __init__(
        self,
        rally: Rally,
        *,
        log: Callable[[str], None] = lambda _m: None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rally = rally
        self._log = log
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.state = "off"
        self.expected: set[str] = set()
        self.hold_step: Optional[int] = None
        self._want: Optional[dict[str, Any]] = None
        self._wait_started: Optional[float] = None
        self._log_at = float("-inf")
        self._rally.clear()

    def _enter_waiting(self) -> None:
        if self._wait_started is None:
            self._wait_started = self._clock()
        self.state = "waiting"

    @property
    def waiting(self) -> bool:
        return self.state == "waiting"

    @property
    def done(self) -> bool:
        return self.state == "done"

    def skip(self, why: str) -> None:
        self.state = "done"
        self._log(f"Party start rally skipped — {why}")

    def begin(self, expected: set[str], *, travel: bool, pose: Any) -> None:
        """Party start. ``travel`` = the hunt needs a cross-map world-nav trip."""
        if self.state != "off":
            return
        self.expected = {str(n).strip() for n in expected if str(n).strip()}
        if not self.expected:
            self.skip("roster empty")
            return
        if travel:
            self.state = "await_plan"
            self._log("Party start rally: waiting for the hunt route")
            return
        if pose is None:
            self.expected = set()
            return
        self._arm(STAGE_START, (int(pose.map_id), int(pose.x), int(pose.y)))
        self._enter_waiting()

    def on_plan(self, plan: Any) -> None:
        """World-nav hook: a route to the hunt exists."""
        if self.state not in ("await_plan", "hold_at"):
            return
        idx = last_teleport_index(plan)
        if idx is None:
            point = plan_start(plan)
            self.hold_step = 0
            stage = STAGE_START
        else:
            point = planned_landing(plan.steps[idx])
            self.hold_step = idx + 1
            stage = STAGE_PLANNED
        if point is None:
            self.skip("route has no rally tile")
            return
        self._arm(stage, point)
        self.state = "hold_at"

    def should_hold(self, step_i: int, pose: Any) -> bool:
        """World-nav hook before each step. True keeps the leader on the spot."""
        if self.state == "hold_at" and self.hold_step is not None and step_i >= self.hold_step:
            if self._rally.stage == STAGE_PLANNED and pose is not None:
                self._arm(STAGE_LANDED, (int(pose.map_id), int(pose.x), int(pose.y)))
            self._enter_waiting()
        return self.state == "waiting"

    def update(self, connected: int, snapshot: Any) -> None:
        """Each tick: resend if needed, count arrivals, finish when all are in."""
        if self.state not in ("hold_at", "waiting") or self._want is None:
            return
        self._rally.arm(self._want)
        self._rally.note_positions(snapshot)
        if self.state != "waiting":
            return
        if self._rally.armed and self._rally.ready(connected, self.expected):
            self.state = "done"
            self._log("Party start rally complete — continue to the hunt")
            return
        now = self._clock()
        started = self._wait_started
        if started is not None and now - started >= WAIT_TIMEOUT_S:
            mins = int(WAIT_TIMEOUT_S // 60)
            self.skip(f"wait timed out ({mins} min)")
            return
        if now - self._log_at >= WAIT_LOG_EVERY_S:
            self._log_at = now
            missing = ", ".join(self._rally.missing(self.expected)) or "—"
            armed = "" if self._rally.armed else " (not sent: party server down)"
            self._log(
                f"Party start rally wait {self._rally.stage} missing={missing} "
                f"ws_clients={int(connected)}{armed}"
            )

    def _arm(self, stage: str, point: tuple[int, int, int]) -> None:
        map_id, x, y = point
        self._want = rally_message(stage=stage, map_id=map_id, x=x, y=y)
        self._rally.arm(self._want)
        self._log(
            f"Party start rally {stage} at map{map_id} ({x},{y}) "
            f"wait {', '.join(sorted(self.expected))}"
        )


__all__ = [
    "LeaderStartRally",
    "TELEPORT_OPS",
    "WAIT_TIMEOUT_S",
    "last_teleport_index",
    "plan_start",
    "planned_landing",
]
