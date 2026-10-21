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


def send_policy_ack(client: Any, *, name: str, policy_id: str) -> bool:
    """Tell the leader this member applied ``policy_id``. False = link down."""
    from websocket.protocol import PartyMessage

    from .orders import policy_ack_message

    if client is None or not getattr(client, "connected", False):
        return False
    body = policy_ack_message(name=name, policy_id=policy_id)
    client.send(PartyMessage(sender=body["from"], message=body))
    return True


def send_member_state(client: Any, body: dict) -> bool:
    """One ``member_state`` frame (built by ``sync.MemberStateReporter``)."""
    from websocket.protocol import PartyMessage

    if client is None or not getattr(client, "connected", False):
        return False
    client.send(PartyMessage(sender=str(body.get("from") or "member"), message=body))
    return True


__all__ = ["send_member_state", "send_member_status", "send_policy_ack"]
