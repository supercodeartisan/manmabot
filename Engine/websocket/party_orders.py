"""Party orders the leader sends the moment it decides, and the rally that follows.

Rally (``rally``): the leader's own wait point. It is not sent to members.
Members follow the leader's live party-memory tile once ``in_party`` is true.
The leader waits on the point until party memory shows every roster member
has arrived.

Recovery (``recovery``): mother-tree decision. Sent immediately. Members do not
act on it yet.

Policy (``party_policy``, leader → members) carries a ``policy_id``. A member
answers every policy frame it applied with ``policy_ack`` echoing that id; the
leader invites a roster name only once its ack matches the current id.

Invite: the leader only types ``/초대 <to>``; no socket notice. The member reads
the in-game invite popup itself, presses Y, and once the popup closed answers
``invite_accept`` (member → leader, with an ``accept_id``; sent a few times,
the leader books it once per id).

Member state (``member_state``, member → leader, every ~2 s and on change):
the member's whole view — leader session it follows, applied ``policy_id``,
its own party memory (``in_party`` / party leader / names), and the last
invite popup it handled (``popup`` / ``pressed`` / ``accepted`` / ...).
Level-triggered: a late start or a reconnect is reconciled by the next frame,
nothing depends on one edge message arriving.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Optional

RALLY = "rally"
RECOVERY = "recovery"
REPORT = "report"
POLICY = "party_policy"
POLICY_ACK = "policy_ack"
INVITE_ACCEPT = "invite_accept"
MEMBER_STATE = "member_state"
MEMBER_HELLO = "member_hello"
BEEP = "beep"

STAGE_START = "start"
STAGE_PLANNED = "planned"
STAGE_LANDED = "landed"
RALLY_STAGES = (STAGE_START, STAGE_PLANNED, STAGE_LANDED)

# Arrival band around the gather point.
ARRIVE_TILES = 7

# One id per leader Start, stamped on every leader frame (``session``). A member
# that sees a new id drops everything it kept from the previous leader run.
_leader_session = ""


def new_leader_session() -> str:
    global _leader_session
    _leader_session = uuid.uuid4().hex[:8]
    return _leader_session


def leader_session() -> str:
    return _leader_session


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


def policy_message(
    *,
    leader_mode: str = "moving",
    random_loot: bool = False,
    loot_role: str = "none",
    yard_half_w: Optional[int] = None,
    yard_half_h: Optional[int] = None,
    yard_scale_with_roster: bool = True,
    party_size: int = 1,
    roster: Optional[list] = None,
    leader_name: str = "",
) -> dict[str, Any]:
    """Global party farm knobs from the leader. Members merge into their config.

    ``leader_mode`` is turret while the leader stands on a party-map point,
    and moving on an area or while traveling. It is not a saved setting.
    Party / solo farm and follow / stop /
    assist distances are per-member and never sent. ``leader_name`` = the
    leader character; a member accepts invite popups only from it (when set).
    """
    body = leader_message(
        kind=POLICY,
        action="farm_policy",
        map_id=None,
        x=None,
        y=None,
    )
    knobs = {
        "leader_mode": "turret" if str(leader_mode or "") == "turret" else "moving",
        "random_loot": bool(random_loot),
        "loot_role": str(loot_role or "none"),
        "yard_half_w": yard_half_w,
        "yard_half_h": yard_half_h,
        "yard_scale_with_roster": bool(yard_scale_with_roster),
        "party_size": max(1, int(party_size)),
        "roster": list(roster or []),
    }
    if str(leader_name or "").strip():
        knobs["leader_name"] = str(leader_name).strip()
    body.update(knobs)
    body["policy_id"] = _policy_id(knobs)
    return body


def _policy_id(knobs: dict[str, Any]) -> str:
    raw = json.dumps(knobs, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def beep_message(*, who: str = "leader", why: str = "already_in_party") -> dict[str, Any]:
    """Link test (beep): already-formed party skips /초대 and pings the socket."""
    sender = str(who or "leader").strip() or "leader"
    return {
        "type": BEEP,
        "from": sender,
        "why": str(why or "already_in_party"),
        "at": time.time(),
    }


def policy_ack_message(
    *,
    name: str,
    policy_id: str,
    client_id: str = "",
) -> dict[str, Any]:
    """Member → leader: this policy is applied on top of the member's profile."""
    body = {
        "type": POLICY_ACK,
        "from": str(name or "member").strip() or "member",
        "policy_id": str(policy_id or ""),
        "ok": True,
    }
    cid = str(client_id or "").strip()
    if cid:
        body["client_id"] = cid
    return body


def new_invite_id() -> str:
    return uuid.uuid4().hex[:8]


