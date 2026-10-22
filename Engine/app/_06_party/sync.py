"""Leader ↔ member state sync (level-triggered, idempotent).

The leader and the members start at different times and sockets drop, so no
step may depend on one edge message arriving. Instead:

- Member → leader ``member_state`` every ``STATE_EVERY_S`` and on change:
  the member's whole view (leader session, applied policy id, its own party
  memory, last invite popup + accept phase). ``MemberStateReporter``.
- Member → leader ``invite_accept`` once Y closed its invite popup
  (``InviteAccepts`` on the leader).
- Leader keeps the latest frame per roster name (``MemberStates``) and
  reconciles each tick: policy confirmed = state echoes the current policy id;
  joined = leader party memory lists the name OR the member accepted the
  invite popup (``invite_accept`` / phase ``accepted``) OR the member's own
  party memory says it is in this leader's party; a fresh ``/초대`` waits while
  the member reports its invite popup is still open.
- Frames carry ids (``policy_id``, ``accept_id``, ``session``) so repeats are
  harmless; a state older than ``STALE_S`` is ignored (member gone / restarted).
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable, Optional

STATE_EVERY_S = 2.0
STALE_S = 7.0
# Hold a new /초대 while the member's invite popup is open, at most this long.
ACCEPT_HOLD_S = 30.0

HANDLING_PHASES = ("popup", "pressed")
ACCEPTED_PHASE = "accepted"
LEFT_PHASE = "left"


def _key(name: Any) -> str:
    return str(name or "").strip().casefold()


def party_view(snapshot: Any) -> dict[str, Any]:
    """This bot's party memory for ``member_state``. ``mem`` ok | blind."""
    if not isinstance(snapshot, dict):
        return {"mem": "blind", "in_party": None, "leader": "", "names": []}
    names = [
        str(m.get("name") or "").strip()
        for m in (snapshot.get("members") or [])
        if isinstance(m, dict) and str(m.get("name") or "").strip()
    ]
    leader = snapshot.get("leader")
    lead = str(leader.get("name") or "").strip() if isinstance(leader, dict) else ""
    return {
        "mem": "ok",
        "in_party": bool(snapshot.get("in_party")),
        "leader": lead or str(snapshot.get("leader_name") or "").strip(),
        "names": names,
    }


def memory_in_party(snapshot: Any) -> Optional[bool]:
    """True / False from party memory, None when it is unreadable."""
    if not isinstance(snapshot, dict):
        return None
    return bool(snapshot.get("in_party"))


