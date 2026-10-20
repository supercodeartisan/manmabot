"""In-game party chat lines (typed into the chat input, then Enter).

- ``/파티 <name>``  invite a character
- ``파티탈퇴``       leave the current party
"""
from __future__ import annotations

INVITE_PREFIX = "/파티 "
LEAVE_COMMAND = "파티탈퇴"


def invite_command(name: str) -> str:
    return f"{INVITE_PREFIX}{str(name or '').strip()}".rstrip()


__all__ = ["INVITE_PREFIX", "LEAVE_COMMAND", "invite_command"]
