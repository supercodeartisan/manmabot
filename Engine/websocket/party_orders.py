"""Party orders the leader sends the moment it decides, and the rally that follows.

Hunt move (``hunt_move``): the chosen NPC teleporter. Members gather on that
NPC. The leader does not click it until those members report they are there.

Recovery (``recovery``): mother-tree decision. Sent immediately. Members do not
act on it yet.
"""
from __future__ import annotations

from typing import Any, Optional

HUNT_MOVE = "hunt_move"
RECOVERY = "recovery"
REPORT = "report"

# Same band as the NPC click (already standing on the teleporter).
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


def hunt_message_from_detail(detail: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Build ``hunt_move`` for one planned ``npc_teleporter`` step."""
    if not isinstance(detail, dict):
        return None
    frm = detail.get("from") or {}
    try:
        x = int(frm.get("x"))
        y = int(frm.get("y"))
        map_id = int(detail.get("land_map_id") or frm.get("mapId"))
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0:
        return None
    gate = detail.get("destination_dungeon")
    try:
        gate_to = int(gate) if gate not in (None, "") else None
    except (TypeError, ValueError):
        gate_to = None
    if gate_to is not None and gate_to <= 0:
        gate_to = None
    action = str(detail.get("behavior_id") or "").strip() or "npc_teleporter"
    return leader_message(
        kind=HUNT_MOVE,
        action=action,
        map_id=map_id,
        x=x,
        y=y,
        gate_to=gate_to,
        gate_edge=str(detail.get("gate_edge_id") or ""),
        destination=[x, y],
    )


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


def first_npc_step(plan: Any) -> Any:
    steps = getattr(plan, "steps", None) or []
    for step in steps:
        if str(getattr(step, "op", "") or "") == "npc_teleporter":
            return step
    return None


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


class HuntRally:
    """One NPC gather. The click waits until expected members have arrived."""

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

    def arm(self, body: dict[str, Any]) -> bool:
        """Remember and send. False when this is the same NPC already announced."""
        key = (
            str(body.get("action") or ""),
            body.get("map_id"),
            body.get("x"),
            body.get("y"),
        )
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


def _report_at_rally(order: dict[str, Any], report: dict[str, Any]) -> bool:
    if bool(report.get("arrived")):
        return True
    try:
        if int(report.get("map_id")) != int(order.get("map_id")):
            return False
        dist = _chev(
            int(report.get("x")),
            int(report.get("y")),
            int(order.get("x")),
            int(order.get("y")),
        )
    except (TypeError, ValueError):
        return False
    return dist <= ARRIVE_TILES


class MemberOrders:
    """Hunt-move order the member is walking to. Recovery is stored and ignored."""

    def __init__(self) -> None:
        self.hunt: Optional[dict[str, Any]] = None
        self.recovery: Optional[dict[str, Any]] = None
        self.arrived = False
        self._reported = False
        self._report_pending = False

    def clear(self) -> None:
        self.hunt = None
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
            if kind != HUNT_MOVE:
                continue
            key = (
                str(body.get("action") or ""),
                body.get("map_id"),
                body.get("x"),
                body.get("y"),
            )
            prev = None
            if self.hunt is not None:
                prev = (
                    str(self.hunt.get("action") or ""),
                    self.hunt.get("map_id"),
                    self.hunt.get("x"),
                    self.hunt.get("y"),
                )
            if key != prev:
                self.hunt = dict(body)
                self.arrived = False
                self._reported = False
                self._report_pending = False

    def near(self, map_id: Optional[int], x: Any, y: Any) -> bool:
        order = self.hunt
        if order is None:
            return False
        try:
            if int(map_id) != int(order.get("map_id")):
                return False
            dist = _chev(int(x), int(y), int(order.get("x")), int(order.get("y")))
        except (TypeError, ValueError):
            return False
        return dist <= ARRIVE_TILES

    def mark_arrived(self) -> bool:
        """True the first time this order is reached (caller should report)."""
        if self.hunt is None or self._reported:
            self.arrived = self.hunt is not None
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


hunt_rally = HuntRally()
member_orders = MemberOrders()


def note_hunt_plan(plan: Any) -> None:
    step = first_npc_step(plan)
    if step is None:
        return
    detail = getattr(step, "detail", None) or {}
    body = hunt_message_from_detail(detail)
    if body is not None:
        hunt_rally.arm(body)


def npc_click_allowed(detail: dict[str, Any], *, connected: int, names: set[str]) -> bool:
    """Arm the rally if the plan hook missed it, then say whether the click may run."""
    body = hunt_message_from_detail(detail)
    if body is not None:
        hunt_rally.arm(body)
    return hunt_rally.ready(connected, names)


def reset_orders() -> None:
    hunt_rally.clear()
    member_orders.clear()


__all__ = [
    "ARRIVE_TILES",
    "HUNT_MOVE",
    "RECOVERY",
    "REPORT",
    "HuntRally",
    "MemberOrders",
    "hunt_message_from_detail",
    "hunt_rally",
    "leader_message",
    "member_orders",
    "note_hunt_plan",
    "npc_click_allowed",
    "party_member_names",
    "recovery_message",
    "reset_orders",
    "self_name_from_party",
]
