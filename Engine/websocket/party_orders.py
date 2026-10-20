"""Party orders the leader sends the moment it decides, and the rally that follows.

Rally (``rally``): one gather point with a ``stage``:

- ``start``   no teleport on the way — the leader's tile at party start
- ``planned`` the planned landing of the last teleport, sent before leaving
- ``landed``  the real landing tile, sent once the leader is there

The leader waits on the point until every roster member has arrived.

Recovery (``recovery``): mother-tree decision. Sent immediately. Members do not
act on it yet.
"""
from __future__ import annotations

from typing import Any, Optional

RALLY = "rally"
RECOVERY = "recovery"
REPORT = "report"

STAGE_START = "start"
STAGE_PLANNED = "planned"
STAGE_LANDED = "landed"
RALLY_STAGES = (STAGE_START, STAGE_PLANNED, STAGE_LANDED)

# Arrival band around the gather point.
ARRIVE_TILES = 7


def _chev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def leader_message(
    *,
    kind: str,
    action: str,
    map_id: Optional[int],
    x: Optional[int],
    y: Optional[int],
    gate_to: Optional[int] = None,
    gate_edge: str = "",
    destination: Optional[list] = None,
) -> dict[str, Any]:
    """Leader frame body. ``from`` is the role, not the character name."""
    return {
        "type": str(kind),
        "from": "leader",
        "action": str(action or ""),
        "map_id": map_id,
        "x": x,
        "y": y,
        "gate_to": gate_to,
        "gate_edge": str(gate_edge or ""),
        "destination": destination,
    }


def rally_message(*, stage: str, map_id: int, x: int, y: int) -> dict[str, Any]:
    if stage not in RALLY_STAGES:
        raise ValueError(f"unknown rally stage {stage!r}")
    body = leader_message(
        kind=RALLY,
        action=RALLY,
        map_id=int(map_id),
        x=int(x),
        y=int(y),
        destination=[int(x), int(y)],
    )
    body["stage"] = stage
    return body


def order_tag(body: Optional[dict[str, Any]]) -> str:
    """``rally:landed`` style tag a member puts on its arrival report."""
    if not isinstance(body, dict):
        return ""
    kind = str(body.get("type") or "")
    stage = str(body.get("stage") or "")
    return f"{kind}:{stage}" if stage else kind


def recovery_message(
    *,
    map_id: Optional[int],
    x: Optional[int],
    y: Optional[int],
) -> dict[str, Any]:
    dest = [int(x), int(y)] if x is not None and y is not None else None
    return leader_message(
        kind=RECOVERY,
        action="return_to_mother_tree",
        map_id=map_id,
        x=x,
        y=y,
        destination=dest,
    )


