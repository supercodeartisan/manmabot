"""Leader startup: leave if needed, then invite the roster by chat.

Lines come from :mod:`chat_commands`. Delivery is the caller's ``send_line``
(the bot passes ``app._05_action.chat``), so this module stays input-free.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .chat_commands import INVITE_PREFIX, LEAVE_COMMAND, invite_command

# After a failed invite: wait this long, then try again (up to this many times).
INVITE_RETRIES = 3
INVITE_RETRY_S = 30.0


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


def configure_party_from_roster(
    *,
    names: list[str],
    send_line: Callable[[str], bool],
    snapshot: Optional[dict[str, Any]] = None,
    self_name: str = "",
    sleep: Optional[Callable[[float], None]] = None,
    stopped: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Leave if this character cannot invite, then invite each missing name.

    ``send_line`` returns True when the line reached the game. A failed invite
    is retried up to ``INVITE_RETRIES`` times (``INVITE_RETRY_S`` between tries),
    then the next roster name is still attempted. A failed leave stops the run
    (this character cannot invite). Returns the lines that were delivered.
    """
    note = log or (lambda _m: None)
    halt = stopped or (lambda: False)
    nap = sleep or time.sleep
    wanted = roster_invite_names(names, self_name)
    sent: list[str] = []
    if not wanted:
        note("Party roster empty — no invitations")
        return sent

    def deliver(line: str, reason: str = "") -> bool:
        note(f'Party chat "{line}"{f" ({reason})" if reason else ""}')
        if not send_line(line):
            note(f'Party chat "{line}" not delivered')
            return False
        sent.append(line)
        return True

    def invite_with_retries(line: str) -> bool:
        attempts = 1 + int(INVITE_RETRIES)
        for n in range(1, attempts + 1):
            if halt():
                return False
            if deliver(line):
                return True
            if n >= attempts:
                break
            note(
                f'Party chat "{line}" retry {n}/{INVITE_RETRIES} '
                f"in {int(INVITE_RETRY_S)}s"
            )
            nap(float(INVITE_RETRY_S))
        return False

    in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
    present = _member_names(snapshot) if in_party else set()
    if in_party and not _local_is_leader(snapshot, self_name):
        if halt() or not deliver(LEAVE_COMMAND, "not the in-game leader"):
            return sent
        nap(1.0)
        present = set()

    for name in wanted:
        if halt():
            break
        if name.casefold() in present:
            note(f'Party already has "{name}" — skip invite')
            continue
        if invite_with_retries(invite_command(name)):
            present.add(name.casefold())
        nap(0.55)
    return sent


__all__ = [
    "INVITE_PREFIX",
    "INVITE_RETRIES",
    "INVITE_RETRY_S",
    "LEAVE_COMMAND",
    "configure_party_from_roster",
    "invite_command",
    "roster_invite_names",
]
