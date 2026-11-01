"""Local character identity for member hello / roster matching.

Uses fields that actually exist on the live player object. There is no
``server_id`` or ``character_name`` on GameState — do not invent them.
Empty / reserved names are not sent (no ``UNKNOWN`` placeholder).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

PROTOCOL_VERSION = 2
MEMBER_HELLO = "member_hello"

# Sent as ``from`` / name when the member does not yet know itself. Never
# treat these as a real character.
_RESERVED = frozenset({"", "member", "leader", "unknown", "server"})


@dataclass(frozen=True)
class CharacterIdentity:
    name: str
    character_class: Optional[str] = None
    level: Optional[int] = None

    @property
    def character_key(self) -> str:
        return str(self.name or "").strip()

    def is_valid(self) -> bool:
        return str(self.name or "").strip().casefold() not in _RESERVED


def class_token(character_type: Any) -> Optional[str]:
    """``CharacterType.ELF`` → ``ELF``. Unknown objects → None."""
    if character_type is None:
        return None
    token = getattr(character_type, "name", None)
    if token:
        return str(token)
    text = str(character_type).strip()
    return text or None


def name_on_roster(name: Any, roster: Any) -> bool:
    """True when ``name`` is a real character listed on the leader roster."""
    key = str(name or "").strip().casefold()
    if key in _RESERVED:
        return False
    for raw in roster or []:
        if isinstance(raw, dict):
            other = str(raw.get("name") or "").strip()
        else:
            other = str(raw or "").strip()
        if other and other.casefold() == key:
            return True
    return False


def build_member_hello(
    identity: CharacterIdentity,
    *,
    client_id: str = "",
    farm_mode: str = "",
) -> Optional[dict[str, Any]]:
    """``member_hello`` body, or None when the name is not yet known."""
    if not identity.is_valid():
        return None
    character: dict[str, Any] = {"name": identity.character_key}
    if identity.character_class:
        character["class"] = identity.character_class
    if identity.level is not None:
        try:
            character["level"] = int(identity.level)
        except (TypeError, ValueError):
            pass
    body: dict[str, Any] = {
        "type": MEMBER_HELLO,
        "protocol_version": PROTOCOL_VERSION,
        "from": identity.character_key,
        "character": character,
    }
    cid = str(client_id or "").strip()
    if cid:
        body["client_id"] = cid
    mode = str(farm_mode or "").strip()
    if mode:
        body["settings"] = {"farm_mode": mode}
    return body


__all__ = [
    "MEMBER_HELLO",
    "PROTOCOL_VERSION",
    "CharacterIdentity",
    "build_member_hello",
    "class_token",
    "name_on_roster",
]
