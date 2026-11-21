"""Party invites — everything the leader needs to build the in-game party.

- Chat lines: ``/초대 <name>`` (invite), ``파티탈퇴`` (leave).
- ``PartyInviter``: pure state machine, one step per bot tick, per member.
  Every roster name not joined gets an invite every ``INVITE_EVERY_S`` — no
  cut-off: a member that starts late, or left the party, is invited whenever
  it is ready. ``START_WAIT_S`` only bounds how long the leader waits before
  the hunt; names still missing then are "late" (still invited).
- ``LeaderInvites``: one per Start. A party-memory read that fails is
  unknown: no ``파티탈퇴`` and no ``/초대`` until a read confirms in or out.
  Leave only when this character's name, the party leader's name, and the
  memory read are all confirmed, and this character is not that leader.
  Already in a party this character leads skips ``파티탈퇴`` and ``/초대``
  for names already listed; a websocket beep tests the link instead.
  Then each tick drives ``PartyInviter``. A roster name is invited only
  after that member confirmed the current policy, not while that member's
  popup is open (other names are not frozen), and no line is typed right
  after an NPC dialog, teleport, or combat action (unless combat has held a
  due invite for ``COMBAT_HOLD_MAX_S``). Joined = this leader's party memory
  lists the name. A fresh member report counts only while this read is
  unknown. ``invite_accept`` is not a join. Left = a confirmed read does not
  list them, for ``LEFT_CONFIRM_S``. An unknown read does not start that
  timer. The 10 minute forming clock starts once and is not reset when a
  member reconnects. Hunt waits only for required roster names.

Chat delivery defaults to ``app._05_action.chat.send_chat_line``; the session
injects policy publish, socket count and wait.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

INVITE_PREFIX = "/초대 "
KICK_PREFIX = "/파티추방 "
LEAVE_COMMAND = "파티탈퇴"
# After the first /파티추방, two more sends if a confirmed read still lists them.
KICK_RETRIES = 2
# Wait this long after a kick line before treating a still-listed name as failed.
KICK_CONFIRM_S = 2.0

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


def kick_command(name: str) -> str:
    return f"{KICK_PREFIX}{str(name or '').strip()}".rstrip()


def member_listed(snapshot: Any, name: str) -> Optional[bool]:
    """True when this read lists the name. False when a read confirms absence.

    None means the read is unknown. Callers must not kick or treat that as a leave.
    """
    from app._06_party.sync import memory_in_party

    if memory_in_party(snapshot) is None:
        return None
    key = str(name or "").strip().casefold()
    if not key or memory_in_party(snapshot) is not True:
        return False
    return key in _member_names(snapshot)


def clear_roster_flags(rows: Any, name: str) -> bool:
    """Turn 사용 and 대기 off for one saved name. The row stays."""
    key = str(name or "").strip().casefold()
    if not key or not isinstance(rows, (list, tuple)):
        return False
    changed = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("name") or "").strip().casefold() != key:
            continue
        if str(row.get("enabled") or "") != "0" or str(row.get("required") or "") != "0":
            row["enabled"] = "0"
            row["required"] = "0"
            changed = True
    return changed


class KickWatch:
    """Type /파티추방, then confirm the name left party memory.

    The first send happens only when a confirmed read lists them. If they are
    still listed after the confirm wait, the line is sent again, up to two
    more times. An unknown read does not count as left and does not spend a retry.
    """

    def __init__(
        self,
        name: str,
        *,
        clock: Callable[[], float] = time.monotonic,
        confirm_s: float = KICK_CONFIRM_S,
        retries: int = KICK_RETRIES,
    ) -> None:
        self.name = str(name or "").strip()
        self.key = self.name.casefold()
        self.sends = 0
        self.typed_at: Optional[float] = None
        self.absent_since: Optional[float] = None
        self.phase = "armed"
        self.confirm_s = float(confirm_s)
        self.retries = int(retries)
        self._clock = clock

    def begin(self, snapshot: Any, send_line: Callable[[str], bool]) -> str:
        listed = member_listed(snapshot, self.name)
        if listed is not True:
            self.phase = "skipped"
            if listed is None:
                return "rejected: party memory unread"
            return "rejected: not in party"
        return self._send(send_line)

    def tick(
        self,
        snapshot: Any,
        send_line: Callable[[str], bool],
        *,
        can_send: bool,
    ) -> Optional[str]:
        if self.phase != "waiting":
            return None
        listed = member_listed(snapshot, self.name)
        if listed is None:
            self.absent_since = None
            return None
        now = self._clock()
        if not listed:
            if self.absent_since is None:
                self.absent_since = now
            if now - self.absent_since < self.confirm_s:
                return None
            self.phase = "left"
            return "left"
        self.absent_since = None
        if self.typed_at is None or now - self.typed_at < self.confirm_s:
            return None
        if self.sends >= 1 + self.retries:
            self.phase = "failed"
            return "failed"
        if not can_send:
            return None
        return self._send(send_line)

    def _send(self, send_line: Callable[[str], bool]) -> str:
        line = kick_command(self.name)
        try:
            ok = bool(send_line(line))
        except Exception:
            ok = False
        self.sends += 1
        self.typed_at = self._clock()
        self.absent_since = None
        self.phase = "waiting"
        return f"manual {line}" if ok else f"manual {line} failed"


def _roster_on(item: Any, key: str, default: bool = True) -> bool:
    if not isinstance(item, dict) or key not in item:
        return default
    raw = item.get(key)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def roster_invite_names(rows: Any, self_name: str = "") -> list[str]:
    """Enabled character names to invite, skipping blanks and this character.

    A row without ``enabled`` stays on. ``enabled`` false is out of forming
    and out of ``/초대``.
    """
    me = str(self_name or "").strip().casefold()
    out: list[str] = []
    seen: set[str] = set()
    items = rows if isinstance(rows, (list, tuple)) else []
    for item in items:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if not _roster_on(item, "enabled", True):
                continue
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


def roster_required_names(rows: Any, self_name: str = "") -> list[str]:
    """Enabled names that hold the hunt until they join.

    Missing ``required`` means yes, so an old roster still waits. Uncheck
    Wait on the Party tab to invite someone without holding forming.
    """
    me = str(self_name or "").strip().casefold()
    out: list[str] = []
    seen: set[str] = set()
    items = rows if isinstance(rows, (list, tuple)) else []
    for item in items:
        if not isinstance(item, dict):
            name = str(item or "").strip()
            required = True
        else:
            name = str(item.get("name") or "").strip()
            if not _roster_on(item, "enabled", True):
                continue
            required = _roster_on(item, "required", True)
        if not name or not required:
            continue
        key = name.casefold()
        if key in seen or (me and key == me):
            continue
        seen.add(key)
        out.append(name)
    return out


def action_party_snapshot(world: Any) -> Any:
    """Party snapshot for invite, leave, and join.

    A failed read this frame (``party_read_ok`` false) is None: unknown.
    ``last_party`` is kept for diagnostics and is not a live pose.
    """
    if world is None:
        return None
    if getattr(world, "party_read_ok", None) is False:
        return None
    return getattr(world, "last_party", None)


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
    """True only when this read confirms the character is in a party.

    Unknown (no snapshot, ``subs_ok`` false) is False here. Callers that must
    not invite or leave on a failed read use ``memory_in_party`` and treat
    None as unknown.
    """
    from app._06_party.sync import memory_in_party

    return memory_in_party(snapshot) is True


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
    """Leave only when memory, this name, and the party leader are all confirmed.

    Unknown memory, an empty self name, or an empty leader name does not
    ``파티탈퇴``. Being the confirmed leader does not either.
    """
    from app._06_party.sync import memory_in_party

    if memory_in_party(snapshot) is not True:
        return False
    me = str(self_name or "").strip()
    if not me:
        return False
    lead = _leader_name(snapshot)
    if not lead:
        return False
    if lead.casefold() == me.casefold():
        return False
    return not _local_is_leader(snapshot, me)


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
    # leader memory | member memory. Empty until a confirmed join.
    join_src: str = ""
    # First "out of party" sighting while joined (leave confirm timer).
    out_since: Optional[float] = None
    left: int = 0
    # Still missing when the start wait ended.
    late: bool = False
    # False = invite, but do not hold the hunt for this name.
    required: bool = True

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
        required: Optional[set[str]] = None,
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
        # Fixed at the first arm. A reconnect must not move this deadline.
        self.started_at = clock()
        self.deadline = self.started_at + self.start_wait_s
        req = None if required is None else {n.casefold() for n in required}
        self.rows = [
            InviteRow(n, required=(req is None or n.casefold() in req))
            for n in names
        ]
        self.state = FORMED if not any(r.required for r in self.rows) else FORMING
        self.sent: list[str] = []
        self.last_memory = "unknown"

    @property
    def active(self) -> bool:
        """Hunt stays held: inside the original start wait, a required name is out."""
        return self.state == FORMING

    @property
    def hunt_active(self) -> bool:
        """Party composition is not holding the hunt. Open and formed both hunt."""
        return self.state != FORMING

    @property
    def inviting(self) -> bool:
        return any(not r.joined for r in self.rows)

    def remaining_s(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def missing(self) -> list[str]:
        return [r.name for r in self.rows if not r.joined]

    def late(self) -> list[str]:
        return [r.name for r in self.rows if r.late and not r.joined]

    def _mark_joined(self, row: InviteRow, now: float, how: str) -> None:
        row.joined_at = now
        row.join_src = how
        row.out_since = None
        was_late = row.late
        row.late = False
        self._log(
            f'Party: "{row.name}" joined'
            + (" (late)" if was_late else f" after {row.invites} invite(s)")
            + f" — {how}"
        )

    def _mark_left(self, row: InviteRow) -> None:
        row.joined_at = None
        row.join_src = ""
        row.out_since = None
        row.last_at = None
        row.left += 1
        self._log(f'Party: "{row.name}" left the party — inviting again')

    def observe(
        self,
        snapshot: Any,
        reported: Callable[[str], bool] = lambda _n: False,
        reported_out: Callable[[str], bool] = lambda _n: False,
    ) -> None:
        """Mark joins and confirmed leaves.

        Joined: this leader's party memory lists the name. ``reported(name)``
        counts only while this read is unknown. ``invite_accept`` is not a
        join. Left: a confirmed read does not list them, for
        ``left_confirm_s``. An unknown read does not start or advance a
        leave, and does not clear a confirmed join.
        """
        from app._06_party.sync import memory_in_party

        known = memory_in_party(snapshot)
        now = self._clock()
        if known is None:
            self.last_memory = "unknown"
            for row in self.rows:
                if row.joined_at is None and _safe(reported, row.name):
                    self._mark_joined(row, now, "member memory")
                else:
                    row.out_since = None
            return
        self.last_memory = "in" if known else "out"
        present = _member_names(snapshot) if known else set()
        del reported_out
        for row in self.rows:
            in_leader = row.name.casefold() in present
            if in_leader:
                if row.joined_at is None:
                    self._mark_joined(row, now, "leader memory")
                else:
                    row.out_since = None
                continue
            if row.joined_at is None:
                continue
            if row.out_since is None:
                row.out_since = now
                continue
            if now - row.out_since < self.left_confirm_s:
                continue
            self._mark_left(row)

    def seed_from_memory(
        self,
        snapshot: Any,
        reported: Callable[[str], bool] = lambda _n: False,
        reported_out: Callable[[str], bool] = lambda _n: False,
    ) -> None:
        """Mark names already in party memory before the first /초대 tick."""
        self.observe(snapshot, reported, reported_out)
        self._update_state(self._clock())

    def _required_open(self) -> list[InviteRow]:
        return [r for r in self.rows if r.required and not r.joined]

    def _update_state(self, now: float) -> None:
        # ``deadline`` stays on the first arm. Rejoining does not extend it.
        if not self._required_open():
            if self.state != FORMED:
                self.state = FORMED
                self._log("Party formed — every required member joined")
            return
        if now < self.deadline:
            self.state = FORMING
            return
        if self.state == FORMING:
            for row in self._required_open():
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
        if not can_send or not self.inviting:
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
            "hunt_active": self.hunt_active,
            "memory": self.last_memory,
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
                    "join_src": r.join_src,
                    "required": r.required,
                    "confidence": "confirmed" if r.joined else self.last_memory,
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
        self._await_memory = False
        self._wanted: list[str] = []
        self._required: list[str] = []
        self._self_name = ""
        self._kick_hold: set[str] = set()

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
        """Read memory. Unknown defers leave and invites. False = leave failed."""
        from app._06_party.sync import memory_in_party

        self._wanted = roster_invite_names(names, self_name)
        self._required = roster_required_names(names, self_name)
        self._self_name = self_name
        membership = memory_in_party(snapshot)
        self._log(
            f"Party setup: self={self_name or '—'} memory={membership} "
            f"leader={_leader_name(snapshot) or '—'} "
            f"invite={', '.join(self._wanted) or '—'} "
            f"required={', '.join(self._required) or '—'}"
        )
        self._publish()
        self._policy_clients = self._clients()
        if membership is None:
            self._await_memory = True
            self.inviter = None
            self.info = {
                "state": "memory_unknown",
                "names": list(self._wanted),
                "hunt_active": True,
                "memory": "unknown",
            }
            self._log(
                "Party memory unknown — not leaving and not inviting "
                "until a read succeeds"
            )
            return True
        return self._arm(snapshot)

    def _arm(self, snapshot: Any) -> bool:
        """Create the inviter once. The forming deadline is this clock."""
        if self.inviter is not None:
            return True
        in_party = already_in_party(snapshot)
        if needs_leave(snapshot, self._self_name):
            if not self._say(LEAVE_COMMAND, "not the in-game leader"):
                self.info = {"state": LEAVE_FAILED, "names": list(self._wanted)}
                return False
            self._wait(1.0)
            in_party = False
            snapshot = None
        self._await_memory = False
        self.inviter = PartyInviter(
            self._wanted,
            required=set(self._required),
            start_wait_s=self.start_wait_s,
            every_s=self.every_s,
            clock=self._clock,
            log=self._log,
        )
        if snapshot is not None:
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
            f"({', '.join(missing or self._wanted) or '—'})"
        )
        return True

    def note_manual_invite(self, name: str, *, ok: bool) -> None:
        """A monitor invite used the same chat path. Do not repeat it immediately."""
        inviter = self.inviter
        if inviter is None:
            return
        now = self._clock()
        key = str(name or "").strip().casefold()
        for row in inviter.rows:
            if row.name.casefold() != key:
                continue
            row.last_at = now
            if ok:
                row.invites += 1
                inviter.sent.append(invite_command(row.name))
            else:
                row.failed += 1
            self.info = inviter.status()
            return

    def hold_kick(self, name: str) -> None:
        """Do not /초대 this name while a kick is still being confirmed."""
        key = str(name or "").strip().casefold()
        if key:
            self._kick_hold.add(key)

    def release_kick(self, name: str) -> None:
        self._kick_hold.discard(str(name or "").strip().casefold())

    def drop_kicked(self, name: str) -> None:
        """Stop inviting a name this session. The saved roster row stays."""
        key = str(name or "").strip().casefold()
        self._kick_hold.discard(key)
        if not key:
            return
        self._wanted = [n for n in self._wanted if n.casefold() != key]
        self._required = [n for n in self._required if n.casefold() != key]
        inviter = self.inviter
        if inviter is None:
            return
        inviter.rows = [row for row in inviter.rows if row.name.casefold() != key]
        inviter._update_state(self._clock())
        self.info = inviter.status()

    def _acked(self, name: str) -> bool:
        try:
            return bool(self._policy_acked(name))
        except Exception:
            return False

    def _ready(self, name: str) -> bool:
        if str(name or "").strip().casefold() in self._kick_hold:
            return False
        if not self._acked(name):
            return False
        return self._hold is None or bool(self._hold.may_invite(name))

    def tick(
        self,
        snapshot: Any,
        last_action: Any = None,
        *,
        hold_chat: bool = False,
    ) -> Optional[str]:
        """One invite step; returns the line typed this tick, if any.

        ``hold_chat`` skips the line because a manual party action already
        used the keyboard this tick. Joins and leaves are still observed.
        An unknown memory read also skips the line.
        """
        from app._06_party.sync import memory_in_party

        if self.inviter is None and self._await_memory:
            if memory_in_party(snapshot) is None:
                self.info = {
                    "state": "memory_unknown",
                    "names": list(self._wanted),
                    "hunt_active": True,
                    "memory": "unknown",
                }
                return None
            if not self._arm(snapshot):
                self._await_memory = False
                return None
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
        memory_known = memory_in_party(snapshot) is not None
        if inviter.inviting and memory_known and not hold_chat:
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
    "KICK_CONFIRM_S",
    "KICK_PREFIX",
    "KICK_RETRIES",
    "LEAVE_COMMAND",
    "LEAVE_FAILED",
    "LEFT_CONFIRM_S",
    "OPEN",
    "START_WAIT_S",
    "UNSAFE_ACTIONS",
    "InviteRow",
    "KickWatch",
    "LeaderInvites",
    "PartyInviter",
    "action_allows_chat",
    "action_is_combat",
    "action_party_snapshot",
    "already_in_party",
    "clear_roster_flags",
    "deliver_chat",
    "invite_command",
    "kick_command",
    "member_listed",
    "needs_leave",
    "roster_invite_names",
    "roster_required_names",
]
