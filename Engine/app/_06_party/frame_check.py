"""Drop party frames that must not drive invite, policy, or rally.

Not authentication. Stops empty names, leader impersonation, oversized
fields, and mismatched hello names from entering the existing workflow.
"""
from __future__ import annotations

from typing import Any

_NAME_MAX = 16
_ID_MAX = 32
_RESERVED = frozenset({"", "member", "leader", "unknown", "server", "?", "-"})

_MEMBER_TYPES = frozenset({
    "member_hello",
    "member_state",
    "policy_ack",
    "invite_accept",
    "report",
    "beep",
})
_LEADER_TYPES = frozenset({
    "party_policy",
    "party_reports",
    "party_buffs",
    "rally",
    "recovery",
    "beep",
    "supply_drop",
    "supply_hold",
    "supply_stand",
})


def _text(value: Any, limit: int) -> str | None:
    """Trimmed text, or None when it contains controls or is too long."""
    if value is None:
        return ""
    if not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    if len(text) > limit:
        return None
    for ch in text:
        if ord(ch) < 32 or ch in "\\/\"'":
            return None
    return text


def character_name(value: Any) -> str:
    """A usable character name, or \"\" when it must not be booked."""
    text = _text(value, _NAME_MAX)
    if text is None or text.casefold() in _RESERVED:
        return ""
    return text


def reject_member_frame(body: Any) -> str:
    """Why a member → leader frame is unusable. \"\" means keep it."""
    if not isinstance(body, dict):
        return "not an object"
    kind = _text(body.get("type"), 32)
    if kind is None or kind not in _MEMBER_TYPES:
        return "bad type"
    who = _text(body.get("from"), _NAME_MAX)
    if who is None:
        return "bad from"
    if who.casefold() == "leader":
        return "member frame claims leader"
    if kind == "member_hello":
        character = body.get("character")
        if not isinstance(character, dict):
            return "hello without character"
        name = character_name(character.get("name"))
        if not name:
            return "hello without a real name"
        if who and who.casefold() not in _RESERVED and who != name:
            return "hello name mismatch"
    cid = body.get("client_id")
    if cid not in (None, "") and _text(cid, _ID_MAX) is None:
        return "bad client_id"
    session = body.get("session")
    if session not in (None, "") and _text(session, _ID_MAX) is None:
        return "bad session"
    return ""


def reject_leader_frame(body: Any) -> str:
    """Why a leader → member frame is unusable. \"\" means keep it."""
    if not isinstance(body, dict):
        return "not an object"
    kind = _text(body.get("type"), 32)
    if kind is None or kind not in _LEADER_TYPES:
        return "bad type"
    who = _text(body.get("from"), _NAME_MAX)
    if who is None or who.casefold() != "leader":
        return "not from leader"
    if kind == "party_policy":
        if _text(body.get("policy_id"), _ID_MAX) in (None, ""):
            return "policy without id"
        mode = _text(body.get("leader_mode"), 16)
        if mode not in ("turret", "moving"):
            return "bad leader_mode"
        roster = body.get("roster")
        if not isinstance(roster, list):
            return "policy roster not a list"
        for row in roster:
            if isinstance(row, dict):
                if not character_name(row.get("name")):
                    return "bad roster name"
            elif not character_name(row):
                return "bad roster name"
    if kind == "rally":
        for key in ("map_id", "x", "y"):
            try:
                int(body.get(key))
            except (TypeError, ValueError):
                return f"rally missing {key}"
    return ""


__all__ = [
    "character_name",
    "reject_leader_frame",
    "reject_member_frame",
]
