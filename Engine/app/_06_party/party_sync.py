"""One leader snapshot for policy and rally. Not a second rally state machine.

The phase is read from ``LeaderStartRally``. ``rev`` moves only when the
member-facing snapshot changes. A retransmit keeps the same number.
"""
from __future__ import annotations

from typing import Any, Optional

SYNC = "party_sync"
_CLICKS = frozenset({"use_talking_scroll", "teleport", "shop_run"})


def rally_phase(start: Any) -> str:
    """``pending`` until the meet tile exists, then ``active``, then ``done``.

    An empty roster never stays pending: there is no meet to wait for.
    """
    if start is None:
        return "done"
    state = str(getattr(start, "state", "") or "off")
    expected = getattr(start, "expected", None) or set()
    if state == "done" or state == "off":
        return "done" if state == "done" or not expected else "pending"
    if state == "waiting" and getattr(start, "meet", None) is not None:
        return "active"
    return "pending"


def rally_point(start: Any) -> Optional[tuple[int, int, int]]:
    if rally_phase(start) != "active":
        return None
    meet = getattr(start, "meet", None)
    if not isinstance(meet, tuple) or len(meet) < 3:
        return None
    return (int(meet[0]), int(meet[1]), int(meet[2]))


class LeaderSync:
    """The snapshot the leader sends. ACK tracks retransmit, not the deadline."""

    def __init__(self) -> None:
        self.rev = 0
        self.run = "running"
        self._sig: Optional[tuple] = None
        self._acked: dict[str, tuple[str, int]] = {}

    def observe(self, session: str, policy_id: str, start: Any) -> dict[str, Any]:
        phase = rally_phase(start)
        point = rally_point(start)
        sig = (str(session or ""), self.run, str(policy_id or ""), phase, point)
        if sig != self._sig:
            self._sig = sig
            self.rev += 1
        return self.body(session, policy_id, start)

    def body(self, session: str, policy_id: str, start: Any) -> dict[str, Any]:
        phase = rally_phase(start)
        body: dict[str, Any] = {
            "type": SYNC,
            "from": "leader",
            "session": str(session or ""),
            "rev": int(self.rev),
            "run": self.run,
            "policy_id": str(policy_id or ""),
            "rally": phase,
        }
        point = rally_point(start)
        if point is not None:
            body["map_id"], body["x"], body["y"] = point
        return body

    def note_ack(self, name: str, session: str, rev: Any) -> None:
        key = str(name or "").strip().casefold()
        if not key:
            return
        try:
            seen = int(rev)
        except (TypeError, ValueError):
            return
        self._acked[key] = (str(session or ""), seen)

    def needs_send(self, name: str, session: str) -> bool:
        key = str(name or "").strip().casefold()
        got = self._acked.get(key)
        return got != (str(session or ""), int(self.rev))

    def pause(self, start: Any, now: float) -> None:
        if self.run == "paused":
            return
        freeze = getattr(start, "freeze", None)
        if callable(freeze):
            freeze(now)
        self.run = "paused"

    def resume(self, start: Any, now: float) -> None:
        if self.run != "paused":
            return
        thaw = getattr(start, "thaw", None)
        if callable(thaw):
            thaw(now)
        self.run = "running"


def roster_has(policy: Optional[dict], name: str) -> Optional[bool]:
    """None when no policy has arrived. False when the name is not on it."""
    if not isinstance(policy, dict):
        return None
    roster = policy.get("roster")
    if not isinstance(roster, list):
        return None
    key = str(name or "").strip().casefold()
    if not key:
        return False
    for row in roster:
        if isinstance(row, dict):
            text = str(row.get("name") or "")
        else:
            text = str(row or "")
        if text.strip().casefold() == key:
            return True
    return False


def _policy_matches(policy: Any, body: dict) -> bool:
    """True when this policy and snapshot are the same session and policy id."""
    if not isinstance(policy, dict) or not isinstance(body, dict):
        return False
    if str(policy.get("policy_id") or "") != str(body.get("policy_id") or ""):
        return False
    if not str(policy.get("policy_id") or ""):
        return False
    left = str(policy.get("session") or "")
    right = str(body.get("session") or "")
    return not left or not right or left == right


