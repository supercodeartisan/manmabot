"""Party invites — everything the leader needs to build the in-game party.

- Chat lines: ``/파티 <name>`` (invite), ``파티탈퇴`` (leave).
- ``PartyInviter``: pure state machine, one step per bot tick. Every roster
  name not in party memory gets an invite every ``INVITE_EVERY_S``; a name
  stops getting invites once party memory lists it. When ``FORM_WINDOW_S``
  runs out, names still missing are excluded (a late join clears that).
- ``LeaderInvites``: one per Start. Sends the party policy first, leaves a
  party this character does not lead, then drives ``PartyInviter`` each tick:
  first invites wait for every member socket or ``POLICY_WAIT_S``, and no
  line is typed right after an action that opens an NPC dialog or teleports.

Chat delivery defaults to ``app._05_action.chat.send_chat_line``; the session
injects policy publish, socket count and wait.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

INVITE_PREFIX = "/파티 "
LEAVE_COMMAND = "파티탈퇴"

# Invite + rally must finish inside this window; then the leader hunts.
FORM_WINDOW_S = 15 * 60
# Re-send ``/파티 <name>`` to a missing member this often.
INVITE_EVERY_S = 20.0
# Members usually connect within seconds of their own Start; the first
# invites wait this long for their sockets (policy before invite).
POLICY_WAIT_S = 20.0
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
EXPIRED = "expired"
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


def _local_is_leader(snapshot: Any, self_name: str) -> bool:
    if not isinstance(snapshot, dict) or not snapshot.get("in_party"):
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
    """In a party this character does not lead: leave before inviting."""
    in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
    return in_party and not _local_is_leader(snapshot, self_name)


def action_allows_chat(action: Any) -> bool:
    """False right after an action that opens an NPC dialog or teleports."""
    kind = getattr(getattr(action, "action", None), "value", "") or ""
    return str(kind) not in UNSAFE_ACTIONS


def deliver_chat(line: str, *, log: Callable[[str], None], why: str = "") -> bool:
    """Type one line into game chat. True when it reached the game."""
    from app._05_action.chat import send_chat_line

    log(f'Party chat "{line}"{f" ({why})" if why else ""}')
    result = send_chat_line(line)
    if not result.ok:
        log(f'Party chat "{line}" failed: {result.describe()}')
        return False
    try:
        from websocket.traffic_log import note_local

        note_local(f'chat "{line}"')
    except Exception:
        pass
    return True


@dataclass
class InviteRow:
    name: str
    invites: int = 0
    failed: int = 0
    last_at: Optional[float] = None
    joined_at: Optional[float] = None
    excluded: bool = False

    @property
    def joined(self) -> bool:
        return self.joined_at is not None


class PartyInviter:
    """forming → formed (everyone joined) | expired (window over, rest excluded)."""

    def __init__(
        self,
        names: list[str],
        *,
        window_s: float = FORM_WINDOW_S,
        every_s: float = INVITE_EVERY_S,
        clock: Callable[[], float] = time.monotonic,
        log: Callable[[str], None] = lambda _m: None,
    ) -> None:
        self._clock = clock
        self._log = log
        self.window_s = float(window_s)
        self.every_s = max(1.0, float(every_s))
        self.started_at = clock()
        self.deadline = self.started_at + self.window_s
        self.rows = [InviteRow(n) for n in names]
        self.state = FORMED if not self.rows else FORMING
        self.sent: list[str] = []

    @property
    def active(self) -> bool:
        return self.state == FORMING

    def remaining_s(self) -> float:
        return max(0.0, self.deadline - self._clock())

    def missing(self) -> list[str]:
        return [r.name for r in self.rows if not r.joined]

    def excluded(self) -> list[str]:
        return [r.name for r in self.rows if r.excluded]

    def observe(self, snapshot: Any) -> None:
        """Mark names party memory now lists (late joins after the window too)."""
        in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
        present = _member_names(snapshot) if in_party else set()
        now = self._clock()
        for row in self.rows:
            if row.joined_at is None and row.name.casefold() in present:
                row.joined_at = now
                was_out = row.excluded
                row.excluded = False
                self._log(
                    f'Party: "{row.name}" joined'
                    + (" (after the window)" if was_out else f" after {row.invites} invite(s)")
                )

    def tick(
        self,
        snapshot: Any,
        *,
        send_line: Callable[[str], bool],
        can_send: bool = True,
    ) -> Optional[str]:
        """One step: update joins, expire, or send at most one due invite."""
        self.observe(snapshot)
        if self.state != FORMING:
            return None
        if all(r.joined for r in self.rows):
            self.state = FORMED
            self._log("Party formed — every roster member joined")
            return None
        now = self._clock()
        if now >= self.deadline:
            self.state = EXPIRED
            for row in self.rows:
                if not row.joined:
                    row.excluded = True
            mins = int(self.window_s // 60)
            self._log(
                f"Party invite window over ({mins} min) — excluded: "
                + (", ".join(self.excluded()) or "—")
            )
            return None
        if not can_send:
            return None
        due = [
            r for r in self.rows
            if not r.joined and (r.last_at is None or now - r.last_at >= self.every_s)
        ]
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
            "window_s": self.window_s,
            "every_s": self.every_s,
            "remaining_s": round(self.remaining_s(), 1),
            "elapsed_s": round(now - self.started_at, 1),
            "names": [r.name for r in self.rows],
            "sent": list(self.sent),
            "excluded": self.excluded(),
            "rows": [
                {
                    "name": r.name,
                    "invites": r.invites,
                    "failed": r.failed,
                    "last_ago_s": (
                        round(now - r.last_at, 1) if r.last_at is not None else None
                    ),
                    "joined": r.joined,
                    "excluded": r.excluded,
                }
                for r in self.rows
            ],
        }


class LeaderInvites:
    """One per Start: policy first, leave if needed, then invites per tick."""

    def __init__(
        self,
        *,
        publish_policy: Callable[[], Any] = lambda: None,
        ws_clients: Callable[[], int] = lambda: 0,
        send_chat: Optional[Callable[[str], bool]] = None,
        wait: Callable[[float], Any] = time.sleep,
        log: Callable[[str], None] = lambda _m: None,
        clock: Callable[[], float] = time.monotonic,
        window_s: Optional[float] = None,
        every_s: Optional[float] = None,
        policy_wait_s: Optional[float] = None,
    ) -> None:
        self._publish_policy = publish_policy
        self._ws_clients = ws_clients
        self._send_chat = send_chat
        self._wait = wait
        self._log = log
        self._clock = clock
        self.window_s = float(FORM_WINDOW_S if window_s is None else window_s)
        self.every_s = float(INVITE_EVERY_S if every_s is None else every_s)
        self.policy_wait_s = float(POLICY_WAIT_S if policy_wait_s is None else policy_wait_s)
        self.inviter: Optional[PartyInviter] = None
        self.info: dict[str, Any] = {}
        self._policy_clients = 0

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

    def start(self, names: Any, *, snapshot: Any, self_name: str) -> bool:
        """Publish policy, leave a foreign party, arm the inviter. False = leave failed."""
        wanted = roster_invite_names(names, self_name)
        in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
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
        self.inviter = PartyInviter(
            wanted,
            window_s=self.window_s,
            every_s=self.every_s,
            clock=self._clock,
            log=self._log,
        )
        self.info = self.inviter.status()
        self._log(
            f"Party invite window {int(self.window_s // 60)} min: "
            f"/파티 every {int(self.every_s)}s until each member joins "
            f"({', '.join(wanted) or '—'})"
        )
        return True

    def tick(self, snapshot: Any, last_action: Any = None) -> Optional[str]:
        """One invite step; returns the line typed this tick, if any."""
        inviter = self.inviter
        if inviter is None:
            return None
        can_send = False
        if inviter.active:
            clients = self._clients()
            if clients > self._policy_clients:
                self._policy_clients = clients
                self._publish()
            policy_ready = clients >= len(inviter.rows) or (
                self._clock() - inviter.started_at >= self.policy_wait_s
            )
            can_send = policy_ready and action_allows_chat(last_action)
        line = inviter.tick(snapshot, send_line=self._say, can_send=can_send)
        self.info = inviter.status()
        return line


__all__ = [
    "EXPIRED",
    "FORMED",
    "FORMING",
    "FORM_WINDOW_S",
    "INVITE_EVERY_S",
    "INVITE_PREFIX",
    "LEAVE_COMMAND",
    "LEAVE_FAILED",
    "POLICY_WAIT_S",
    "UNSAFE_ACTIONS",
    "InviteRow",
    "LeaderInvites",
    "PartyInviter",
    "action_allows_chat",
    "deliver_chat",
    "invite_command",
    "needs_leave",
    "roster_invite_names",
]
