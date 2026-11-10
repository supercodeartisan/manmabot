"""Leader start rally: reach the party schedule mark, wait, then hunt.

The walk to the mark is not paused at the current tile or the first teleporter.
``note_arrived`` stands the leader on that mark. The stand ends when every
expected member is at the mark, or after 3 minutes. Members are not sent the
tile. Once party memory shows them in the party, they follow the leader's live tile.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from app._06_party.comms.orders import (
    STAGE_START,
    Rally,
    rally_message,
)

TELEPORT_OPS = ("npc_teleporter", "talking_scroll")
WAIT_LOG_EVERY_S = 5.0
WAIT_TIMEOUT_S = 10 * 60
# Stand on the rally mark for members, then walk into the farm.
MEMBER_WAIT_S = 3 * 60


def _steps(plan: Any) -> list:
    return list(getattr(plan, "steps", None) or [])


def _is_teleport(step: Any) -> bool:
    return str(getattr(step, "op", "") or "") in TELEPORT_OPS


def first_teleport_index(plan: Any) -> Optional[int]:
    """Index of the first NPC-teleporter / talking-scroll step, or None."""
    for i, step in enumerate(_steps(plan)):
        if _is_teleport(step):
            return i
    return None


def last_teleport_index(plan: Any) -> Optional[int]:
    """Index of the last NPC-teleporter / talking-scroll step, or None."""
    steps = _steps(plan)
    for i in range(len(steps) - 1, -1, -1):
        if _is_teleport(steps[i]):
            return i
    return None


def departure_point(step: Any) -> Optional[tuple[int, int, int]]:
    """Tile the party stands on before this teleport step runs."""
    detail = getattr(step, "detail", None) or {}
    return _point(detail.get("from"))


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
    """off → await_mark → waiting → done. The mark opens a 3 minute stand."""

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
        # Leader start-wait end (clock time); None = WAIT_TIMEOUT_S from wait start.
        self.deadline: Optional[float] = None
        # Expected names not at the rally point when the start wait ended.
        self.left_behind: list[str] = []
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

    def remaining_s(self) -> Optional[float]:
        if self.state == "waiting" and self._wait_started is not None:
            return max(0.0, self._wait_started + MEMBER_WAIT_S - self._clock())
        if self.deadline is not None:
            return max(0.0, self.deadline - self._clock())
        if self._wait_started is not None:
            return max(0.0, self._wait_started + WAIT_TIMEOUT_S - self._clock())
        return None

    def begin(
        self,
        expected: set[str],
        *,
        travel: bool,
        pose: Any,
        deadline: Optional[float] = None,
    ) -> None:
        """Party start. ``travel`` = the hunt needs a cross-map world-nav trip."""
        if self.state != "off":
            return
        if deadline is not None:
            self.deadline = float(deadline)
        self.expected = {str(n).strip() for n in expected if str(n).strip()}
        if not self.expected:
            # Stay ``off`` — ``skip()`` used to mark ``done``, so the monitor
            # painted Rally/Hunt complete while Connect was still waiting.
            self._log("Party start rally skipped — roster empty")
            return
        del travel, pose
        self.state = "await_mark"
        self._log("Party start rally walks to the party mark")

    def note_arrived(self, point: tuple[int, int, int]) -> None:
        """The leader is on the mark. Stand until the roster is here, or 3 minutes."""
        if self.state != "await_mark":
            return
        self._arm(STAGE_START, point)
        self._enter_waiting()
        self._log(
            "Party start rally at the mark — wait up to 3 min for members"
        )

    def on_plan(self, plan: Any) -> None:
        """Travel owns the route. A plan does not start this wait."""
        del plan

    def should_hold(self, step_i: int, pose: Any) -> bool:
        """The leader does not stand for members. The walk to the mark continues."""
        del step_i, pose
        return False

    def update(self, connected: int, snapshot: Any) -> None:
        """Each tick: resend if needed, count arrivals, finish when all are in."""
        if (
            self.deadline is not None
            and self.state not in ("off", "done", "waiting")
            and self._clock() >= self.deadline
        ):
            self.left_behind = self._rally.missing(self.expected)
            missing = ", ".join(self.left_behind) or "—"
            self.skip(
                f"start wait over, not arrived: {missing} — continue to the hunt "
                "(late members follow the leader)"
            )
            return
        if self.state not in ("hold_at", "waiting") or self._want is None:
            return
        self._rally.arm(self._want)
        self._rally.note_positions(snapshot)
        if self.state != "waiting":
            return
        if self._rally.armed and self._rally.ready(connected, self.expected):
            self.state = "done"
            self._log("Party start rally complete — all members here, continue to the hunt")
            return
        now = self._clock()
        started = self._wait_started
        if started is not None and now - started >= MEMBER_WAIT_S:
            self.left_behind = self._rally.missing(self.expected)
            missing = ", ".join(self.left_behind) or "—"
            self.skip(
                f"3 min wait over, not arrived: {missing} — continue to the hunt "
                "(late members follow the leader)"
            )
            return
        if now - self._log_at >= WAIT_LOG_EVERY_S:
            self._log_at = now
            missing = ", ".join(self._rally.missing(self.expected)) or "—"
            self._log(
                f"Party start rally wait {self._rally.stage} missing={missing} "
                f"ws_clients={int(connected)}"
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
    "MEMBER_WAIT_S",
    "TELEPORT_OPS",
    "WAIT_TIMEOUT_S",
    "departure_point",
    "first_teleport_index",
    "last_teleport_index",
    "plan_start",
    "planned_landing",
]
