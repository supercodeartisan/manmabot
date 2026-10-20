"""Leader startup: leave if needed, then invite the roster by chat.

In-game lines (type, then Enter):

- ``/초대 <name>``
- ``파티탈퇴``
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

LEAVE_COMMAND = "파티탈퇴"
INVITE_PREFIX = "/초대 "


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


def send_game_chat(text: str) -> bool:
    """Open chat, paste the line, send. Uses the hunt Interception path."""
    from autologin.bot.input.inputrouter import InputRouter

    line = str(text or "").strip()
    if not line:
        return False
    try:
        from session.probes import bring_game_to_front, probe_game

        game = probe_game()
        hwnd = int(getattr(game, "hwnd", 0) or 0)
        if hwnd:
            bring_game_to_front(hwnd)
            time.sleep(0.2)
    except Exception:
        pass
    if not InputRouter.physical_press_enter():
        InputRouter.press_enter()
    time.sleep(0.2)
    typed = InputRouter.physical_type_text(line)
    if not typed:
        InputRouter.type_text(line)
    time.sleep(0.2)
    if not InputRouter.physical_press_enter():
        InputRouter.press_enter()
    time.sleep(0.35)
    return True


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
    snapshot: Optional[dict[str, Any]] = None,
    self_name: str = "",
    send_line: Optional[Callable[[str], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    stopped: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Leave if this character cannot invite, then ``/초대`` each missing name.

    Returns the chat lines that were sent.
    """
    send = send_line or send_game_chat
    note = log or (lambda _m: None)
    halt = stopped or (lambda: False)
    wanted = roster_invite_names(names, self_name)
    sent: list[str] = []
    if not wanted:
        note("Party roster empty — no invitations")
        return sent

    in_party = bool(isinstance(snapshot, dict) and snapshot.get("in_party"))
    present = _member_names(snapshot) if in_party else set()
    if in_party and not _local_is_leader(snapshot, self_name):
        if halt():
            return sent
        note(f'Party chat "{LEAVE_COMMAND}" (not the in-game leader)')
        send(LEAVE_COMMAND)
        sent.append(LEAVE_COMMAND)
        sleep(1.0)
        present = set()

    for name in wanted:
        if halt():
            break
        if name.casefold() in present:
            note(f'Party already has "{name}" — skip invite')
            continue
        line = invite_command(name)
        # Exact in-game line: ``/초대 <member name>``
        note(f'Party chat "{line}"')
        send(line)
        sent.append(line)
        present.add(name.casefold())
        sleep(0.55)
    return sent


__all__ = [
    "INVITE_PREFIX",
    "LEAVE_COMMAND",
    "configure_party_from_roster",
    "invite_command",
    "roster_invite_names",
    "send_game_chat",
]
