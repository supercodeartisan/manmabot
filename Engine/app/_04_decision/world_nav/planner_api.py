"""World-nav planner API — engine ``ready`` package + ``data/world_nav``."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _planner_mod() -> Any:
    from .ready import planner as mod

    return mod


@lru_cache(maxsize=1)
def _nav_state_log() -> Any:
    from .ready import nav_state_log as mod

    return mod


def Pose(*args: Any, **kwargs: Any) -> Any:
    return _planner_mod().Pose(*args, **kwargs)


def Goal(*args: Any, **kwargs: Any) -> Any:
    return _planner_mod().Goal(*args, **kwargs)


def plan(
    start: Any,
    goal: Any,
    *,
    has_talking_scroll: bool = True,
    adena: int | None = None,
    use_npc_teleporters: bool = True,
) -> Any:
    return _planner_mod().plan(
        start,
        goal,
        has_talking_scroll=has_talking_scroll,
        adena=adena,
        use_npc_teleporters=use_npc_teleporters,
    )


def map_goal(map_id: int) -> Any:
    return _planner_mod().Goal.map_goal(map_id)


def point_goal(map_id: int, x: int, y: int) -> Any:
    return _planner_mod().Goal.point_goal(map_id, x, y)


def emit_state(state: str, **fields: Any) -> str:
    nslog = _nav_state_log()
    return nslog.emit(state, None, **fields)


def state_tokens() -> Any:
    return _nav_state_log()
