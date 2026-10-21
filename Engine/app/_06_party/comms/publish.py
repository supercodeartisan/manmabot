"""Leader → members: decision / recovery / body broadcast."""
from __future__ import annotations

from typing import Any, Optional


def publish_body(body: dict[str, Any]) -> int:
    from websocket.leader_decisions import publish_body as _publish

    return int(_publish(body) or 0)


def publish_leader_decision(
    action: Any,
    world: Any = None,
    *,
    map_id: Optional[int] = None,
) -> str:
    from websocket.leader_decisions import publish_leader_decision as _pub

    return str(_pub(action, world, map_id=map_id) or "")


def publish_recovery(
    *,
    map_id: Optional[int],
    x: Optional[int],
    y: Optional[int],
) -> int:
    from .orders import recovery_message

    return publish_body(recovery_message(map_id=map_id, x=x, y=y))


def publish_policy(**kwargs: Any) -> int:
    from .orders import policy_message

    return publish_body(policy_message(**kwargs))


__all__ = [
    "publish_body",
    "publish_leader_decision",
    "publish_policy",
    "publish_recovery",
]
