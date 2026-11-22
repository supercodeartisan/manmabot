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
    "sighting",
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
    "make_way",
    "formation_path",
    "party_focus",
    "party_sync",
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
    if kind == "sighting":
        if not character_name(who):
            return "sighting without a name"
        try:
            int(body.get("map_id"))
        except (TypeError, ValueError):
            return "sighting without a tile"
        mobs = body.get("mobs")
        rows = mobs if isinstance(mobs, list) else [body]
        if not isinstance(mobs, list) and not str(body.get("species") or "").strip():
            return "sighting without species"
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("species") or "").strip():
                return "sighting without species"
            try:
                int(row.get("x"))
                int(row.get("y"))
            except (TypeError, ValueError):
                return "sighting without a tile"
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
    if kind == "party_sync":
        if str(body.get("run") or "") not in ("running", "paused"):
            return "bad sync run"
        phase = str(body.get("rally") or "")
        if phase not in ("pending", "active", "done"):
            return "bad sync rally"
        try:
            int(body.get("rev"))
        except (TypeError, ValueError):
            return "bad sync rev"
        if phase == "active":
            for key in ("map_id", "x", "y"):
                try:
                    int(body.get(key))
                except (TypeError, ValueError):
                    return f"sync missing {key}"
    if kind == "rally":
        for key in ("map_id", "x", "y"):
            try:
                int(body.get(key))
            except (TypeError, ValueError):
                return f"rally missing {key}"
    if kind == "formation_path":
        try:
            int(body.get("map_id"))
            int(body.get("rev"))
            int(body.get("seq"))
        except (TypeError, ValueError):
            return "bad formation_path"
        if not bool(body.get("clear")):
            tiles = body.get("tiles")
            if not isinstance(tiles, list) or not tiles or len(tiles) > 32:
                return "bad formation_path"
            for tile in tiles:
                try:
                    int(tile[0])
                    int(tile[1])
                except (TypeError, ValueError, IndexError):
                    return "bad formation_path"
    if kind == "party_focus" and not bool(body.get("clear")):
        if not str(body.get("species") or "").strip():
            return "focus without species"
        try:
            int(body.get("map_id"))
            int(body.get("x"))
            int(body.get("y"))
        except (TypeError, ValueError):
            return "focus without a tile"
    return ""


__all__ = [
    "character_name",
    "reject_leader_frame",
    "reject_member_frame",
]
