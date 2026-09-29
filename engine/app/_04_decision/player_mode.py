"""Session-level player modes for Decision."""
from __future__ import annotations

from enum import Enum


class PlayerMode(Enum):
    """Sticky high-level state; ActionType is still the per-tick intent."""

    TRAVELING = "traveling"
    FARMING = "farming"
    RETREATING = "retreating"
    # TRADING reserved for later


# HP thresholds (shared Traveling / Farming / Retreating).
HP_CRITICAL_RATIO = 0.30
HP_LOW_RATIO = 0.55
HP_ALMOST_FULL_RATIO = 0.90
HP_FULL_RATIO = 0.99
# No heal skill and no red potions (or they ran out): leave retreat at this HP
# instead of waiting for almost-full / full natural regen.
HP_PASSIVE_RECOVER_RATIO = 0.50
# Below this level: field HP skips heal/potions; mother tree or talking scroll.
LOW_LEVEL_HP_CAP = 15

# Fix/Recovery consumable / heal gates (schedule Recovery page).
HP_RECOVER_ENABLED = True
USE_HP_POTION = True
USE_HEAL = True
MP_RECOVER_ENABLED = False
MP_POTION_RATIO = 0.30
USE_MP_POTION = False
RESURRECT_IF_DEAD = True

# Mage: return to nearest safe when MP falls to this ratio.
MP_ESCAPE_ENABLED = False
MP_LOW_RATIO = 0.15
# Leave MP retreat when MP recovers to this ratio.
MP_RECOVERED_RATIO = 0.90
# While idling in retreat (waiting to recover), HP ≤ this → teleport to
# another nearest painted safe (exclude the one we are already in / headed
# to). Talking-scroll landings skip this — they are already safe.
HP_IDLE_EMERGENCY_RATIO = 0.10
# Elf: Return to Mother Tree instead of random escape teleport (must have learned it).
ELF_MOTHER_TREE = True
# Ordered HP response. Default: heal → tree → red water → teleport → safe.
HP_ACTIONS: list = []

# Fix/Return 귀환 (town/safe via talking scroll preferred — not escape TP).
RETURN_HP_ENABLED = True
RETURN_HP_RATIO = 0.30
RETURN_MP_ENABLED = True
RETURN_MP_RATIO = 0.15
RETURN_IDLE_ENABLED = False
RETURN_IDLE_SECONDS = 60.0
# Map pack to return to after shopping (operator selected farms map).
HUNT_MAP_ID = "talking_island"

# Teleport card: emergency skill escape (PK / surround). Escape HP/MP still
# uses HP_CRITICAL_RATIO / MP_LOW_RATIO via begin_retreat.
RANDOM_TELEPORT_ENABLED = False
TELEPORT_ON_PLAYER = False
TELEPORT_WHEN_SURROUNDED = False
SURROUND_MONSTER_COUNT = 4
# Surround TP counts living monsters inside this Chebyshev radius only.
SURROUND_TILES = 2

# Travel used to engage when ≤ this many attackables; travel now ignores combat.
TRAVEL_MAX_ATTACKABLE = 2

