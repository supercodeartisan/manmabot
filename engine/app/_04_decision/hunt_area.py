"""Hunt/Attack area-switch watches: empty, low Adena yield, nearby players."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from app._03_world.constants import LOCAL_PLAYER_TRACK_ID
from app._03_world.objects import ObjectType
from app._04_decision import player_mode as pm
from app._04_decision.combat_query import object_on_screen
from app._04_decision.farm_time import is_inside_active_farm

if TYPE_CHECKING:
    from app._03_world import GameState
    from app._04_decision.blackboard import Blackboard


def current_adena(state: "GameState") -> Optional[int]:
    player = getattr(state, "player", None)
    inv = getattr(player, "inventory", None) if player is not None else None
    if inv is None:
        return None
    if not bool(getattr(inv, "bag_ready", False)):
        return None
    try:
        return max(0, int(getattr(inv, "adena", 0) or 0))
    except (TypeError, ValueError):
        return None


def reset_area_watch(blackboard: "Blackboard", state: "GameState | None" = None) -> None:
    """Start a fresh empty / yield window for the current farm stay."""
    blackboard.farm_empty_since = 0.0
    blackboard.farm_watch_started = time.time()
    adena = current_adena(state) if state is not None else None
    blackboard.farm_adena_start = -1 if adena is None else int(adena)


def nearby_other_players(state: "GameState") -> int:
    """On-screen other characters (local player excluded)."""
    players = []
    if hasattr(state, "players"):
        try:
            players = list(state.players() or [])
        except Exception:
            players = []
    count = 0
    for obj in players:
        if obj is None:
            continue
        if getattr(obj, "object_type", None) is not ObjectType.PLAYER:
            continue
        tid = getattr(obj, "track_id", None)
        if tid is not None and int(tid) == int(LOCAL_PLAYER_TRACK_ID):
            continue
        if object_on_screen(obj):
            count += 1
    return count


def _ensure_watch(blackboard: "Blackboard", state: "GameState") -> None:
    if float(getattr(blackboard, "farm_watch_started", 0.0) or 0.0) <= 0:
        reset_area_watch(blackboard, state)
        return
    if int(getattr(blackboard, "farm_adena_start", -1)) < 0:
        adena = current_adena(state)
        if adena is not None:
            blackboard.farm_adena_start = int(adena)


def rotate_reason(state: "GameState", blackboard: "Blackboard") -> Optional[str]:
    """Why the current farm should be left, or None to stay.

    Empty / yield clocks only run while the character is inside the active
    farm. Nearby-player count can fire from the same stay.
    """
    if not is_inside_active_farm(blackboard):
        blackboard.farm_empty_since = 0.0
        return None
    _ensure_watch(blackboard, state)
    now = time.time()

    if pm.AREA_PLAYERS_ENABLED:
        if nearby_other_players(state) >= int(pm.AREA_PLAYER_COUNT):
            return "nearby players"

    attackable = 0
    try:
        from app._04_decision.combat_query import count_attackable

        attackable = int(
            count_attackable(
                state, origin=blackboard.world_origin, check_path=False,
            )
        )
    except Exception:
        attackable = 0

    if pm.AREA_EMPTY_ENABLED:
        if attackable > 0:
            blackboard.farm_empty_since = 0.0
        else:
            started = float(getattr(blackboard, "farm_empty_since", 0.0) or 0.0)
            if started <= 0:
                blackboard.farm_empty_since = now
            elif now - started >= float(pm.AREA_EMPTY_SECONDS):
                return "no monsters"

    if pm.AREA_LOW_YIELD_ENABLED:
        watch = float(getattr(blackboard, "farm_watch_started", 0.0) or 0.0)
        if watch > 0 and now - watch >= float(pm.AREA_LOW_YIELD_SECONDS):
            adena = current_adena(state)
            start = int(getattr(blackboard, "farm_adena_start", -1))
            if adena is not None and start >= 0:
                gained = max(0, int(adena) - start)
                if gained < int(pm.AREA_LOW_YIELD_ADENA):
                    return "low adena yield"
    return None


__all__ = [
    "current_adena",
    "reset_area_watch",
    "nearby_other_players",
    "rotate_reason",
]
