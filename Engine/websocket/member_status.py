"""Member → leader: buffs and item list.

The 10s heartbeat carries the same report. Arrival at a hunt NPC sends one
immediately. Does not change follow or combat by itself.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from .party_orders import REPORT
from .protocol import PartyMessage

HEARTBEAT_S = 10.0


class MemberHeartbeat:
    def __init__(self, client: Any) -> None:
        self.client = client
        self._next = 0.0

    def maybe_send(
        self,
        world: Any,
        *,
        map_id: Optional[int] = None,
        name: str = "",
        x: Any = None,
        y: Any = None,
        arrived: bool = False,
    ) -> bool:
        """Send one report when the 10s interval has elapsed and the link is up."""
        now = time.monotonic()
        if now < self._next:
            return False
        return self.send_report(
            world,
            map_id=map_id,
            name=name,
            x=x,
            y=y,
            arrived=arrived,
        )

    def send_report(
        self,
        world: Any,
        *,
        map_id: Optional[int] = None,
        name: str = "",
        x: Any = None,
        y: Any = None,
        arrived: bool = False,
    ) -> bool:
        """Send buffs and items now."""
        client = self.client
        if client is None or not client.connected:
            return False
        who = str(name or "member").strip() or "member"
        client.send(
            PartyMessage(
                sender=who,
                message=_report(
                    world,
                    map_id,
                    name=who,
                    x=x,
                    y=y,
                    arrived=arrived,
                ),
            )
        )
        self._next = time.monotonic() + HEARTBEAT_S
        return True


def _report(
    world: Any,
    map_id: Optional[int],
    *,
    name: str,
    x: Any,
    y: Any,
    arrived: bool,
) -> dict[str, Any]:
    player = getattr(world, "player", None)
    pos = getattr(player, "position", None)
    if x is None and pos is not None:
        x = getattr(pos, "x", None)
    if y is None and pos is not None:
        y = getattr(pos, "y", None)
    return {
        "type": REPORT,
        "from": name,
        "buffs": _buffs(player),
        "items": _items(player),
        "map_id": map_id,
        "x": x,
        "y": y,
        "arrived": bool(arrived),
    }


def _buffs(player: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for buff in getattr(player, "buffs", None) or []:
        rows.append(
            {
                "name": str(getattr(buff, "name", "") or ""),
                "duration": getattr(buff, "duration", 0),
                "skill": getattr(buff, "skill", 0),
            }
        )
    return rows


def _items(player: Any) -> dict[str, Any]:
    inv = getattr(player, "inventory", None)
    rows: list[dict[str, Any]] = []
    for item in getattr(inv, "items", None) or []:
        rows.append(
            {
                "name": str(getattr(item, "name", "") or ""),
                "quantity": getattr(item, "quantity", 0),
            }
        )
    return {
        "adena": getattr(inv, "adena", 0) if inv is not None else 0,
        "hp_potion": getattr(inv, "hp_potion", 0) if inv is not None else 0,
        "mp_potion": getattr(inv, "mp_potion", 0) if inv is not None else 0,
        "arrows": getattr(inv, "arrows", 0) if inv is not None else 0,
        "list": rows,
    }


__all__ = ["HEARTBEAT_S", "MemberHeartbeat"]
