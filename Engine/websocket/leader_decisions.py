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
    # Mother-tree and the start rally have their own frames (recovery / rally).
    if name == "return_to_mother_tree":
        return ""
    if name == "shop_run" and str(getattr(action, "shop_kind", "") or "") == "teleporter":
        return ""
    key = _key(action, name)
    if key == _last_key:
        return ""
    body = _body(action, name, world, map_id)
    if publish_body(body) <= 0 and not _server_listening():
        return ""
    _last_key = key
    return name


def publish_body(body: dict[str, Any]) -> int:
    """Broadcast one leader payload. Returns how many clients received it."""
    from .active import current
    from .protocol import PartyMessage

    watchdog = current()
    if watchdog is None or not watchdog.running or not watchdog.server.listening:
        return 0
    try:
        return int(
            watchdog.server.broadcast(PartyMessage(sender="leader", message=body))
            or 0
        )
    except Exception:
        return 0


def _server_listening() -> bool:
    from .active import current

    watchdog = current()
    return bool(
        watchdog is not None and watchdog.running and watchdog.server.listening
    )


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
        "from": "leader",
        "action": name,
        "map_id": map_id,
        "x": x,
        "y": y,
        "gate_to": getattr(action, "gate_expect_map_id", None),
        "gate_edge": str(getattr(action, "gate_edge", "") or ""),
        "destination": (
            [getattr(dest, "x", None), getattr(dest, "y", None)]
            if dest is not None
            else None
        ),
    }


__all__ = ["CRITICAL_ACTIONS", "publish_body", "publish_leader_decision"]
