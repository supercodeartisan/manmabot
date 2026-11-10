"""Named behavior columns — ids match Docs/architecture/DECISION_STEPS.md.

Modes stay few (PlayerMode). Each mode tick runs one of these columns
top-to-bottom (first non-None Status wins).
"""
from __future__ import annotations

# tick_mode prefix (before PlayerMode dispatch)
GLOBAL: tuple[str, ...] = (
    "survival.death",
    "ui.dismiss_level_up",
)

# Sticky PlayerMode.WORLD_NAV — cross-map routine session
WORLD_NAV: tuple[str, ...] = (
    "survival.death",
    "survival.emergency_tp",
    "survival.hp",
    "survival.mp_safe",
    "survival.return_vitals",
    "party.hold_ground",  # leader waits while a member is off their seat
    "shop.trip",  # handoff → SHOPPING (may clear+re-request world nav)
    "spell.support",
    "spell.buffs",
    # Walk / gate approach only. Scroll, NPC teleporter, and gate click stay put.
    "unstick.confined",
    "world_nav.drive",
)

# Sticky PlayerMode.SHOPPING — buy/sell trip (scroll / walk / STOP / RUN)
SHOPPING: tuple[str, ...] = (
    "survival.death",
    "survival.emergency_tp",
    "survival.hp",
    "survival.mp_safe",
    "survival.return_vitals",
    "shop.drive",
)

FARMING_ISLAND: tuple[str, ...] = (
    "survival.death",
    "survival.emergency_tp",
    "survival.hp",
    "survival.mp_safe",
    "survival.return_vitals",
    "party.hold_ground",  # leader waits while a member is off their seat
    "survival.return_idle",
    "shop.before_world_nav",
    "nav.world",
    "spell.support",
    "spell.buffs",
    "unstick.confined",
    "farm.newbie",
    "farm.post_respawn_spellbook",
    "farm.upkeep",
    "farm.post_shop_return",
    "nav.hunt_map",
    "party.turret_leash",  # party leader turret only
    "farm.engage",
    "party.turret_idle",  # party leader turret only
    "farm.enter",
    "farm.search",
)

FARMING_DUNGEON: tuple[str, ...] = (
    "survival.death",
    "survival.hp",
    "survival.mp_safe",
    "survival.return_vitals",
    "party.hold_ground",  # leader waits while a member is off their seat
    "survival.return_idle",
    "shop.before_world_nav",
    "nav.world",
    "spell.support",
    "spell.buffs",
    "farm.post_respawn_spellbook",
    "farm.post_shop_return",
    "nav.hunt_map",
    "dungeon.off_floor",
    "dungeon.blocked",
    "party.turret_leash",  # party leader turret only
    "farm.engage",
    "party.turret_idle",  # party leader turret only
    "dungeon.patrol",
    "dungeon.idle_nudge",
)

TRAVELING: tuple[str, ...] = (
    "survival.death",
    "survival.emergency_tp",
    "survival.hp",
    "survival.mp_safe",
    "survival.return_vitals",
    "party.hold_ground",  # leader waits while a member is off their seat
    # Schedule row minutes up → next row (do not wait for patrol/combat to end).
    # SHOPPING column omits this so an in-flight buy/sell is not aborted.
    "routine.duration",
    "spell.support",
    "spell.buffs",
    "unstick.confined",
    "shop.trip",  # handoff → SHOPPING (sell before break when next row needs bag clear)
    "travel.training_done",
    "nav.hunt_map",  # enter/patrol only — handler no-ops otherwise
    "travel.entered_farm",  # inside the rect: stop, do not walk on to center
    "farm.engage",  # enter/patrol only
    "travel.push_deeper_farm",
    "travel.arrive",
    "travel.hop",
    "travel.hop_fail",
)

RETREATING: tuple[str, ...] = (
    "survival.death",
    "retreat.mother_tree",
    "retreat.exit",
    "retreat.scroll",
    "retreat.teleport",
    "retreat.escalate_safe",
    "retreat.post_land_tree",
    "spell.support",
    "survival.inplace_hp",
    "retreat.loot_if_clear",
    "retreat.walk_safe",
    "retreat.idle_emergency",
    "retreat.wait",
)

__all__ = [
    "GLOBAL",
    "WORLD_NAV",
    "SHOPPING",
    "FARMING_ISLAND",
    "FARMING_DUNGEON",
    "TRAVELING",
    "RETREATING",
]
