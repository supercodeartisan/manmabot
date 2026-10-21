"""Member → leader: heartbeat and arrival reports."""
from __future__ import annotations

from typing import Any, Optional


def send_member_status(
    beat: Any,
    world: Any,
    *,
    map_id: Optional[int] = None,
    name: str = "",
    x: Any = None,
    y: Any = None,
    force_report: bool = False,
) -> bool:
    """Send buffs/items. ``force_report`` = just arrived at the gather point."""
    from .orders import member_orders

    if beat is None:
        return False
    if force_report:
        return bool(
            beat.send_report(
                world,
                map_id=map_id,
                name=name,
                x=x,
                y=y,
                arrived=True,
                order=member_orders.order_kind,
            )
        )
    return bool(
        beat.maybe_send(
            world,
            map_id=map_id,
            name=name,
            x=x,
            y=y,
            arrived=bool(member_orders.arrived),
            order=member_orders.order_kind,
        )
    )


__all__ = ["send_member_status"]
