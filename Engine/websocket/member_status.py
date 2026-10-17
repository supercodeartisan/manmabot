"""Member → leader: current player status every 10 seconds.

Does not change follow or combat. The member bot already decided what to do;
this only reports the live player.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .protocol import PartyMessage

HEARTBEAT_S = 10.0


class MemberHeartbeat:
    def __init__(self, client: Any) -> None:
        self.client = client
        self._next = 0.0

    def maybe_send(self, world: Any, *, map_id: Optional[int] = None) -> bool:
        """Send one status frame when the 10s interval has elapsed and the link is up."""
        now = time.monotonic()
        if now < self._next:
            return False
        client = self.client
        if client is None or not client.connected:
            return False
        client.send(PartyMessage(sender="member", message=_status(world, map_id)))
        self._next = now + HEARTBEAT_S
        return True


def _status(world: Any, map_id: Optional[int]) -> dict[str, Any]:
    player = getattr(world, "player", None)
    pos = getattr(player, "position", None)
    hp = getattr(player, "hp", None)
    max_hp = getattr(player, "max_hp", None)
    mp = getattr(player, "mp", None)
    max_mp = getattr(player, "max_mp", None)

    def _ratio(part: Any, whole: Any, fallback: Any) -> Optional[float]:
        try:
            if part is not None and whole:
                return round(float(part) / float(whole), 3)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        try:
            return round(float(fallback), 3)
        except (TypeError, ValueError):
            return None

    return {
        "type": "player",
        "hp": hp,
        "max_hp": max_hp,
        "mp": mp,
        "max_mp": max_mp,
        "hp_ratio": _ratio(hp, max_hp, getattr(player, "hp_ratio", None)),
        "mp_ratio": _ratio(mp, max_mp, getattr(player, "mp_ratio", None)),
        "alive": bool(getattr(player, "alive", True)),
        "level": getattr(player, "level", None),
        "x": getattr(pos, "x", None) if pos is not None else None,
        "y": getattr(pos, "y", None) if pos is not None else None,
        "map_id": map_id,
    }


__all__ = ["HEARTBEAT_S", "MemberHeartbeat"]