# Farm loot-vs-combat.
LOOT_MAX_TILES = 7
# Axis-aligned box around the player (tile radii, not a Chebyshev disk).
# HP nearby-threat only. Combat vs loot no longer uses this box.
NEAR_MONSTER_WIDTH_TILES = 4
NEAR_MONSTER_HEIGHT_TILES = 5
# Click-attack from here (Chebyshev). Do not walk adjacent first.
# Elf bows reach 7–8 tiles; 0–6 must also fire from the current tile.
ATTACK_CLICK_TILES = 8
# Legacy close-range hold. Live unfinished sticky now beats loot at any range.
STICKY_LOOT_HOLD_TILES = 2
# Keep a memory pile even when its UV is slightly outside the window.
LOOT_KEEP_TILES = 8
# While standing or walking to a pile, an attackable monster this close
# interrupts loot (same radius either way).
LOOT_APPROACH_THREAT_TILES = 5
# Legacy alias; farm loot-vs-combat uses LOOT_APPROACH_THREAT_TILES for both.
POST_KILL_MELEE_TILES = 5
# Legacy Chebyshev alias used only when a caller still passes ``tiles=``.
LOOT_DANGER_TILES = 3
# Strong-hit escape: HP lost across this window (peak-to-current) → escape now.
# Wider than a combat decide/act cycle so a single big hit is not missed.
HP_SPIKE_WINDOW_S = 1.5
HP_SPIKE_DROP = 0.20
# Stand on the pile or within two tiles, then PICKUP.
# One tile was too tight: approach hops stop a cell short of the gold.
LOOT_PICKUP_TILES = 2
# Loot hop is done this close to the click waypoint. Farm ARRIVE_TILES (2)
# was too loose: the bot cancelled the walk early and issued a new click.
LOOT_HOP_ARRIVE_TILES = 1
# Approach stuck: unchanged WCS while walking toward an item (then 360° sweep).
LOOT_APPROACH_STUCK_TICKS = 8
LOOT_APPROACH_STUCK_SECONDS = 5.0
# After a pickup click, skip that pile until memory drops it (or this many ticks).
LOOT_CLICKED_COOLDOWN_TICKS = 8
# After a confirmed pickup click, do not stand idle. Next loot/combat is immediate.
LOOT_PICKUP_SETTLE_S = 0.0
# Max wait for that pile to leave memory before walking. Gone → move immediately.
# Short hold + re-click while listed; ghosts time out without a long IDLE.
LOOT_AWAIT_GONE_S = 0.8

# Legacy hard-stuck gate (kept for old configs). Live recovery uses unstick_seconds.
TRAVEL_STUCK_TICKS = 100
TRAVEL_STUCK_SECONDS = 10.0
# Same tile this long while walking (travel / search / loot)
# → 360° walkable clicks within unstick_radius.
TRAVEL_UNSTICK_SECONDS = 5.0
# Enter / next-farm A* empty: walk walkable tiles in this Chebyshev ring,
# then teleport / talking scroll. Does not change travel/search unstick.
ENTER_FARM_DETOUR_RADIUS = 5
# Attacking but the monster world tile is unchanged this long → sidestep
# ~2 tiles off the attack line (no teleport). A second wait gives up.
COMBAT_BLOCKED_UNSTICK_SECONDS = 2.0
COMBAT_BLOCKED_UNSTICK_RADIUS = 2
# This many standstill episodes inside the window → teleport / talking scroll.
UNSTICK_BURST_COUNT = 3
UNSTICK_BURST_WINDOW_S = 20.0
# If the player stays inside this Chebyshev bubble this long → TP / scroll.
# Separate from the 3× standstill burst (different intent).
UNSTICK_CONFINED_TILES = 5
UNSTICK_CONFINED_SECONDS = 13.0
# While a hop is active, issue a real walk click this often (fresh screen coords).
TRAVEL_RECLICK_SECONDS = 2.0
TRAVEL_UNSTICK_RADIUS = 3
# After every walkable tile inside this radius has been tried, teleport / scroll.
TRAVEL_UNSTICK_INNER_RADIUS = 2
# When travel/search hop cursor is not NORMAL, try nearby relative tiles.
# 1 = primary + Chebyshev-1 ring; 2 was ~25 snaps and stalled the loop.
TRAVEL_CURSOR_FALLBACK_RADIUS = 2
# Memory tile is exact; screen click can be off. Search this Chebyshev
# radius (tiles) around the entity until the attack cursor appears.
ATTACK_CURSOR_SEARCH_TILES = 0.2
# Loot clicks the pile UV and memory cell only. A neighbor hunt is NORMAL=walk.
LOOT_CURSOR_SEARCH_TILES = 0.0

# Loot filter.
LOOT_MODE_ALL = "all_items"
LOOT_MODE_ADENA = "adena_only"
DEFAULT_LOOT_MODE = LOOT_MODE_ALL
# When HUD bag fill exceeds this ratio, only pick adena (아데나).
LOOT_ADENA_WEIGHT_RATIO = 0.30

# Hunt/Attack tab — wired combat / area knobs (off keeps legacy behavior).
TARGET_DELAY_ENABLED = False
TARGET_DELAY_MIN_MS = 20
TARGET_DELAY_MAX_MS = 50
ANTIDOTE_AUTO = False
AREA_EMPTY_ENABLED = False
AREA_EMPTY_SECONDS = 60.0
AREA_LOW_YIELD_ENABLED = False
AREA_LOW_YIELD_ADENA = 1000
AREA_LOW_YIELD_SECONDS = 180.0
AREA_PLAYERS_ENABLED = False
AREA_PLAYER_COUNT = 3


