"""Leader → members: the few solo decisions that change the party.

The leader keeps the normal solo farm. This only copies a decision that
already happened and sends it on the party socket. Attack, loot, heal, and
walk ticks are not sent.
"""
from __future__ import annotations

from typing import Any, Optional

# These change where the party is or whether it is still farming.
CRITICAL_ACTIONS = frozenset(
    {
        "teleport",
        "return_to_mother_tree",
        "use_talking_scroll",
        "gate",
        "shop_run",
        "shop_stop",
        "respawn",
    }
)

_last_key: Optional[tuple] = None


def publish_leader_decision(
    action: Any,
    world: Any = None,
    *,
    map_id: Optional[int] = None,
) -> str:
    """Broadcast one critical decision. Returns the action name, or ""."""
    global _last_key
    name = _action_name(action)
    if name not in CRITICAL_ACTIONS:
        _last_key = None
        return ""
    key = _key(action, name)
    if key == _last_key:
        return ""
    from .active import current
    from .protocol import PartyMessage

    watchdog = current()
    if watchdog is None or not watchdog.running or not watchdog.server.listening:
        return ""
    body = _body(action, name, world, map_id)
    try:
        watchdog.server.broadcast(PartyMessage(sender="leader", message=body))
    except Exception:
        return ""
    _last_key = key
    return name


def _action_name(action: Any) -> str:
    token = getattr(action, "action", None)
    value = getattr(token, "value", None)
    if value:
        return str(value)
    return str(token or "")


def _key(action: Any, name: str) -> tuple:
    dest = getattr(action, "destination", None)
    xy = None
    if dest is not None:
        xy = (getattr(dest, "x", None), getattr(dest, "y", None))
    return (
        name,
        str(getattr(action, "reason", "") or ""),
        str(getattr(action, "shop_kind", "") or ""),
        str(getattr(action, "shop_behavior_id", "") or ""),
        getattr(action, "gate_expect_map_id", None),
        str(getattr(action, "gate_edge", "") or ""),
        xy,
    )


def _body(action: Any, name: str, world: Any, map_id: Optional[int]) -> dict[str, Any]:
    x = y = None
    player = getattr(world, "player", None)
    pos = getattr(player, "position", None)
    if pos is not None:
        x = getattr(pos, "x", None)
        y = getattr(pos, "y", None)
    dest = getattr(action, "destination", None)
    return {
        "type": "decision",
        "action": name,
        "reason": str(getattr(action, "reason", "") or ""),
        "map_id": map_id,
        "x": x,
        "y": y,
        "shop_kind": getattr(action, "shop_kind", None) or "",
        "shop_behavior_id": getattr(action, "shop_behavior_id", None) or "",
        "gate_to": getattr(action, "gate_expect_map_id", None),
        "gate_edge": str(getattr(action, "gate_edge", "") or ""),
        "destination": (
            [getattr(dest, "x", None), getattr(dest, "y", None)]
            if dest is not None
            else None
        ),
    }


__all__ = ["CRITICAL_ACTIONS", "publish_leader_decision"]