def consider_sync(
    orders: Any,
    *,
    name: str,
    on_roster: Optional[bool],
) -> str:
    """Apply a stored ``party_sync`` once its policy pair and roster are known.

    Returns ``applied``, ``held``, ``dropped``, ``stale``, or ``none``.
    A lower rev in the same session does not replace a newer one. The applied
    ACK is withheld until the matching policy and snapshot are both in hand.
    """
    body = getattr(orders, "sync_frame", None)
    if not isinstance(body, dict):
        return "none"
    policy = getattr(orders, "policy", None)
    if not _policy_matches(policy, body):
        # A newer policy must not keep the previous snapshot's permission.
        applied_pid = str(getattr(orders, "applied_policy_id", "") or "")
        current_pid = str(policy.get("policy_id") or "") if isinstance(policy, dict) else ""
        if current_pid and current_pid != applied_pid:
            orders.leader_run = ""
        return "held"
    if on_roster is None:
        return "held"
    if on_roster is False:
        orders.sync_frame = None
        orders.gather = None
        orders.formation_path = None
        orders.party_focus = None
        orders.leader_run = ""
        orders.applied_sync = None
        orders.applied_policy_id = ""
        orders.sync_excluded = True
        return "dropped"
    orders.sync_excluded = False
    session = str(body.get("session") or "")
    try:
        rev = int(body.get("rev"))
    except (TypeError, ValueError):
        return "stale"
    applied = getattr(orders, "applied_sync", None)
    if (
        isinstance(applied, tuple)
        and applied[0] == session
        and int(applied[1]) > rev
    ):
        return "stale"
    run = str(body.get("run") or "running")
    if run not in ("running", "paused"):
        run = "running"
    orders.leader_run = run
    phase = str(body.get("rally") or "")
    if phase == "active":
        try:
            map_id = int(body.get("map_id"))
            x = int(body.get("x"))
            y = int(body.get("y"))
        except (TypeError, ValueError):
            return "stale"
        current = getattr(orders, "gather", None)
        same = (
            isinstance(current, dict)
            and int(current.get("map_id")) == map_id
            and int(current.get("x")) == x
            and int(current.get("y")) == y
            and str(current.get("session") or "") == session
            and int(current.get("rev") or -1) == rev
        )
        if not same:
            orders.gather = {
                "type": "rally",
                "from": "leader",
                "stage": "start",
                "session": session,
                "rev": rev,
                "map_id": map_id,
                "x": x,
                "y": y,
            }
            orders.arrived = False
            orders._reported = False
            orders._report_pending = False
    elif phase == "done" or phase == "pending":
        orders.gather = None
        orders.arrived = False
        orders._reported = False
        orders._report_pending = False
    orders.applied_sync = (session, rev)
    orders.applied_phase = phase
    orders.applied_policy_id = str(policy.get("policy_id") or "")
    return "applied"


def hold_special_move(order: Optional[dict], issued: Any, session: Any) -> bool:
    """Hold a second scroll or teleport on the same destination and step.

    The leader rev is not part of this. Pause and resume must not look like a
    new command. A later step, a new meet tile, or a failed session may click.
    """
    if not isinstance(order, dict) or not isinstance(issued, dict):
        return False
    try:
        dest = (int(order.get("map_id")), int(order.get("x")), int(order.get("y")))
        old = issued.get("dest")
        if not isinstance(old, tuple) or tuple(int(v) for v in old) != dest:
            return False
        step = int(getattr(session, "step_i", 0) or 0)
        if step != int(issued.get("step") or 0):
            return False
    except (TypeError, ValueError):
        return False
    phase = str(getattr(session, "phase", "") or "")
    if phase == "fail":
        return False
    return True


def same_rally_click(order: Optional[dict], issued: Any) -> bool:
    if not isinstance(order, dict) or not isinstance(issued, tuple) or len(issued) < 5:
        return False
    try:
        return (
            str(order.get("session") or "") == issued[0]
            and int(order.get("rev")) == int(issued[1])
            and int(order.get("map_id")) == int(issued[2])
            and int(order.get("x")) == int(issued[3])
            and int(order.get("y")) == int(issued[4])
        )
    except (TypeError, ValueError, IndexError):
        return False


def click_name(intent: Any) -> str:
    token = getattr(intent, "action", None)
    return str(getattr(token, "value", None) or token or "")


__all__ = [
    "LeaderSync",
    "SYNC",
    "click_name",
    "consider_sync",
    "hold_special_move",
    "rally_phase",
    "rally_point",
    "roster_has",
    "same_rally_click",
    "_CLICKS",
]