def invite_accept_message(
    *,
    name: str,
    session: str,
    accept_id: str,
    inviter: str = "",
    presses: int = 0,
    client_id: str = "",
) -> dict[str, Any]:
    """Member → leader: Y closed this member's invite popup (accepted)."""
    body = {
        "type": INVITE_ACCEPT,
        "from": str(name or "member").strip() or "member",
        "session": str(session or ""),
        "accept_id": str(accept_id or ""),
        "inviter": str(inviter or ""),
        "presses": int(presses or 0),
        "at": time.time(),
    }
    cid = str(client_id or "").strip()
    if cid:
        body["client_id"] = cid
    return body


def member_hello_message(body: dict[str, Any]) -> dict[str, Any]:
    """Pass-through for a ``member_hello`` dict built by ``member_identity``."""
    return dict(body or {})


def member_state_message(
    *,
    name: str,
    session: str,
    policy_id: str,
    party: dict[str, Any],
    invite: dict[str, Any],
    seq: int,
    changed: bool,
    live: Optional[dict[str, Any]] = None,
    client_id: str = "",
) -> dict[str, Any]:
    """Member → leader: full member view (see module doc). ``changed`` = differs
    from the previous frame (the rest are keep-alive repeats). ``live`` = monitor
    extras (bot state, map, xy, hp/mp, current step)."""
    body = {
        "type": MEMBER_STATE,
        "from": str(name or "member").strip() or "member",
        "session": str(session or ""),
        "policy_id": str(policy_id or ""),
        "party": dict(party or {}),
        "invite": dict(invite or {}),
        "live": dict(live or {}),
        "seq": int(seq),
        "changed": bool(changed),
    }
    cid = str(client_id or "").strip()
    if cid:
        body["client_id"] = cid
    return body


def seat_role_for_name(roster: Any, name: str) -> str:
    """Roster seat for ``name`` (member|mage|shopkeeper). Default mage."""
    want = str(name or "").strip().casefold()
    if not want or not isinstance(roster, (list, tuple)):
        return "mage"
    for row in roster:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().casefold() != want:
            continue
        role = str(row.get("role") or "mage").strip().lower()
        return role if role in ("member", "mage", "shopkeeper") else "mage"
    return "mage"


def seat_index_for_name(roster: Any, name: str) -> Optional[int]:
    """0-based position of ``name`` among named roster rows, or None."""
    want = str(name or "").strip().casefold()
    if not want or not isinstance(roster, (list, tuple)):
        return None
    i = 0
    for row in roster:
        raw = row.get("name") if isinstance(row, dict) else row
        key = str(raw or "").strip().casefold()
        if not key:
            continue
        if key == want:
            return i
        i += 1
    return None


def loot_role_for_name(roster: Any, name: str, *, default: str = "none") -> str:
    """Per-player loot seat: none | responsible."""
    want = str(name or "").strip().casefold()
    fallback = "responsible" if str(default or "").strip().lower() == "responsible" else "none"
    if not want or not isinstance(roster, (list, tuple)):
        return fallback
    for row in roster:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().casefold() != want:
            continue
        loot = str(row.get("loot") or row.get("loot_role") or fallback).strip().lower()
        return loot if loot in ("none", "responsible") else fallback
    return fallback


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
        """Remember the wait point on this leader. Members are not told the tile."""
        key = _order_key(body)
        if key == self.key:
            return False
        self.key = key
        self.body = dict(body)
        self.arrived.clear()
        self._told_clients = -1
        return True

    def repeat_if_members_joined(self, connected: int) -> bool:
        """Members follow the live leader tile, so the wait point is not resent."""
        del connected
        return False

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
    """Member side: rally point, recovery, and leader farm policy."""

    def __init__(self) -> None:
        self.gather: Optional[dict[str, Any]] = None
        self.recovery: Optional[dict[str, Any]] = None
        self.policy: Optional[dict[str, Any]] = None
        self.arrived = False
        self._reported = False
        self._report_pending = False
        self._policy_dirty = False
        # Leader run id; a new one means the leader bot was started again.
        self.session = ""
        self.session_resets = 0
        self._session_changed = False
        self._beep: Optional[dict[str, Any]] = None

    @property
    def order_kind(self) -> str:
        return order_tag(self.gather)

    def _drop_orders(self) -> None:
        self.gather = None
        self.recovery = None
        self.policy = None
        self.arrived = False
        self._reported = False
        self._report_pending = False
        self._policy_dirty = False

    def clear(self) -> None:
        self._drop_orders()
        self.session = ""
        self.session_resets = 0
        self._session_changed = False
        self._beep = None

    def take_beep(self) -> Optional[dict[str, Any]]:
        """Leader beep once, then None until the next one."""
        body = self._beep
        self._beep = None
        return body

    def take_session_change(self) -> Optional[str]:
        """The new leader session id once after it first appears, else None."""
        if not self._session_changed:
            return None
        self._session_changed = False
        return self.session

    def take_policy(self) -> Optional[dict[str, Any]]:
        """Return the latest policy once when it changes."""
        if not self._policy_dirty or self.policy is None:
            return None
        self._policy_dirty = False
        return dict(self.policy)

    def ingest(self, frames: list[Any]) -> None:
        for frame in frames:
            body = getattr(frame, "message", None)
            if not isinstance(body, dict):
                continue
            # Other members' frames are relayed too; only the leader sets the session.
            if str(body.get("from") or "") != "leader":
                continue
            session = str(body.get("session") or "")
            if session and session != self.session:
                self._drop_orders()
                self.session = session
                self.session_resets += 1
                self._session_changed = True
            kind = str(body.get("type") or "")
            if kind == BEEP:
                self._beep = dict(body)
                continue
            if kind == RECOVERY:
                self.recovery = dict(body)
                continue
            if kind == POLICY:
                self.policy = dict(body)
                self._policy_dirty = True
                continue
            if kind == RALLY:
                # A rally pin is not a walk goal. Follow uses party memory.
                if self.gather is not None:
                    self.gather = None
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