__all__ = [
    "PlayerMode",
    "HP_CRITICAL_RATIO",
    "HP_LOW_RATIO",
    "HP_ALMOST_FULL_RATIO",
    "HP_FULL_RATIO",
    "HP_PASSIVE_RECOVER_RATIO",
    "LOW_LEVEL_HP_CAP",
    "HP_IDLE_EMERGENCY_RATIO",
    "HP_RECOVER_ENABLED",
    "USE_HP_POTION",
    "USE_HEAL",
    "MP_RECOVER_ENABLED",
    "MP_POTION_RATIO",
    "USE_MP_POTION",
    "RESURRECT_IF_DEAD",
    "ELF_MOTHER_TREE",
    "HP_ACTIONS",
    "MP_ESCAPE_ENABLED",
    "MP_LOW_RATIO",
    "MP_RECOVERED_RATIO",
    "RETURN_HP_ENABLED",
    "RETURN_HP_RATIO",
    "RETURN_MP_ENABLED",
    "RETURN_MP_RATIO",
    "RETURN_IDLE_ENABLED",
    "RETURN_IDLE_SECONDS",
    "HUNT_MAP_ID",
    "RANDOM_TELEPORT_ENABLED",
    "TELEPORT_ON_PLAYER",
    "TELEPORT_WHEN_SURROUNDED",
    "SURROUND_MONSTER_COUNT",
    "SURROUND_TILES",
    "TRAVEL_MAX_ATTACKABLE",
    "LOOT_MAX_TILES",
    "NEAR_MONSTER_WIDTH_TILES",
    "NEAR_MONSTER_HEIGHT_TILES",
    "ATTACK_CLICK_TILES",
    "STICKY_LOOT_HOLD_TILES",
    "LOOT_KEEP_TILES",
    "LOOT_APPROACH_THREAT_TILES",
    "POST_KILL_MELEE_TILES",
    "LOOT_DANGER_TILES",
    "HP_SPIKE_WINDOW_S",
    "HP_SPIKE_DROP",
    "LOOT_PICKUP_TILES",
    "LOOT_HOP_ARRIVE_TILES",
    "LOOT_APPROACH_STUCK_TICKS",
    "LOOT_APPROACH_STUCK_SECONDS",
    "LOOT_CLICKED_COOLDOWN_TICKS",
    "LOOT_PICKUP_SETTLE_S",
    "LOOT_AWAIT_GONE_S",
    "TRAVEL_STUCK_TICKS",
    "TRAVEL_STUCK_SECONDS",
    "TRAVEL_UNSTICK_SECONDS",
    "ENTER_FARM_DETOUR_RADIUS",
    "COMBAT_BLOCKED_UNSTICK_SECONDS",
    "COMBAT_BLOCKED_UNSTICK_RADIUS",
    "UNSTICK_BURST_COUNT",
    "UNSTICK_BURST_WINDOW_S",
    "UNSTICK_CONFINED_TILES",
    "UNSTICK_CONFINED_SECONDS",
    "TRAVEL_RECLICK_SECONDS",
    "TRAVEL_UNSTICK_RADIUS",
    "TRAVEL_UNSTICK_INNER_RADIUS",
    "TRAVEL_CURSOR_FALLBACK_RADIUS",
    "ATTACK_CURSOR_SEARCH_TILES",
    "LOOT_CURSOR_SEARCH_TILES",
    "LOOT_MODE_ALL",
    "LOOT_MODE_ADENA",
    "DEFAULT_LOOT_MODE",
    "LOOT_ADENA_WEIGHT_RATIO",
    "TARGET_DELAY_ENABLED",
    "TARGET_DELAY_MIN_MS",
    "TARGET_DELAY_MAX_MS",
    "ANTIDOTE_AUTO",
    "AREA_EMPTY_ENABLED",
    "AREA_EMPTY_SECONDS",
    "AREA_LOW_YIELD_ENABLED",
    "AREA_LOW_YIELD_ADENA",
    "AREA_LOW_YIELD_SECONDS",
    "AREA_PLAYERS_ENABLED",
    "AREA_PLAYER_COUNT",
]
