"""Leader ↔ member state sync (level-triggered, idempotent).

The leader and the members start at different times and sockets drop, so no
step may depend on one edge message arriving. Instead:

- Member → leader ``member_state`` every ``STATE_EVERY_S`` and on change:
  the member's whole view (leader session, applied policy id, its own party
  memory, last invite popup + accept phase). ``MemberStateReporter``.
- Member → leader ``invite_accept`` once Y closed its invite popup
  (``InviteAccepts`` on the leader). That frame is the accept attempt, not
  proof the character is in the party.
- Leader keeps the latest frame per roster name (``MemberStates``) and
  reconciles each tick: policy confirmed = state echoes the current policy id;
  joined = leader party memory lists the name, or a fresh member report whose
  own party memory says it is in this leader's party. ``invite_accept`` alone
  does not join. A fresh ``/초대`` waits only for that member while its popup
  is open.
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


def _roster_order(names: Iterable[str] = ()) -> list[str]:
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


def memory_in_party(snapshot: Any) -> Optional[bool]:
    """True in a party, False confirmed out, None when this read is unknown.

    A missing snapshot or ``subs_ok`` false is unknown. It is not "not in a
    party", so callers must not invite or leave on None.
    """
    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("subs_ok") is False:
        return None
    if "in_party" not in snapshot and "members" not in snapshot:
        return None
    return bool(snapshot.get("in_party"))


def party_view(snapshot: Any) -> dict[str, Any]:
    """This bot's party memory for ``member_state``. ``mem`` ok | blind."""
    known = memory_in_party(snapshot)
    if known is None:
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
        "in_party": known,
        "leader": lead or str(snapshot.get("leader_name") or "").strip(),
        "names": names,
    }


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

    def nudge(self) -> None:
        """Send on the next tick. Does not clear the invite accepter or the seq."""
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
        client_id: str = "",
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
            live=live, client_id=client_id,
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
        # Names whose socket dropped. ``fresh`` stays false until the next state.
        self._awaiting: set[str] = set()
        self._peers: dict[str, str] = {}

    def clear(self) -> None:
        self.rows.clear()
        self.unnamed_at = None
        self._awaiting.clear()
        self._peers.clear()

    def bind_peer(self, peer: str, name: str) -> None:
        """Remember which socket id last spoke as ``name``."""
        pid = str(peer or "").strip()
        who = str(name or "").strip()
        if pid and who:
            self._peers[pid] = who

    def name_for_peer(self, peer: str) -> str:
        return str(self._peers.get(str(peer or "").strip()) or "")

    def forget_peer(self, peer: str) -> None:
        self._peers.pop(str(peer or "").strip(), None)

    def hold_until_fresh(self, name: str) -> None:
        """A dropped socket. The last report is not current until a new one arrives.

        Invite rows and ``InviteAccepter`` are not touched. A 3 s-old frame is
        still inside the 7 s window, so staleness alone would keep it.
        """
        key = _key(name)
        if key:
            self._awaiting.add(key)

    def awaiting_fresh(self, name: str) -> bool:
        return _key(name) in self._awaiting

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
        its name yet (``member``) is bound by ``client_id`` to the next roster
        name without a fresh state, in roster order.
        """
        if session and str(body.get("session") or "") != session:
            return ""
        name = str(who or body.get("from") or "").strip()
        if not name or name.casefold() == "leader":
            return ""
        names = _roster_order(roster)
        by_key = {n.casefold(): n for n in names}
        client_id = str(body.get("client_id") or "").strip()
        if name.casefold() in by_key:
            name = by_key[name.casefold()]
        elif name.casefold() == "member" and names:
            name = self._bind_unnamed(names, client_id)
            if not name:
                self.unnamed_at = self._clock()
                return ""
        else:
            return ""
        prev = self.rows.get(_key(name)) or {}
        try:
            seq = int(body.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        # Same member run, older frame (reordered): keep the newer one.
        if prev and seq and 0 < seq < int(prev.get("seq") or 0) and prev.get("fresh_at"):
            if self._clock() - float(prev["fresh_at"]) < STALE_S:
                return name
        if client_id:
            for key, row in list(self.rows.items()):
                if str(row.get("client_id") or "") != client_id:
                    continue
                if key == _key(name):
                    continue
                if not row.get("named"):
                    self.rows.pop(key, None)
                else:
                    row["client_id"] = ""
        self.rows[_key(name)] = {
            "name": name,
            "named": str(who or body.get("from") or "") not in ("", "member"),
            "client_id": client_id or str(prev.get("client_id") or ""),
            "seq": seq,
            "policy_id": str(body.get("policy_id") or ""),
            "party": dict(body.get("party") or {}),
            "invite": dict(body.get("invite") or {}),
            "live": dict(body.get("live") or {}),
            "fresh_at": self._clock(),
            "at": time.time(),
            "frames": int(prev.get("frames", 0)) + 1,
        }
        self._awaiting.discard(_key(name))
        return name

    def _bind_unnamed(self, names: list[str], client_id: str) -> str:
        """Map an unnamed member to one roster name. "" if they cannot be told apart."""
        if client_id:
            for row in self.rows.values():
                if str(row.get("client_id") or "") == client_id:
                    return str(row.get("name") or "")
        open_names = [n for n in names if not self.fresh(n)]
        if not open_names:
            return ""
        if not client_id and len(open_names) != 1:
            return ""
        return open_names[0]

    def row(self, name: str) -> dict[str, Any]:
        row = dict(self.rows.get(_key(name)) or {})
        if row:
            row["age_s"] = round(self._clock() - float(row.get("fresh_at") or 0.0), 1)
            row["fresh"] = row["age_s"] < STALE_S and _key(name) not in self._awaiting
            row["awaiting_fresh"] = _key(name) in self._awaiting
        return row

    def fresh(self, name: str) -> bool:
        if _key(name) in self._awaiting:
            return False
        row = self.rows.get(_key(name))
        return bool(row) and self._clock() - float(row.get("fresh_at") or 0.0) < STALE_S

    def policy_ok(self, name: str, policy_id: Optional[str]) -> bool:
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
        return policy_id is None or str(row.get("policy_id") or "") == str(policy_id)

    def joined(self, name: str, leader_name: str = "") -> bool:
        """Fresh member party memory says this character is in this leader's party.

        Popup phase and ``invite_accept`` are not a join. A blind report is not
        "out" either; callers see False here and ``out_of_party`` stays False
        while ``mem`` is not ok.
        """
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
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
        """Fresh readable party memory says the member is not in this party.

        A blind or stale report is not an exit. Popup accept is not a join, so
        it also does not block this "out" once memory is readable and empty.
        """
        row = self.rows.get(_key(name))
        if not row or not self.fresh(name):
            return False
        if (row.get("party") or {}).get("mem") != "ok":
            return False
        return not self.joined(name, leader_name)

    def invite_phase(self, name: str) -> tuple[str, str]:
        """(invite_id, phase) the member last reported, ("", "") when unknown.

        A socket drop keeps the last popup phase so ``/초대`` stays held. The
        join itself still waits for a fresh report.
        """
        row = self.rows.get(_key(name))
        if not row:
            return "", ""
        if not self.fresh(name) and not self.awaiting_fresh(name):
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
        know its name (``member``) is bound by ``client_id`` to the next roster
        name without an accept yet.
        """
        if session and str(body.get("session") or "") != session:
            return "", False
        name = str(who or body.get("from") or "").strip()
        if not name or name.casefold() == "leader":
            return "", False
        names = _roster_order(roster)
        by_key = {n.casefold(): n for n in names}
        client_id = str(body.get("client_id") or "").strip()
        if name.casefold() in by_key:
            name = by_key[name.casefold()]
        elif name.casefold() == "member" and names:
            if client_id:
                for row in self.rows.values():
                    if str(row.get("client_id") or "") == client_id:
                        name = str(row.get("name") or "")
                        break
                else:
                    name = ""
            else:
                name = ""
            if not name:
                open_names = [n for n in names if _key(n) not in self.rows]
                if not open_names:
                    return "", False
                if not client_id and len(open_names) != 1:
                    return "", False
                name = open_names[0]
        else:
            return "", False
        aid = str(body.get("accept_id") or "")
        prev = self.rows.get(_key(name)) or {}
        first = not prev or str(prev.get("accept_id") or "") != aid
        if client_id:
            for key, row in list(self.rows.items()):
                if str(row.get("client_id") or "") != client_id:
                    continue
                if key != _key(name):
                    self.rows.pop(key, None)
        self.rows[_key(name)] = {
            "name": name,
            "accept_id": aid,
            "client_id": client_id or str(prev.get("client_id") or ""),
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
    """True only from a fresh member party-memory report for this leader.

    ``accepts`` is ignored. ``invite_accept`` records that Y was sent and the
    popup closed; it does not put the character in the party.
    """
    del accepts
    states = states if states is not None else member_states
    return states.joined(name, leader_name)


class InviteHold:
    """Per member: no new ``/초대`` for that name while its popup is open.

    Other names keep their own clocks. At most ``ACCEPT_HOLD_S`` per popup.
    Chat itself is still one line at a time; this hold does not freeze the
    rest of the roster or the socket.
    """

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

