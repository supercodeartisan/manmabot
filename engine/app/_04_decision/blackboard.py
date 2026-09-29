"""Decision-time memory shared by every behavior node."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app._03_world import ActionType, Position
from app._03_world.battle_area import player_screen_position
from app._03_world.world_coords import WorldOrigin
from app._04_decision.behaviors.navigation import (
    BEARING_PERSIST_MIN,
    LEG_HISTORY_SIZE,
    MovementLeg,
    MovementPlanner,
)
from app._04_decision.player_mode import PlayerMode
from app._04_decision.types import ActionIntent


def _default_virtual_position() -> Position:
    pos = player_screen_position()
    return Position(x=pos.x, y=pos.y)


@dataclass
class Blackboard:
    """Temporary decision memory that persists between ``decide`` ticks.

    Holds the current goal/targets and session timers. Values are only
    cleared deliberately (target died, disappeared or unreachable), never
    reset on every tick, so combat keeps engaging the same monster until it
    is no longer valid.
    """

    # -- current objectives -------------------------------------------------
    current_target_id: Optional[int] = None
    # Survives TrackIds / heap-pointer churn: rebind by species + last cell.
    current_target_species: Optional[str] = None
    current_target_world: Optional[tuple[int, int]] = None
    current_item_id: Optional[int] = None
    current_goal: Optional[str] = None

    # -- farming session ----------------------------------------------------
    # Accumulated seconds spent inside the active farm rect (not wall-clock).
    farm_elapsed_seconds: float = 0.0
    farm_time_last_sample: float = 0.0
    farm_time_inside: bool = False
    farm_area_index: int = 0
    # Hunt/Attack area watches (empty / Adena yield). 0 / -1 = not armed.
    farm_empty_since: float = 0.0
    farm_watch_started: float = 0.0
    farm_adena_start: int = -1
    # Target-select delay: wait before engaging a newly chosen monster.
    target_select_until: float = 0.0
    target_select_id: Optional[int] = None
    # Ordered farm indices: schedule list order, then cycle.
    farm_tour: list[int] = field(default_factory=list)
    farm_tour_pos: int = 0
    # Dungeon patrol: index into configured midpoints.
    patrol_index: int = 0
    home_position: Optional[Position] = None

    # -- sticky high-level mode ---------------------------------------------
    player_mode: PlayerMode = PlayerMode.FARMING
    resume_mode: Optional[PlayerMode] = None
    # Why the current nav_goal was set (home / next_farm / enter_farm / safe).
    travel_purpose: Optional[str] = None
    # One-shot box-1 F10 teleport at the start of a retreat.
    retreat_teleport_pending: bool = False
    # After a danger teleport, keep healing until HP ≥ 50% or MP < 20%.
    heal_after_teleport: bool = False
    # Buff name → last successful cast time (``time.time()``). Missing = not yet cast.
    buff_last_cast: dict[str, float] = field(default_factory=dict)
    # Wall-clock when buff cadence started (first due_buff / bot session).
    buff_session_at: float = 0.0
    # Last use time for heal / potion / other slotted skills.
    spell_last_cast: dict[str, float] = field(default_factory=dict)
    # Shared magic cooldown: last buff / heal / teleport / mage-attack cast.
    magic_last_cast: float = 0.0
    # Wall-clock of last travel/search unstick teleport.
    unstick_teleport_at: float = 0.0

    # -- anti-spam / stuck detection ------------------------------------------
    # Wall-clock start of sticky combat (``time.time()``); 0 = not engaged.
    # Last-resort give-up after ``MAX_ENGAGE_SECONDS`` if the target never dies.
    target_engage_started: float = 0.0
    # Monotonic decision-tick counter, incremented once per ``decide()``. The
    # shared frame clock used for cooldowns.
    tick_count: int = 0
    # Targets combat gave up on, mapped to the tick they were abandoned. They
    # are excluded from re-selection until the cooldown elapses.
    given_up_target_ids: dict[int, int] = field(default_factory=dict)
    # Bow cursor was ``arrow_lack`` — go buy arrows at a shop.
    needs_arrows: bool = False
    needs_potion: bool = False
    potion_suppress_until: float = 0.0
    needs_depoison: bool = False
    depoison_suppress_until: float = 0.0
    # Consecutive cursor-verify fails per track (probation before soft give-up).
    cursor_verify_fail_streak: dict[int, int] = field(default_factory=dict)
    # Soft nav hazards (e.g. sleeping 돌골렘 disks). Absolute tiles + TTL.
    hazard_zones: list = field(default_factory=list)
    # Session blacklist (fake targets: no MP drain / never moved). No expiry.
    blacklisted_target_ids: set[int] = field(default_factory=set)
    # Post-attack probes for blacklist rules.
    attack_probe_target_id: Optional[int] = None
    attack_probe_wcs: Optional[tuple[int, int]] = None
    attack_probe_started: float = 0.0
    attack_probe_mp_before: Optional[int] = None
    attack_probe_awaiting_mp: bool = False
    attack_probe_mp_unchanged_ticks: int = 0
    # Consecutive search ticks in which the destination was kept unchanged
    # (emitted ``mid_act=True``). This is the age of the current leg: reaching
    # LEG_TICKS means the leg is done and search rolls the next destination.
    search_leg_ticks: int = 0
    # The waypoint the character is currently walking to while searching.
    search_destination: Optional[Position] = None
    # Absolute tile the search hop is trying to reach (memory-near check).
    search_waypoint: Optional[tuple[int, int]] = None
    # True while waiting for memory position to reach ``search_waypoint``.
    search_hop_active: bool = False
    # tick_count of the last search emission; a gap > 1 means search was
    # interrupted (e.g. by combat) and the leg-age counter should restart.
    last_search_tick: int = 0
    # Search stuck detection while waiting for the waypoint.
    search_stuck_tile: Optional[tuple[int, int]] = None
    search_stuck_since_tick: int = 0
    search_stuck_since_time: float = 0.0
    search_unstick_active: bool = False
    # Sticky loot: walk-to-item hop (like search) then PICKUP when near.
    loot_approach_destination: Optional[Position] = None
    loot_approach_waypoint: Optional[tuple[int, int]] = None
    loot_approach_active: bool = False
    loot_stuck_tile: Optional[tuple[int, int]] = None
    loot_stuck_since_tick: int = 0
    loot_stuck_since_time: float = 0.0
    loot_pickup_since_time: float = 0.0
    # track_id → tick of last successful pickup click (skip empty-tile reclicks).
    loot_clicked_ids: dict[int, int] = field(default_factory=dict)
    # Do not walk/fight until this wall-clock (set after a confirmed pickup).
    loot_pickup_until: float = 0.0
    # After a loot click, wait until this track_id leaves memory before walking.
    loot_await_gone_id: Optional[int] = None
    loot_await_gone_since: float = 0.0
    # Coverage memory for the active farm (cell_x, cell_y) -> visit count.
    farm_visit: dict[tuple[int, int], int] = field(default_factory=dict)

    # -- travel (A* guided) --------------------------------------------------
    travel_leg_ticks: int = 0
    travel_destination: Optional[Position] = None
    last_travel_tick: int = 0
    # Wall-clock of last real travel walk click (not mid_act holds).
    travel_click_at: float = 0.0
    # True while waiting for memory position to reach nav_waypoint.
    travel_hop_active: bool = False
    travel_stuck_tile: Optional[tuple[int, int]] = None
    travel_stuck_since_tick: int = 0
    travel_stuck_since_time: float = 0.0
    travel_unstick_active: bool = False
    # Nearby ±3 walk already issued for this freeze (5s); teleport still waits 10s/100.
    travel_soft_unstick_done: bool = False

    # -- movement planning ---------------------------------------------------
    # Dead-reckoned world-relative position of the character. The player sits
    # at a fixed battle-area anchor so movement is inferred from the legs we
    # roll, not from perception output. Re-anchored to the player's real
    # position whenever a fresh wandering session starts.
    virtual_position: Position = field(default_factory=_default_virtual_position)
    # Current trend bearing (degrees) and how many legs it has been held.
    movement_bearing_deg: float = 0.0
    bearing_legs: int = 0
    bearing_legs_target: int = BEARING_PERSIST_MIN
    # Walkability gate. The stub accepts everything until the minimap module
    # lands; real implementation rejects unreachable click points.
    is_walkable: Callable[[Position], bool] = field(default=lambda _p: True)
    # Recent destination rolls, oldest first. Also used for the per-leg
    # console log in DecisionManager.
    leg_history: deque[MovementLeg] = field(
        default_factory=lambda: deque(maxlen=LEG_HISTORY_SIZE)
    )
    # Rolls the next leg. Survives ``reset()``: it only owns RNG state.
    movement_planner: MovementPlanner = field(default_factory=MovementPlanner)

    # -- absolute navigation (terrain pathfinding) ---------------------------
    # Absolute tile of the player when relative WCS is (0, 0).
    world_origin: WorldOrigin = field(default_factory=WorldOrigin)
    # Absolute goal tile for long-range travel (None = no guided nav).
    nav_goal: Optional[tuple[int, int]] = None
    # Last computed absolute path (including current tile at index 0).
    nav_path: list[tuple[int, int]] = field(default_factory=list)
    # Absolute waypoint last chosen for a battle-screen click.
    nav_waypoint: Optional[tuple[int, int]] = None

    # -- emitted decision for this tick --------------------------------------
    intent: Optional[ActionIntent] = None

    # -- generic scratch space for future behaviors --------------------------
    scratch: dict[str, Any] = field(default_factory=dict)

    def emit(self, action: ActionType, **kwargs: Any) -> None:
        """Record the action intent chosen by the current behavior."""
        self.intent = ActionIntent(action=action, **kwargs)

    def reset(self) -> None:
        """Clear all decision memory (new session)."""
        self.current_target_id = None
        self.current_target_species = None
        self.current_target_world = None
        self.current_item_id = None
        self.current_goal = None
        self.farm_elapsed_seconds = 0.0
        self.farm_time_last_sample = 0.0
        self.farm_time_inside = False
        self.farm_area_index = 0
        self.farm_empty_since = 0.0
        self.farm_watch_started = 0.0
        self.farm_adena_start = -1
        self.target_select_until = 0.0
        self.target_select_id = None
        self.farm_tour.clear()
        self.farm_tour_pos = 0
        self.patrol_index = 0
        self.intent = None
        self.player_mode = PlayerMode.FARMING
        self.resume_mode = None
        self.travel_purpose = None
        self.retreat_teleport_pending = False
        self.heal_after_teleport = False
        # Buff reuse survives pause/resume and soft reset (wall-clock).
        from app._04_decision.spells import persist_buff_timers, restore_buff_timers

        persist_buff_timers(self)
        # Keep existing timestamps; refill from process persist if empty.
        restore_buff_timers(self)
        self.spell_last_cast.clear()
        self.magic_last_cast = 0.0
        self.unstick_teleport_at = 0.0
        self.target_engage_started = 0.0
        self.tick_count = 0
        self.given_up_target_ids.clear()
        self.needs_arrows = False
        self.needs_potion = False
        self.potion_suppress_until = 0.0
        self.needs_depoison = False
        self.depoison_suppress_until = 0.0
        self.cursor_verify_fail_streak.clear()
        self.hazard_zones.clear()
        self.blacklisted_target_ids.clear()
        self.attack_probe_target_id = None
        self.attack_probe_wcs = None
        self.attack_probe_started = 0.0
        self.attack_probe_mp_before = None
        self.attack_probe_awaiting_mp = False
        self.attack_probe_mp_unchanged_ticks = 0
        self.search_leg_ticks = 0
        self.search_destination = None
        self.search_waypoint = None
        self.search_hop_active = False
        self.last_search_tick = 0
        self.search_stuck_tile = None
        self.search_stuck_since_tick = 0
        self.search_stuck_since_time = 0.0
        self.search_unstick_active = False
        self.loot_approach_destination = None
        self.loot_approach_waypoint = None
        self.loot_approach_active = False
        self.loot_stuck_tile = None
        self.loot_stuck_since_tick = 0
        self.loot_stuck_since_time = 0.0
        self.loot_pickup_since_time = 0.0
        self.loot_clicked_ids.clear()
        self.loot_pickup_until = 0.0
        self.loot_await_gone_id = None
        self.loot_await_gone_since = 0.0
        self.farm_visit.clear()
        self.travel_leg_ticks = 0
        self.travel_destination = None
        self.last_travel_tick = 0
        self.travel_click_at = 0.0
        self.travel_hop_active = False
        self.travel_stuck_tile = None
        self.travel_stuck_since_tick = 0
        self.travel_stuck_since_time = 0.0
        self.travel_unstick_active = False
        self.travel_soft_unstick_done = False
        self.virtual_position = _default_virtual_position()
        self.movement_bearing_deg = 0.0
        self.bearing_legs = 0
        self.bearing_legs_target = BEARING_PERSIST_MIN
        self.leg_history.clear()
        self.world_origin = WorldOrigin()
        self.nav_goal = None
        self.nav_path.clear()
        self.nav_waypoint = None
        self.scratch.clear()


__all__ = ["Blackboard"]