def party_member_names(snapshot: Any) -> set[str]:
    """In-game party members except the leader. Empty when the roster is unknown."""
    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
        return set()
    names: set[str] = set()
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict) or raw.get("is_leader"):
            continue
        name = str(raw.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def self_name_from_party(snapshot: Any, map_id: Optional[int], x: Any, y: Any) -> str:
    """Party-list name of the local character, matched by map and tile."""
    if not isinstance(snapshot, dict):
        return ""
    try:
        px, py = int(x), int(y)
        mid = int(map_id) if map_id is not None else None
    except (TypeError, ValueError):
        return ""
    best = ""
    best_d = ARRIVE_TILES + 1
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        try:
            if mid is not None and int(raw.get("map_id")) != mid:
                continue
            dist = _chev(px, py, int(raw.get("x")), int(raw.get("y")))
        except (TypeError, ValueError):
            continue
        if dist < best_d:
            best = name
            best_d = dist
    return best if best_d <= ARRIVE_TILES else ""


def _publish(body: dict[str, Any]) -> int:
    from .leader_decisions import publish_body

    return int(publish_body(body) or 0)


def _order_key(body: Optional[dict[str, Any]]) -> Optional[tuple]:
    if body is None:
        return None
    return (
        order_tag(body),
        str(body.get("action") or ""),
        body.get("map_id"),
        body.get("x"),
        body.get("y"),
    )


class Rally:
    """Leader side of one gather point. The leader waits on ``ready``."""

    def __init__(self) -> None:
        self.key: Optional[tuple] = None
        self.body: Optional[dict[str, Any]] = None
        self.arrived: set[str] = set()
        self._told_clients = -1

    def clear(self) -> None:
        self.key = None
        self.body = None
        self.arrived.clear()
        self._told_clients = -1

    @property
    def armed(self) -> bool:
        return self.body is not None

    @property
    def stage(self) -> str:
        return str(self.body.get("stage") or "") if self.body is not None else ""

    def arm(self, body: dict[str, Any]) -> bool:
        """Remember and send. False when this point is already announced or no server."""
        key = _order_key(body)
        if key == self.key:
            return False
        from .leader_decisions import _server_listening

        if not _server_listening():
            return False
        self.key = key
        self.body = dict(body)
        self.arrived.clear()
        self._told_clients = -1
        sent = _publish(self.body)
        self._told_clients = sent
        return True

    def repeat_if_members_joined(self, connected: int) -> bool:
        """Send the same order again when a new client connects after the first send."""
        if not self.armed or self.body is None:
            return False
        n = max(0, int(connected))
        if n <= self._told_clients:
            return False
        sent = _publish(self.body)
        self._told_clients = max(self._told_clients, sent, n)
        return True

    def note_report(
        self,
        who: str,
        body: dict[str, Any],
        names: Optional[set[str]] = None,
    ) -> None:
        if not self.armed or self.body is None:
            return
        name = str(who or body.get("from") or "").strip()
        if not name or name == "leader":
            return
        if not _report_at_rally(self.body, body):
            return
        expected = {str(n).strip() for n in (names or set()) if str(n).strip()}
        if name == "member" and expected:
            missing = expected - self.arrived
            if len(missing) == 1:
                name = next(iter(missing))
        self.arrived.add(name)

    def note_positions(self, snapshot: Any) -> None:
        """Count party-list members already standing within reach of the point."""
        if not self.armed or self.body is None or not isinstance(snapshot, dict):
            return
        for raw in snapshot.get("members") or []:
            if not isinstance(raw, dict) or raw.get("is_leader"):
                continue
            name = str(raw.get("name") or "").strip()
            if name and _at_point(self.body, raw.get("map_id"), raw.get("x"), raw.get("y")):
                self.arrived.add(name)

    def missing(self, names: set[str]) -> list[str]:
        expected = {str(n).strip() for n in names if str(n).strip()}
        return sorted(expected - self.arrived)

    def ready(self, connected: int, names: set[str]) -> bool:
        """True when nobody is expected, or every expected member has arrived."""
        if not self.armed:
            return True
        expected = {str(n).strip() for n in names if str(n).strip()}
        if expected:
            return expected <= self.arrived
        n = max(0, int(connected))
        if n <= 0:
            return True
        return len(self.arrived) >= n


def _at_point(order: dict[str, Any], map_id: Any, x: Any, y: Any) -> bool:
    try:
        if int(map_id) != int(order.get("map_id")):
            return False
        dist = _chev(int(x), int(y), int(order.get("x")), int(order.get("y")))
    except (TypeError, ValueError):
        return False
    return dist <= ARRIVE_TILES


def _report_at_rally(order: dict[str, Any], report: dict[str, Any]) -> bool:
    # ``arrived`` refers to the member's current order; ignore it for another one.
    if bool(report.get("arrived")) and str(report.get("order") or "") == order_tag(order):
        return True
    return _at_point(order, report.get("map_id"), report.get("x"), report.get("y"))


class MemberOrders:
    """Member side: the rally point to walk to. Recovery is stored and ignored."""

    def __init__(self) -> None:
        self.gather: Optional[dict[str, Any]] = None
        self.recovery: Optional[dict[str, Any]] = None
        self.arrived = False
        self._reported = False
        self._report_pending = False

    @property
    def order_kind(self) -> str:
        return order_tag(self.gather)

    def clear(self) -> None:
        self.gather = None
        self.recovery = None
        self.arrived = False
        self._reported = False
        self._report_pending = False

    def ingest(self, frames: list[Any]) -> None:
        for frame in frames:
            body = getattr(frame, "message", None)
            if not isinstance(body, dict):
                continue
            kind = str(body.get("type") or "")
            if kind == RECOVERY:
                self.recovery = dict(body)
                continue
            if kind != RALLY:
                continue
            if _order_key(body) != _order_key(self.gather):
                self.gather = dict(body)
                self.arrived = False
                self._reported = False
                self._report_pending = False

    def near(self, map_id: Optional[int], x: Any, y: Any) -> bool:
        order = self.gather
        return order is not None and _at_point(order, map_id, x, y)

    def mark_arrived(self) -> bool:
        """True the first time this order is reached (caller should report)."""
        if self.gather is None or self._reported:
            self.arrived = self.gather is not None
            return False
        self.arrived = True
        self._reported = True
        self._report_pending = True
        return True

    def take_report(self) -> bool:
        """True once per arrival, so the session sends buffs and items immediately."""
        if not self._report_pending:
            return False
        self._report_pending = False
        return True


rally = Rally()
member_orders = MemberOrders()


def reset_orders() -> None:
    rally.clear()
    member_orders.clear()


__all__ = [
    "ARRIVE_TILES",
    "RALLY",
    "RALLY_STAGES",
    "RECOVERY",
    "REPORT",
    "STAGE_LANDED",
    "STAGE_PLANNED",
    "STAGE_START",
    "MemberOrders",
    "Rally",
    "leader_message",
    "member_orders",
    "order_tag",
    "party_member_names",
    "rally",
    "rally_message",
    "recovery_message",
    "reset_orders",
    "self_name_from_party",
]