def _roster_list(names: Optional[Any] = None) -> list[str]:
    """Stable unique roster names, preserving incoming order."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


class PolicyAcks:
    """Leader side: which roster names confirmed which ``policy_id``."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def clear(self) -> None:
        self.rows.clear()

    def note(self, who: str, body: dict[str, Any], names: Optional[Any] = None) -> str:
        """Record one ack; returns the roster name it was booked to ("" = ignored).

        A member that does not know its name yet sends ``from=member`` plus a
        stable ``client_id``. Each id is bound to the next unconfirmed roster
        name, in roster order, so two unnamed members no longer drop both acks.
        """
        name = str(who or (body or {}).get("from") or "").strip()
        if not name or name.casefold() == "leader":
            return ""
        pid = str((body or {}).get("policy_id") or "")
        client_id = str((body or {}).get("client_id") or "").strip()
        roster = _roster_list(names)
        by_key = {n.casefold(): n for n in roster}
        if name.casefold() in by_key:
            return self._store(by_key[name.casefold()], pid, client_id, named=True)
        if name.casefold() != "member" or not roster:
            return ""
        if client_id:
            for row in self.rows.values():
                if str(row.get("client_id") or "") == client_id:
                    return self._store(
                        str(row.get("name") or ""), pid, client_id, named=False
                    )
        open_names = [n for n in roster if not self.acked(n, pid)]
        if not open_names:
            return ""
        if not client_id and len(open_names) != 1:
            return ""
        return self._store(open_names[0], pid, client_id, named=False)

    def _store(
        self, name: str, pid: str, client_id: str, *, named: bool
    ) -> str:
        name = str(name or "").strip()
        if not name:
            return ""
        if client_id:
            for key, row in list(self.rows.items()):
                if str(row.get("client_id") or "") != client_id:
                    continue
                if key == name.casefold():
                    continue
                if not row.get("named"):
                    self.rows.pop(key, None)
                else:
                    row["client_id"] = ""
        prev = self.rows.get(name.casefold()) or {}
        self.rows[name.casefold()] = {
            "name": name,
            "policy_id": pid,
            "client_id": client_id or str(prev.get("client_id") or ""),
            "named": bool(named or prev.get("named")),
            "at": time.time(),
            "count": int(prev.get("count", 0)) + 1,
        }
        return name

    def acked(self, name: str, policy_id: Optional[str]) -> bool:
        row = self.rows.get(str(name or "").strip().casefold())
        if row is None:
            return False
        return policy_id is None or str(row.get("policy_id") or "") == str(policy_id)

    def row(self, name: str) -> dict[str, Any]:
        return dict(self.rows.get(str(name or "").strip().casefold()) or {})


rally = Rally()
member_orders = MemberOrders()
policy_acks = PolicyAcks()


def reset_orders() -> None:
    rally.clear()
    member_orders.clear()
    policy_acks.clear()


__all__ = [
    "ARRIVE_TILES",
    "BEEP",
    "MEMBER_STATE",
    "MEMBER_HELLO",
    "member_hello_message",
    "INVITE_ACCEPT",
    "beep_message",
    "invite_accept_message",
    "member_state_message",
    "new_invite_id",
    "POLICY",
    "POLICY_ACK",
    "PolicyAcks",
    "leader_session",
    "new_leader_session",
    "policy_ack_message",
    "policy_acks",
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
    "policy_message",
    "rally",
    "rally_message",
    "recovery_message",
    "reset_orders",
    "loot_role_for_name",
    "seat_index_for_name",
    "seat_role_for_name",
    "self_name_from_party",
]
