"""Party invites — everything the leader needs to build the in-game party.

- Chat lines: ``/초대 <name>`` (invite), ``파티탈퇴`` (leave).
- ``PartyInviter``: pure state machine, one step per bot tick, per member.
  Every roster name not joined gets an invite every ``INVITE_EVERY_S`` — no
  cut-off: a member that starts late, or left the party, is invited whenever
  it is ready. ``START_WAIT_S`` only bounds how long the leader waits before
  the hunt; names still missing then are "late" (still invited).
- ``LeaderInvites``: one per Start. Reads party memory first. Already in a
  party this character leads (or cannot tell) skips ``파티탈퇴`` and ``/초대``
  for names already listed; a websocket beep tests the link instead. Else
  sends the party policy, leaves a party this character does not lead, then
  drives ``PartyInviter`` each tick: a roster name is invited only after that
  member confirmed the current policy, not while its ``member_state`` says
  its invite popup is still open (``sync.InviteHold``), and no line is typed
  right after an action that opens an NPC dialog or teleports, nor right
  after a combat action (unless combat has held a due invite for
  ``COMBAT_HOLD_MAX_S``). No socket notice is sent: the member sees the popup
  itself. Joined = leader party memory, or the member accepted the popup
  (``invite_accept``) / its party memory says so (``sync.reported_joined``);
  left = the member reports it is out and the leader memory does not list
  it, for ``LEFT_CONFIRM_S``.

Chat delivery defaults to ``app._05_action.chat.send_chat_line``; the session
injects policy publish, socket count and wait.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

INVITE_PREFIX = "/초대 "
LEAVE_COMMAND = "파티탈퇴"

# Leader waits this long for invites + rally before the hunt; invites go on after.
START_WAIT_S = 10 * 60
# Re-send ``/초대 <name>`` to a missing member this often.
INVITE_EVERY_S = 20.0
# A joined member counts as gone only after reporting "out" this long.
LEFT_CONFIRM_S = 10.0
# Combat may delay a due invite at most this long.
COMBAT_HOLD_MAX_S = 60.0
# Typing chat right after these would steal skill / potion keys.
COMBAT_ACTIONS = frozenset(
    {
        "attack",
        "use_hp_potion",
        "use_mp_potion",
        "use_depoison",
        "heal",
        "buff",
        "hp_to_mp",
    }
)
# Chat would type into an NPC dialog or break a gate / teleport / shop click.
UNSAFE_ACTIONS = frozenset(
    {
        "shop_run",
        "shop_stop",
        "gate",
        "teleport",
        "use_talking_scroll",
        "return_to_mother_tree",
        "respawn",
        "dismiss_level_up",
    }
)

FORMING = "forming"
FORMED = "formed"
# Start wait over, someone still missing: hunting, invites go on.
OPEN = "open"
LEAVE_FAILED = "leave_failed"


def invite_command(name: str) -> str:
    return f"{INVITE_PREFIX}{str(name or '').strip()}".rstrip()


def roster_invite_names(rows: Any, self_name: str = "") -> list[str]:
    """Character names to invite, skipping blanks and this character."""
    me = str(self_name or "").strip().casefold()
    out: list[str] = []
    seen: set[str] = set()
    items = rows if isinstance(rows, (list, tuple)) else []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen or (me and key == me):
            continue
        seen.add(key)
        out.append(name)
    return out


def _leader_name(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return ""
    leader = snapshot.get("leader")
    if isinstance(leader, dict):
        name = str(leader.get("name") or "").strip()
        if name:
            return name
    return str(snapshot.get("leader_name") or "").strip()


def _member_names(snapshot: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(snapshot, dict):
        return names
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if name:
            names.add(name.casefold())
    return names


def already_in_party(snapshot: Any) -> bool:
    """True when party memory shows this character is already in a party.

    Unreadable memory (no snapshot, or ``subs_ok`` false) is not in-party —
    that is unknown, not an invitation skip.
    """
    if not isinstance(snapshot, dict):
        return False
    if snapshot.get("subs_ok") is False:
        return False
    return bool(snapshot.get("in_party"))


def _local_is_leader(snapshot: Any, self_name: str) -> bool:
    if not already_in_party(snapshot):
        return False
    me = str(self_name or "").strip().casefold()
    if not me:
        return False
    lead = _leader_name(snapshot).casefold()
    if lead and lead == me:
        return True
    for raw in snapshot.get("members") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip().casefold()
        if name == me:
            return bool(raw.get("is_leader"))
    return False


def needs_leave(snapshot: Any, self_name: str) -> bool:
    """In a party this character does not lead: leave before inviting.

    Unknown identity (empty ``self_name``) must not ``파티탈퇴`` an already
    formed party.
    """
    if not already_in_party(snapshot):
        return False
    if _local_is_leader(snapshot, self_name):
        return False
    if not str(self_name or "").strip():
        return False
    return True


def _action_kind(action: Any) -> str:
    return str(getattr(getattr(action, "action", None), "value", "") or "")


def action_allows_chat(action: Any) -> bool:
    """False right after an action that opens an NPC dialog or teleports."""
    return _action_kind(action) not in UNSAFE_ACTIONS


def action_is_combat(action: Any) -> bool:
    return _action_kind(action) in COMBAT_ACTIONS


def deliver_chat(line: str, *, log: Callable[[str], None], why: str = "") -> bool:
    """Type one line into game chat. True when it reached the game."""
    from app._05_action.chat import send_chat_line

    log(f'Party chat "{line}"{f" ({why})" if why else ""}')
    try:
        result = send_chat_line(line)
        error = "" if result.ok and int(getattr(result, "failed", 0) or 0) == 0 else result.describe()
    except Exception as exc:
        error = str(exc)
        result = None
    if error:
        log(f'Party chat "{line}" failed: {error}')
        _note_monitor(f'chat "{line}" FAILED: {error}')
        return False
    extra = ""
    if result is not None:
        extra = f" chars={result.chars} keys={result.keys}"
        if result.message:
            extra += f" ime={result.message}"
    log(f'Party chat "{line}" typed{extra}')
    _note_monitor(f'chat "{line}" typed{extra}')
    return True


def _note_monitor(text: str) -> None:
    try:
        from websocket.traffic_log import note_local

        note_local(text)
    except Exception:
        pass


@dataclass
class InviteRow:
    name: str
    invites: int = 0
    failed: int = 0
    last_at: Optional[float] = None
    joined_at: Optional[float] = None
    # First "out of party" sighting while joined (leave confirm timer).
    out_since: Optional[float] = None
    left: int = 0
    # Still missing when the start wait ended.
    late: bool = False

    @property
    def joined(self) -> bool:
        return self.joined_at is not None


class PartyInviter:
    """forming (start wait) → formed (everyone in) | open (wait over, invites go on).

    A member that leaves turns ``formed`` back into ``forming`` / ``open``.
    """

    def __init__(
        self,
        names: list[str],
        *,
        start_wait_s: float = START_WAIT_S,
        every_s: float = INVITE_EVERY_S,
        left_confirm_s: float = LEFT_CONFIRM_S,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self._clock = clock
        self._log = log
        self.start_wait_s = float(start_wait_s)
        self.every_s = max(1.0, float(every_s))
        self.left_confirm_s = max(0.0, float(left_confirm_s))
        self.started_at = clock()
        self.deadline = self.started_at + self.start_wait_s
        self.rows = [InviteRow(n) for n in names]
        self.state = FORMED if not self.rows else FORMING
        self.sent: list[str] = []

    @property
    def active(self) -> bool:
        """Leader still in the start wait (not everyone joined yet)."""
        return self.state == FORMING

    @property
    def inviting(self) -> bool:
        return any(not r.joined for r in self.rows)

    def remaining_s(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def missing(self) -> list[str]:
        return [r.name for r in self.rows if not r.joined]

    def late(self) -> list[str]:
        return [r.name for r in self.rows if r.late and not r.joined]

    def observe(
        self,
        snapshot: Any,
        reported: Callable[[str], bool] = lambda _n: False,
        reported_out: Callable[[str], bool] = lambda _n: False,
    ) -> None:
        """Mark joins and confirmed leaves.

        Joined: this leader's party memory lists the name, or ``reported(name)``
        (the member's own party memory says it is in this party). Left: a
        joined member reports ``reported_out(name)`` and the leader memory does
        not list it, for ``left_confirm_s``.
        """
        in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
        present = _member_names(snapshot) if in_party else set()
        now = self._clock()
        for row in self.rows:
            in_leader = row.name.casefold() in present
            if row.joined_at is None:
                if in_leader:
                    how = "leader party memory"
                else:
                    how = "member report" if _safe(reported, row.name) else ""
                if not how:
                    continue
                row.joined_at = now
                row.out_since = None
                was_late = row.late
                row.late = False
                self._log(
                    f'Party: "{row.name}" joined'
                    + (" (late)" if was_late else f" after {row.invites} invite(s)")
                    + f" — {how}"
                )
                continue
            if in_leader or not _safe(reported_out, row.name):
                row.out_since = None
                continue
            if row.out_since is None:
                row.out_since = now
                continue
            if now - row.out_since < self.left_confirm_s:
                continue
            row.joined_at = None
            row.out_since = None
            row.last_at = None
            row.left += 1
            self._log(f'Party: "{row.name}" left the party — inviting again')

    def seed_from_memory(
        self,
        snapshot: Any,
        reported: Callable[[str], bool] = lambda _n: False,
        reported_out: Callable[[str], bool] = lambda _n: False,
    ) -> None:
        """Mark names already in party memory before the first /초대 tick."""
        self.observe(snapshot, reported, reported_out)
        self._update_state(self._clock())

    def _update_state(self, now: float) -> None:
        if all(r.joined for r in self.rows):
            if self.state != FORMED:
                self.state = FORMED
                self._log("Party formed — every roster member joined")
            return
        if now < self.deadline:
            self.state = FORMING
            return
        if self.state == FORMING:
            for row in self.rows:
                if not row.joined:
                    row.late = True
            mins = int(self.start_wait_s // 60)
            self._log(
                f"Party start wait over ({mins} min) — hunting; still inviting: "
                + (", ".join(self.missing()) or "—")
            )
        self.state = OPEN

    def due(self, ready: Optional[Callable[[str], bool]] = None) -> list[InviteRow]:
        now = self._clock()
        return [
            r for r in self.rows
            if not r.joined
            and (r.last_at is None or now - r.last_at >= self.every_s)
            and (ready is None or ready(r.name))
        ]

    def tick(
        self,
        snapshot: Any,
        *,
        send_line: Callable[[str], bool],
        can_send: bool = True,
        ready: Optional[Callable[[str], bool]] = None,
        reported: Callable[[str], bool] = lambda _n: False,
        reported_out: Callable[[str], bool] = lambda _n: False,
    ) -> Optional[str]:
        """One step: update joins / leaves / state, send at most one due invite.

        ``ready(name)`` False keeps that name waiting (no invite, no retry clock).
        """
        self.observe(snapshot, reported, reported_out)
        now = self._clock()
        self._update_state(now)
        if self.state == FORMED or not can_send:
            return None
        due = self.due(ready)
        if not due:
            return None
        row = min(due, key=lambda r: (r.last_at is not None, r.last_at or 0.0))
        line = invite_command(row.name)
        row.last_at = now
        if send_line(line):
            row.invites += 1
            self.sent.append(line)
            return line
        row.failed += 1
        self._log(f'Party chat "{line}" not delivered — next try in {int(self.every_s)}s')
        return None

    def status(self) -> dict[str, Any]:
        now = self._clock()
        return {
            "state": self.state,
            "start_wait_s": self.start_wait_s,
            "every_s": self.every_s,
            "remaining_s": round(self.remaining_s(), 1),
            "elapsed_s": round(now - self.started_at, 1),
            "names": [r.name for r in self.rows],
            "sent": list(self.sent),
            "late": self.late(),
            "rows": [
                {
                    "name": r.name,
                    "invites": r.invites,
                    "failed": r.failed,
                    "last_ago_s": (
                        round(now - r.last_at, 1) if r.last_at is not None else None
                    ),
                    "joined": r.joined,
                    "late": r.late and not r.joined,
                    "left": r.left,
                    "leaving_s": (
                        round(now - r.out_since, 1) if r.out_since is not None else None
                    ),
                }
                for r in self.rows
            ],
        }


def _safe(fn: Callable[[str], bool], name: str) -> bool:
    try:
        return bool(fn(name))
    except Exception:
        return False


class LeaderInvites:
    """One per Start: policy first, leave if needed, then invites per tick."""

    def __init__(
        self,
        *,
        publish_policy: Callable[[], Any] = lambda: None,
        ws_clients: Callable[[], int] = lambda: 0,
        policy_acked: Callable[[str], bool] = lambda _name: True,
        hold: Any = None,
        reported_joined: Callable[[str], bool] = lambda _name: False,
        reported_out: Callable[[str], bool] = lambda _name: False,
        send_chat: Optional[Callable[[str], bool]] = None,
        wait: Callable[[float], Any] = time.sleep,
        log: Callable[[str], None] = lambda _m: None,
        clock: Callable[[], float] = time.monotonic,
        start_wait_s: Optional[float] = None,
        every_s: Optional[float] = None,
        on_beep: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._publish_policy = publish_policy
        self._ws_clients = ws_clients
        self._policy_acked = policy_acked
        # ``sync.InviteHold``: no new /초대 while the member's invite popup is open.
        self._hold = hold
        self._reported_joined = reported_joined
        self._reported_out = reported_out
        self._send_chat = send_chat
        self._wait = wait
        self._log = log
        self._clock = clock
        self.start_wait_s = float(START_WAIT_S if start_wait_s is None else start_wait_s)
        self.every_s = float(INVITE_EVERY_S if every_s is None else every_s)
        self._on_beep = on_beep
        self.inviter: Optional[PartyInviter] = None
        self.info: dict[str, Any] = {}
        self._policy_clients = 0
        self._combat_hold_at: Optional[float] = None
        self._beep_on = False

    @property
    def active(self) -> bool:
        return self.inviter is not None and self.inviter.active

    @property
    def deadline(self) -> Optional[float]:
        return self.inviter.deadline if self.inviter is not None else None

    def _say(self, line: str, why: str = "") -> bool:
        if self._send_chat is not None:
            return bool(self._send_chat(line))
        return deliver_chat(line, log=self._log, why=why)

    def _clients(self) -> int:
        try:
            return int(self._ws_clients() or 0)
        except Exception:
            return 0

    def _publish(self) -> None:
        try:
            self._publish_policy()
        except Exception as exc:
            self._log(f"Party policy publish failed: {exc}")

    def _ring(self) -> None:
        if self._on_beep is None:
            return
        try:
            self._on_beep()
        except Exception as exc:
            self._log(f"Party beep failed: {exc}")

    def start(self, names: Any, *, snapshot: Any, self_name: str) -> bool:
        """Read memory, skip invites when already organized, else leave + arm inviter.

        False = leave failed.
        """
        wanted = roster_invite_names(names, self_name)
        in_party = already_in_party(snapshot)
        self._log(
            f"Party setup: self={self_name or '—'} in_party={in_party} "
            f"leader={_leader_name(snapshot) or '—'} invite={', '.join(wanted) or '—'}"
        )
        self._publish()
        self._policy_clients = self._clients()
        if needs_leave(snapshot, self_name):
            if not self._say(LEAVE_COMMAND, "not the in-game leader"):
                self.info = {"state": LEAVE_FAILED, "names": wanted}
                return False
            self._wait(1.0)
            in_party = False
            snapshot = None
        self.inviter = PartyInviter(
            wanted,
            start_wait_s=self.start_wait_s,
            every_s=self.every_s,
            clock=self._clock,
            log=self._log,
        )
        self.inviter.seed_from_memory(
            snapshot, self._reported_joined, self._reported_out
        )
        self.info = self.inviter.status()
        missing = self.inviter.missing()
        joined = [r.name for r in self.inviter.rows if r.joined]
        if in_party:
            self._beep_on = True
            self._ring()
            if not missing:
                self._log(
                    "Party already organized (memory) — skipping invitations; "
                    "websocket beep"
                )
                return True
            self._log(
                "Party already in-game (memory) — skipping /초대 for "
                f"{', '.join(joined) or '—'}; still inviting "
                f"{', '.join(missing)}"
            )
        self._log(
            f"Party start wait {int(self.start_wait_s // 60)} min, then hunt. "
            f"/초대 every {int(self.every_s)}s to each member that confirmed the "
            f"policy and is not in the party — no cut-off "
            f"({', '.join(missing or wanted) or '—'})"
        )
        return True

    def _acked(self, name: str) -> bool:
        try:
            return bool(self._policy_acked(name))
        except Exception:
            return False

    def _ready(self, name: str) -> bool:
        if not self._acked(name):
            return False
        return self._hold is None or bool(self._hold.may_invite(name))

    def tick(self, snapshot: Any, last_action: Any = None) -> Optional[str]:
        """One invite step; returns the line typed this tick, if any."""
        inviter = self.inviter
        if inviter is None:
            return None
        clients = self._clients()
        if clients > self._policy_clients:
            self._publish()
            if self._beep_on:
                self._ring()
        self._policy_clients = clients
        can_send = False
        if inviter.inviting:
            can_send = action_allows_chat(last_action) and self._combat_allows(
                inviter, last_action
            )
        line = inviter.tick(
            snapshot,
            send_line=self._say,
            can_send=can_send,
            ready=self._ready,
            reported=self._reported_joined,
            reported_out=self._reported_out,
        )
        info = inviter.status()
        for row in info.get("rows") or []:
            name = str(row.get("name") or "")
            row["policy_acked"] = self._acked(name)
            if self._hold is not None:
                row.update(self._hold.row(name))
        info["combat_hold_s"] = (
            round(self._clock() - self._combat_hold_at, 1)
            if self._combat_hold_at is not None
            else None
        )
        self.info = info
        return line

    def _combat_allows(self, inviter: PartyInviter, last_action: Any) -> bool:
        """No chat right after a combat action, unless a due invite waited too long."""
        if not action_is_combat(last_action) or not inviter.due(self._ready):
            self._combat_hold_at = None
            return True
        now = self._clock()
        if self._combat_hold_at is None:
            self._combat_hold_at = now
        if now - self._combat_hold_at < COMBAT_HOLD_MAX_S:
            return False
        self._combat_hold_at = None
        return True


__all__ = [
    "COMBAT_ACTIONS",
    "COMBAT_HOLD_MAX_S",
    "FORMED",
    "FORMING",
    "INVITE_EVERY_S",
    "INVITE_PREFIX",
    "LEAVE_COMMAND",
    "LEAVE_FAILED",
    "LEFT_CONFIRM_S",
    "OPEN",
    "START_WAIT_S",
    "UNSAFE_ACTIONS",
    "InviteRow",
    "LeaderInvites",
    "PartyInviter",
    "action_allows_chat",
    "action_is_combat",
    "already_in_party",
    "deliver_chat",
    "invite_command",
    "needs_leave",
    "roster_invite_names",
]
