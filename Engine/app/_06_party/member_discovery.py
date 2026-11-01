"""Leader-side discovery: keep connections the roster filter used to drop.

Does not invite, apply policy, or edit the saved roster. MATCHED names go
through the existing member_state / invite workflow. Everyone else stays here
until P1 approval.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class MembershipStatus(str, Enum):
    MATCHED = "MATCHED"
    MISSING = "MISSING"
    PENDING = "PENDING"
    UNIDENTIFIED = "UNIDENTIFIED"
    CONFLICT = "CONFLICT"


def _key(name: Any) -> str:
    return str(name or "").strip().casefold()


def _roster_names(roster: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in roster or []:
        if isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
        else:
            name = str(raw or "").strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


@dataclass
class DiscoveredMember:
    connection_id: str
    name: str = ""
    character_class: str = ""
    level: Optional[int] = None
    status: MembershipStatus = MembershipStatus.UNIDENTIFIED
    at: float = 0.0
    frames: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "name": self.name,
            "class": self.character_class,
            "level": self.level,
            "status": self.status.value,
            "at": self.at,
            "frames": self.frames,
        }


class MemberDiscovery:
    """One row per member ``client_id`` (not the transient WebSocket ``cN``)."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.by_connection: dict[str, DiscoveredMember] = {}

    def clear(self) -> None:
        self.by_connection.clear()

    def observe(
        self,
        *,
        connection_id: str,
        name: str = "",
        character_class: str = "",
        level: Any = None,
        roster: Any = None,
    ) -> DiscoveredMember:
        cid = str(connection_id or "").strip() or "_anon"
        incoming = str(name or "").strip()
        prev = self.by_connection.get(cid)
        # Keep the last real name if this frame is still unnamed.
        from .member_identity import CharacterIdentity

        if not CharacterIdentity(name=incoming).is_valid() and prev is not None:
            if CharacterIdentity(name=prev.name).is_valid():
                incoming = prev.name
                if not character_class:
                    character_class = prev.character_class
                if level is None:
                    level = prev.level

        ident = CharacterIdentity(name=incoming)
        roster_by_key = {n.casefold(): n for n in _roster_names(roster)}
        if not ident.is_valid():
            status = MembershipStatus.UNIDENTIFIED
            incoming = ""
        else:
            claimants = [
                row
                for row in self.by_connection.values()
                if row.connection_id != cid
                and _key(row.name) == incoming.casefold()
                and row.status
                in (
                    MembershipStatus.MATCHED,
                    MembershipStatus.PENDING,
                    MembershipStatus.CONFLICT,
                )
            ]
            if claimants:
                status = MembershipStatus.CONFLICT
                for other in claimants:
                    other.status = MembershipStatus.CONFLICT
            elif incoming.casefold() in roster_by_key:
                status = MembershipStatus.MATCHED
                incoming = roster_by_key[incoming.casefold()]
            else:
                status = MembershipStatus.PENDING

        try:
            lvl = int(level) if level is not None else None
        except (TypeError, ValueError):
            lvl = None

        row = DiscoveredMember(
            connection_id=cid,
            name=incoming,
            character_class=str(character_class or "") or (
                prev.character_class if prev is not None else ""
            ),
            level=lvl if lvl is not None else (prev.level if prev is not None else None),
            status=status,
            at=time.time(),
            frames=(prev.frames if prev is not None else 0) + 1,
        )
        self.by_connection[cid] = row
        return row

    def snapshot(self, roster: Any = None) -> dict[str, Any]:
        names = _roster_names(roster)
        rows = [row.as_dict() for row in self.by_connection.values()]
        matched = {
            _key(r["name"])
            for r in rows
            if r.get("status") == MembershipStatus.MATCHED.value and r.get("name")
        }
        pending = [r for r in rows if r.get("status") == MembershipStatus.PENDING.value]
        unidentified = [
            r for r in rows if r.get("status") == MembershipStatus.UNIDENTIFIED.value
        ]
        conflict = [r for r in rows if r.get("status") == MembershipStatus.CONFLICT.value]
        missing = [n for n in names if n.casefold() not in matched]
        return {
            "members": rows,
            "pending": pending,
            "unidentified": unidentified,
            "conflict": conflict,
            "missing": missing,
            "matched": sorted(matched),
            "pending_count": len(pending),
            "unidentified_count": len(unidentified),
            "conflict_count": len(conflict),
        }


discovery = MemberDiscovery()


__all__ = [
    "DiscoveredMember",
    "MemberDiscovery",
    "MembershipStatus",
    "discovery",
]
