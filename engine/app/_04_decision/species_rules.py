"""Species rules: allow/deny filter, golem proximity, sleeping-golem hazards."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from app._03_world.objects import Position
from app._03_world.world_coords import (
    WorldOrigin,
    content_to_world,
    max_distance,
    relative_to_absolute,
    tile_chebyshev,
)

if TYPE_CHECKING:  # pragma: no cover
    from app._03_world import GameState
    from app._03_world.objects import WorldObject
    from app._04_decision.blackboard import Blackboard

# Sleeping stone golem (classifier fine label). Seeds a nav hazard.
SLEEPING_GOLEM_LABEL = "monster_골램_50"
# Any stone-golem family: only attackable within this Chebyshev tile range.
GOLEM_ENGAGE_TILES = 2
# Soft exclusion disk around a seen sleeper (absolute nav tiles).
GOLEM_HAZARD_RADIUS = 3
GOLEM_HAZARD_TTL_S = 60.0

# Substrings matched in species / detail / identity (case-insensitive).
_GOLEM_NEEDLES: tuple[str, ...] = (
    SLEEPING_GOLEM_LABEL,
    "돌골렘",
    "돌 골렘",
    "라바 골렘",
    "라바골렘",
    "골램",
    "골렘",
    "golem",
)
_SCARECROW_NEEDLES: tuple[str, ...] = ("허수아비", "scarecrow", "稻草人")
# Only characters below this level may attack 허수아비.
NEWBIE_LEVEL_CAP = 5


@dataclass(frozen=True)
class HazardZone:
    """Soft nav avoid disk in absolute map tiles."""

    x: int
    y: int
    radius: int
    expires_at: float
    source: str = "sleeping_golem"


def _species_blob(obj: "WorldObject") -> str:
    detail = (obj.detail_classification or "").strip().lower()
    species = (obj.species_name or "").strip().lower()
    name = ""
    if obj.identity is not None and getattr(obj.identity, "name", None):
        name = str(obj.identity.name).strip().lower()
    return f"{detail} {species} {name}"


def is_golem_species(obj: "WorldObject") -> bool:
    """True for stone-golem family (sleeping or active labels)."""
    blob = _species_blob(obj)
    return any(needle.lower() in blob for needle in _GOLEM_NEEDLES)


def is_sleeping_golem(obj: "WorldObject") -> bool:
    """True when the classifier reports the sleeping golem label."""
    return SLEEPING_GOLEM_LABEL.lower() in _species_blob(obj)


def is_scarecrow_species(obj: "WorldObject") -> bool:
    """True for Talking Island training dummies (허수아비)."""
    blob = _species_blob(obj)
    return any(needle.lower() in blob for needle in _SCARECROW_NEEDLES)


def is_newbie_player(game_state: "GameState") -> bool:
    """True when memory has loaded a character level below 5 (training trip)."""
    player = game_state.player
    if player is None or player.level is None:
        return False
    return 0 < int(player.level) < NEWBIE_LEVEL_CAP


def scarecrow_blocked_by_player_level(
    obj: "WorldObject",
    player_level: int | None,
) -> bool:
    """True when this 허수아비 is off-limits (level 5+ or unknown)."""
    if not is_scarecrow_species(obj):
        return False
    if player_level is None:
        return True
    try:
        level = int(player_level)
    except (TypeError, ValueError):
        return True
    return level < 1 or level >= NEWBIE_LEVEL_CAP


def scarecrows_ignored(game_state: "GameState") -> bool:
    """True when the live character is not under 5 and must skip 허수아비."""
    return not is_newbie_player(game_state)


def tile_distance_from_player(obj: "WorldObject") -> int:
    """Chebyshev tiles from local player (relative WCS origin) to object."""
    from app._03_world.world_coords import distance_tiles_from_memory

    known = distance_tiles_from_memory(obj)
    if known is not None:
        return known
    tile = content_to_world(obj.position.x, obj.position.y)
    return max_distance(tile, Position(0.0, 0.0))


def effective_player_level(game_state: "GameState") -> int:
    from app._03_world.constants import DEFAULT_PLAYER_LEVEL

    player = game_state.player
    if player is not None and player.level is not None:
        return int(player.level)
    return DEFAULT_PLAYER_LEVEL


def is_blacklisted_object(obj: "WorldObject") -> bool:
    """True when the operator filter turns this species off."""
    from app._03_world.constants import is_species_filtered_out

    return is_species_filtered_out(obj.species_name, obj.detail_classification)


def _is_golem_catalog_name(display: str) -> bool:
    text = display.strip().lower()
    return any(needle.lower() in text for needle in _GOLEM_NEEDLES)


def golem_required_player_level(obj: "WorldObject") -> int | None:
    """Minimum character level that may attack this golem.

    Uses the operator forced level from the monster blacklist/whitelist
    table when set, otherwise the catalog default (돌 골렘 13, 라바 골렘 43).
    Sleeping-golem suffix labels are ignored — those are never engaged.
    """
    from app._03_world.constants import (
        list_species_catalog,
        monster_level_for_object,
        monster_level_from_species,
        species_display_name,
    )

    if is_sleeping_golem(obj):
        return None

    level = monster_level_for_object(obj.species_name, obj.detail_classification)
    if level is not None:
        return level

    blob = _species_blob(obj)
    matched: int | None = None
    matched_len = 0
    for key, _default in list_species_catalog():
        display = species_display_name(key)
        if not _is_golem_catalog_name(display):
            continue
        folded = display.strip().lower()
        compact = folded.replace(" ", "")
        if folded not in blob and compact not in blob:
            continue
        resolved = monster_level_from_species(key)
        if resolved is None:
            continue
        if len(folded) >= matched_len:
            matched = resolved
            matched_len = len(folded)
    return matched


def golem_blocked_by_player_level(
    obj: "WorldObject",
    player_level: int | None,
) -> bool:
    """True when the player is below this golem's forced/catalog level.

    Missing character level is treated as too low. No resolvable species
    level leaves the legacy proximity-only rule in place.
    """
    if not is_golem_species(obj) or is_sleeping_golem(obj):
        return False
    required = golem_required_player_level(obj)
    if required is None:
        return False
    if player_level is None:
        return True
    return int(player_level) < int(required)


def is_avoided_species(
    obj: "WorldObject",
    player_level: int | None = None,
) -> bool:
    """True when this monster should not be newly engaged.

    Operator allow/deny (blacklist/whitelist) is the only species gate,
    except 허수아비 at level 5+ and sleeping golems. Player vs monster
    level is not compared. Active golems still require
    :data:`GOLEM_ENGAGE_TILES` so a far statue is not pulled.
    """
    if is_blacklisted_object(obj):
        return True
    if is_sleeping_golem(obj):
        return True
    if scarecrow_blocked_by_player_level(obj, player_level):
        return True
    if is_golem_species(obj):
        return tile_distance_from_player(obj) > GOLEM_ENGAGE_TILES
    return False


def is_avoided_for_state(game_state: "GameState", obj: "WorldObject") -> bool:
    player = getattr(game_state, "player", None)
    level = getattr(player, "level", None) if player is not None else None
    return is_avoided_species(obj, player_level=level)


def object_absolute_tile(
    obj: "WorldObject",
    origin: WorldOrigin,
) -> tuple[int, int]:
    from app._03_world.world_coords import memory_nav_tile

    cell = memory_nav_tile(obj)
    if cell is not None:
        return cell
    rel = content_to_world(obj.position.x, obj.position.y)
    return relative_to_absolute(rel.x, rel.y, origin)


def sync_sleeping_golem_hazards(
    game_state: "GameState",
    blackboard: "Blackboard",
    *,
    now: float | None = None,
) -> None:
    """Refresh hazard disks from visible sleeping golems; drop expired ones."""
    t = time.time() if now is None else float(now)
    origin = blackboard.world_origin
    zones = list(getattr(blackboard, "hazard_zones", []) or [])

    # Expire old.
    zones = [z for z in zones if z.expires_at > t]

    # Upsert / refresh from current vision (quantize to tile).
    by_tile: dict[tuple[int, int], HazardZone] = {
        (z.x, z.y): z for z in zones
    }
    for obj in game_state.monsters():
        if not is_sleeping_golem(obj):
            continue
        ax, ay = object_absolute_tile(obj, origin)
        by_tile[(ax, ay)] = HazardZone(
            x=ax,
            y=ay,
            radius=GOLEM_HAZARD_RADIUS,
            expires_at=t + GOLEM_HAZARD_TTL_S,
            source=SLEEPING_GOLEM_LABEL,
        )
    blackboard.hazard_zones = list(by_tile.values())


def tile_in_hazard(
    blackboard: "Blackboard",
    x: int,
    y: int,
    *,
    now: float | None = None,
) -> bool:
    """True when absolute tile ``(x,y)`` lies in an unexpired hazard disk."""
    t = time.time() if now is None else float(now)
    for z in getattr(blackboard, "hazard_zones", []) or []:
        if z.expires_at <= t:
            continue
        if tile_chebyshev(x, y, z.x, z.y) <= int(z.radius):
            return True
    return False


def active_hazard_zones(
    blackboard: "Blackboard",
    *,
    now: float | None = None,
) -> list[HazardZone]:
    t = time.time() if now is None else float(now)
    return [z for z in (getattr(blackboard, "hazard_zones", []) or []) if z.expires_at > t]


__all__ = [
    "SLEEPING_GOLEM_LABEL",
    "GOLEM_ENGAGE_TILES",
    "GOLEM_HAZARD_RADIUS",
    "GOLEM_HAZARD_TTL_S",
    "HazardZone",
    "NEWBIE_LEVEL_CAP",
    "is_golem_species",
    "is_sleeping_golem",
    "golem_required_player_level",
    "golem_blocked_by_player_level",
    "is_scarecrow_species",
    "is_newbie_player",
    "scarecrow_blocked_by_player_level",
    "scarecrows_ignored",
    "tile_distance_from_player",
    "effective_player_level",
    "is_avoided_species",
    "is_avoided_for_state",
    "is_blacklisted_object",
    "object_absolute_tile",
    "sync_sleeping_golem_hazards",
    "tile_in_hazard",
    "active_hazard_zones",
]