class MemberStateReporter:
    """Member side: build and send ``member_state`` on change or every 2 s."""

    def __init__(
        self,
        *,
        every_s: float = STATE_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.every_s = max(0.5, float(every_s))
        self._clock = clock
        self._last_key = ""
        self._last_at: Optional[float] = None
        self.seq = 0
        self.sent = 0
        self.sent_at: Optional[float] = None
        self.last: dict[str, Any] = {}

    def reset(self) -> None:
        self._last_key = ""
        self._last_at = None

    def tick(
        self,
        send: Callable[[dict[str, Any]], bool],
        *,
        name: str,
        session: str,
        policy_id: str,
        party: dict[str, Any],
        invite: dict[str, Any],
        live: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Send when the view changed or the keep-alive is due. True = sent.

        ``live`` (bot state, map, xy, hp …) rides along for the leader monitor
        but does not count as a change, so walking does not flood frames.
        """
        from .comms.orders import member_state_message

        view = {
            "name": name, "session": session, "policy_id": policy_id,
            "party": party, "invite": invite,
        }
        key = json.dumps(view, sort_keys=True, default=str, ensure_ascii=False)
        now = self._clock()
        changed = key != self._last_key
        if not changed and self._last_at is not None and now - self._last_at < self.every_s:
            return False
        body = member_state_message(
            name=name, session=session, policy_id=policy_id,
            party=party, invite=invite, seq=self.seq + 1, changed=changed,
            live=live,
        )
        try:
            ok = bool(send(body))
        except Exception:
            ok = False
        if not ok:
            return False
        self.seq += 1
        self.sent += 1
        self.sent_at = time.time()
        self._last_key = key
        self._last_at = now
        self.last = body
        return True

    def status(self) -> dict[str, Any]:
        return {"seq": self.seq, "sent": self.sent, "sent_at": self.sent_at}


class MemberStates:
    """Leader side: latest ``member_state`` per roster name."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.rows: dict[str, dict[str, Any]] = {}
        # Last frame from a member that does not know its name and could not be booked.
        self.unnamed_at: Optional[float] = None

    def clear(self) -> None:
        self.rows.clear()
        self.unnamed_at = None

    def unnamed_recent(self) -> bool:
        return self.unnamed_at is not None and self._clock() - self.unnamed_at < STALE_S

    def note(
        self,
        who: str,
        body: dict[str, Any],
        roster: Iterable[str] = (),
        *,
        session: str = "",
    ) -> str:
        """Store one frame; returns the roster name booked ("" = ignored).

        A frame for an older leader session is ignored: that member has not seen
        this run yet and will re-report once it has. A member that does not know
        its name yet (``member``) is booked to the only roster name without a
        named, fresh state.
        """
        if session and str(body.get("session") or "") != session:
            return ""
        name = str(who or body.get("from") or "").strip()
        if not name or name == "leader":
            return ""
        names = [str(n).strip() for n in roster if str(n).strip()]
        by_key = {n.casefold(): n for n in names}
        if name.casefold() in by_key:
            name = by_key[name.casefold()]
        elif name == "member" and names:
            open_names = [
                n for n in names
                if not (self.fresh(n) and self.rows[_key(n)].get("named"))
            ]
            if len(open_names) != 1:
                self.unnamed_at = self._clock()
                return ""
            name = open_names[0]
        prev = self.rows.get(_key(name)) or {}
        try:
            seq = int(body.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        # Same member run, older frame (reordered): keep the newer one.
        if prev and seq and 0 < seq < int(prev.get("seq") or 0) and prev.get("fresh_at"):
            if self._clock() - float(prev["fresh_at"]) < STALE_S:
                return name
        self.rows[_key(name)] = {
            "name": name,
            "named": str(who or body.get("from") or "") not in ("", "member"),
            "seq": seq,
            "policy_id": str(body.get("policy_id") or ""),
            "party": dict(body.get("party") or {}),
            "invite": dict(body.get("invite") or {}),
            "live": dict(body.get("live") or {}),
            "fresh_at": self._clock(),
            "at": time.time(),
            "frames": int(prev.get("frames", 0)) + 1,
        }
        return name

    def row(self, name: str) -> dict[str, Any]:
        row = dict(self.rows.get(_key(name)) or {})
        if row:
            row["age_s"] = round(self._clock() - float(row.get("fresh_at") or 0.0), 1)
            row["fresh"] = row["age_s"] < STALE_S
        return row

    def fresh(self, name: str) -> bool:
        row = self.rows.get(_key(name))
        return bool(row) and self._clock() - float(row.get("fresh_at") or 0.0) < STALE_S

    def policy_ok(self, name: str, policy_id: Optional[str]) -> bool:
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
        return policy_id is None or str(row.get("policy_id") or "") == str(policy_id)

    def joined(self, name: str, leader_name: str = "") -> bool:
        """The member accepted the invite popup, or its own party memory says
        it is in this leader's party."""
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
        if str((row.get("invite") or {}).get("phase") or "") == ACCEPTED_PHASE:
            return True
        party = row.get("party") or {}
        if party.get("mem") != "ok" or not party.get("in_party"):
            return False
        lead = _key(party.get("leader"))
        me = _key(leader_name)
        if lead and me:
            return lead == me
        names = {_key(n) for n in party.get("names") or []}
        return not me or not names or me in names

    def out_of_party(self, name: str, leader_name: str = "") -> bool:
        """The member's own party memory (fresh, readable) says it is not in
        this party, and it does not report an accepted invite."""
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
        if (row.get("party") or {}).get("mem") != "ok":
            return False
        return not self.joined(name, leader_name)

    def invite_phase(self, name: str) -> tuple[str, str]:
        """(invite_id, phase) the member last reported, ("", "") when unknown."""
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return "", ""
        inv = row.get("invite") or {}
        return str(inv.get("id") or ""), str(inv.get("phase") or "")


class InviteAccepts:
    """Leader side: ``invite_accept`` frames — Y closed the member's invite popup."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def clear(self) -> None:
        self.rows.clear()

    def note(
        self,
        who: str,
        body: dict[str, Any],
        roster: Iterable[str] = (),
        *,
        session: str = "",
    ) -> tuple[str, bool]:
        """Book one frame: (roster name or "", first time for this ``accept_id``).

        A frame for another leader session is ignored. A member that does not
        know its name (``member``) is booked to the only roster name without an
        accept yet.
        """
        if session and str(body.get("session") or "") != session:
            return "", False
        name = str(who or body.get("from") or "").strip()
        if not name or name == "leader":
            return "", False
        names = [str(n).strip() for n in roster if str(n).strip()]
        by_key = {n.casefold(): n for n in names}
        if name.casefold() in by_key:
            name = by_key[name.casefold()]
        elif name == "member" and names:
            open_names = [n for n in names if _key(n) not in self.rows]
            if len(open_names) != 1:
                return "", False
            name = open_names[0]
        aid = str(body.get("accept_id") or "")
        prev = self.rows.get(_key(name)) or {}
        first = not prev or str(prev.get("accept_id") or "") != aid
        self.rows[_key(name)] = {
            "name": name,
            "accept_id": aid,
            "inviter": str(body.get("inviter") or ""),
            "presses": int(body.get("presses") or 0),
            "at": float(prev.get("at") or 0.0) if not first else time.time(),
            "count": int(prev.get("count", 0)) + 1,
        }
        return name, first

    def accepted(self, name: str) -> bool:
        return _key(name) in self.rows

    def row(self, name: str) -> dict[str, Any]:
        return dict(self.rows.get(_key(name)) or {})


def reported_joined(
    name: str,
    leader_name: str = "",
    *,
    states: Optional["MemberStates"] = None,
    accepts: Optional[InviteAccepts] = None,
) -> bool:
    """Joined as the member tells it: accepted invite popup or own party memory.

    With a fresh ``member_state`` the ``invite_accept`` counts only while the
    state still carries that ``accept_id`` and not ``left`` (a restarted member
    or one that left must not stay joined on an old accept)."""
    states = states if states is not None else member_states
    accepts = accepts if accepts is not None else invite_accepts
    if states.joined(name, leader_name):
        return True
    if not accepts.accepted(name):
        return False
    if not states.fresh(name):
        return True
    iid, phase = states.invite_phase(name)
    aid = str(accepts.row(name).get("accept_id") or "")
    return bool(aid) and iid == aid and phase != LEFT_PHASE


class InviteHold:
    """Leader: no new ``/초대`` while the member reports its invite popup open
    (``popup`` / ``pressed``), at most ``ACCEPT_HOLD_S`` per popup."""

    def __init__(
        self,
        states: MemberStates,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._states = states
        self._clock = clock
        self._since: dict[str, tuple[str, float]] = {}

    def may_invite(self, name: str) -> bool:
        iid, phase = self._states.invite_phase(name)
        key = _key(name)
        if phase not in HANDLING_PHASES:
            self._since.pop(key, None)
            return True
        prev = self._since.get(key)
        if prev is None or prev[0] != iid:
            prev = (iid, self._clock())
            self._since[key] = prev
        return self._clock() - prev[1] >= ACCEPT_HOLD_S

    def row(self, name: str) -> dict[str, Any]:
        iid, phase = self._states.invite_phase(name)
        return {
            "accept_id": iid,
            "member_phase": phase,
            "hold": "" if self.may_invite(name) else f"member {phase}",
        }


member_states = MemberStates()
invite_accepts = InviteAccepts()


__all__ = [
    "ACCEPTED_PHASE",
    "ACCEPT_HOLD_S",
    "HANDLING_PHASES",
    "InviteAccepts",
    "InviteHold",
    "LEFT_PHASE",
    "MemberStateReporter",
    "MemberStates",
    "STALE_S",
    "STATE_EVERY_S",
    "invite_accepts",
    "member_states",
    "memory_in_party",
    "party_view",
    "reported_joined",
]

