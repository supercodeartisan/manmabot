"""Arm / tick / fail-skip world nav from UI routine."""

from __future__ import annotations

from typing import Any, Optional

from app._04_decision.behavior_tree import Status
from app.bot_log import get_logger

from . import planner_api as api
from .routine import RoutineCursor, goal_for_entry
from .session import WorldNavSession, live_pose_from_state

SCRATCH_WORLD_NAV = "world_nav_session"
SCRATCH_ROUTINE = "routine_cursor"
SCRATCH_NEED_WORLD_NAV = "need_world_nav"
SCRATCH_WORLD_NAV_GATE = "world_nav_gate"
SCRATCH_WORLD_NAV_PAUSE = "world_nav_pause_request"
SCRATCH_RUNTIME_CONFIG = "runtime_config"
SCRATCH_ROUTINE_KIND = "routine_kind"  # battle | break
# Nav-show / decision panel: last gate land failure after 2 attempts.
SCRATCH_NAV_GATE_WARN = "nav_gate_warn"


def init_routine_on_blackboard(
    blackboard: Any,
    *,
    routine: list | None,
    fallback_map: str,
    selected_farms: list[str] | None = None,
    farm_stays_s: dict | None = None,
    entries_normalized: bool = False,
) -> RoutineCursor:
    """Install routine cursor.

    Live Start should pass ``entries_normalized=True`` after
    ``settings.farm_schedule.normalize_routine`` and install map overlays via
    ``session.world_nav_inject``.
    """
    if routine:
        if entries_normalized:
            cursor = RoutineCursor.from_entries(list(routine))
        else:
            cursor = RoutineCursor.from_routine(routine)
    else:
        cursor = RoutineCursor.from_profile_fallback(
            map_id=fallback_map,
            selected_farms=selected_farms,
            farm_stays_s=farm_stays_s,
        )
    blackboard.scratch[SCRATCH_ROUTINE] = cursor
    entry = cursor.active()
    if entry is not None:
        blackboard.scratch[SCRATCH_ROUTINE_KIND] = str(entry.get("kind") or "battle")
    get_logger("nav").info(
        "routine init entries=%s index=%s map=%s",
        len(cursor),
        cursor.index,
        None if entry is None else entry.get("map_id"),
    )
    return cursor


def request_world_nav(blackboard: Any, reason: str) -> None:
    """Stash a need flag only (does not change ``PlayerMode``)."""
    blackboard.scratch[SCRATCH_NEED_WORLD_NAV] = str(reason or "request")


def ensure_world_nav_mode(blackboard: Any) -> None:
    """Sticky ``PlayerMode.WORLD_NAV`` while a session/need owns the character."""
    from app._04_decision.mode_control import set_mode
    from app._04_decision.player_mode import PlayerMode

    if blackboard.player_mode is not PlayerMode.WORLD_NAV:
        set_mode(blackboard, PlayerMode.WORLD_NAV)


def begin_world_nav(blackboard: Any, reason: str) -> None:
    """Request arm + enter ``PlayerMode.WORLD_NAV`` (external entry points)."""
    request_world_nav(blackboard, reason)
    ensure_world_nav_mode(blackboard)


def clear_world_nav_run(blackboard: Any) -> None:
    """Drop in-flight world-nav session/gate/need. Keeps routine cursor.

    Call when another owner takes the character (e.g. begin_retreat).
    ``finish_retreat`` may ``begin_world_nav`` again afterward.
    Does not change ``PlayerMode`` (caller sets retreat/farming).
    """
    blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV_GATE, None)
    blackboard.scratch.pop(SCRATCH_NEED_WORLD_NAV, None)


def set_nav_gate_warn(
    blackboard: Any,
    *,
    message: str,
    to_map: int | None = None,
    from_map: int | None = None,
    edge: str = "",
) -> None:
    """Surface a gate failure on the debug Navigation-show tab."""
    import time

    blackboard.scratch[SCRATCH_NAV_GATE_WARN] = {
        "message": str(message or "gate transition failed"),
        "to_map": to_map,
        "from_map": from_map,
        "edge": str(edge or ""),
        "at": time.time(),
    }


def clear_nav_gate_warn(blackboard: Any) -> None:
    blackboard.scratch.pop(SCRATCH_NAV_GATE_WARN, None)


def apply_routine_entry_runtime(
    blackboard: Any,
    entry: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> None:
    """Switch HUNT_MAP / farms / dungeon flag to the active routine row.

    Call only after world-nav **arrival** (or equivalent). Do not call at arm
    time — that would load destination terrain while still walking the source map.

    Pack terrain/origin must already match live mapId (see live_map_pack); this
    re-applies hunt farms and confirms the pack synchronously (no async race).
    """
    from app._04_decision import player_mode as pm
    from app._04_decision.dungeon import set_dungeon_mode_override
    from app._04_decision.live_map_pack import ensure_navigation_for_pack_id

    pack_id = str(entry.get("map_id") or "").strip()
    if not pack_id:
        return
    pm.HUNT_MAP_ID = pack_id
    kind = str(entry.get("kind") or "battle").strip().lower()
    blackboard.scratch[SCRATCH_ROUTINE_KIND] = kind

    from app._04_decision.world_nav.overlays import (
        farm_rects_selected,
        is_dungeon_pack,
        safe_rects_selected,
    )

    dungeon = is_dungeon_pack(blackboard, pack_id)
    set_dungeon_mode_override(dungeon)

    cfg = config or blackboard.scratch.get(SCRATCH_RUNTIME_CONFIG)
    if not isinstance(cfg, dict):
        return
    nav = dict(cfg.get("navigation") or {})
    nav["active_map"] = pack_id
    names = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    rects: list = []
    safe_rects: list = []
    if dungeon or kind == "break":
        nav.pop("farm_areas", None)
        if dungeon:
            nav.pop("farm_areas_file", None)
        if kind == "break" and not dungeon and names:
            safe_rects = safe_rects_selected(blackboard, pack_id, names)
    else:
        if names:
            rects = farm_rects_selected(blackboard, pack_id, names)
        if rects:
            nav["farm_areas"] = rects
            nav.pop("farm_areas_file", None)
    # Drop a previous break row's subset before pack sync reloads areas.
    nav.pop("safe_areas", None)
    cfg["navigation"] = nav
    blackboard.scratch[SCRATCH_RUNTIME_CONFIG] = cfg
    ensure_navigation_for_pack_id(blackboard, cfg, pack_id)
    # configure_navigation_for_map pops inline farms — restore selected rects.
    nav = dict(cfg.get("navigation") or {})
    if rects:
        nav["farm_areas"] = rects
        nav.pop("farm_areas_file", None)
    nav.pop("safe_areas", None)
    try:
        from session.probes import apply_userdata_area_files

        apply_userdata_area_files(
            nav,
            pack_id,
            include_farms=not dungeon and kind != "break" and not rects,
        )
    except Exception as exc:
        get_logger("nav").warning("area overlay skipped: %s", exc)
    if safe_rects:
        nav["safe_areas"] = safe_rects
    cfg["navigation"] = nav
    try:
        from app._04_decision import nav_config as nc

        nc._load_farms_and_home(nav)
    except Exception as exc:
        get_logger("nav").warning("farm rect remount failed: %s", exc)
    # Reset farm tour for new map.
    blackboard.farm_tour.clear()
    blackboard.farm_tour_pos = 0
    blackboard.farm_area_index = 0
    blackboard.patrol_index = 0
    get_logger("nav").info(
        "routine apply map=%s kind=%s dungeon=%s farms=%s safe=%s",
        pack_id,
        kind,
        dungeon,
        len(rects),
        len(safe_rects),
    )


# Trips back onto the row already being timed. They must not restart duration.
_STAY_CLOCK_KEEP_REASONS = frozenset({
    "post_retreat",
    "post_shop",
    "after_shop",
    "hunt_map",
})


def _arrival_resets_stay(reason: str) -> bool:
    return str(reason or "") not in _STAY_CLOCK_KEEP_REASONS


def _drop_world_nav_session(blackboard: Any) -> None:
    """Drop an in-flight plan so a new routine row can arm."""
    blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV_GATE, None)
    blackboard.scratch.pop(SCRATCH_NEED_WORLD_NAV, None)
    try:
        from app._04_decision.behaviors.travel import clear_travel

        clear_travel(blackboard)
    except Exception:
        pass


def _break_row_has_rest_goal(blackboard: Any, entry: dict[str, Any]) -> bool:
    """True when a break row has at least one checked rest area on this pack."""
    if str(entry.get("kind") or "").strip().lower() != "break":
        return False
    names = [str(n) for n in (entry.get("selected_farms") or []) if str(n).strip()]
    if not names:
        return False
    from app._04_decision.world_nav.overlays import safe_rects_selected

    pack_id = str(entry.get("map_id") or "").strip()
    return bool(safe_rects_selected(blackboard, pack_id, names))


def take_next_routine_if_due(blackboard: Any) -> bool:
    """If the active row's minutes are up, leave it and arm the next row.

    Used from farming/world-nav ticks and from ``TRAVELING`` (patrol) so a
    dungeon walk cannot outlive the schedule row. ``SHOPPING`` must not call
    this to interrupt an in-flight buy/sell — after the trip clears, the next
    farming/world-nav tick advances if still overdue.
    """
    cursor = blackboard.scratch.get(SCRATCH_ROUTINE)
    if not isinstance(cursor, RoutineCursor) or len(cursor) < 1:
        return False
    if not cursor.duration_expired():
        return False
    old = cursor.active()
    _drop_world_nav_session(blackboard)
    cursor.advance()
    entry = cursor.active()
    old_map = str((old or {}).get("map_id") or "")
    new_map = str((entry or {}).get("map_id") or "")
    get_logger("nav").info(
        "routine duration → next from=%s to=%s",
        None if old is None else old.get("map_id"),
        None if entry is None else entry.get("map_id"),
    )
    if entry is not None and old_map == new_map:
        apply_routine_entry_runtime(blackboard, entry)
        on_hunt = False
        try:
            from app._04_decision.talking_scroll import player_on_selected_map

            on_hunt = bool(player_on_selected_map(blackboard))
        except Exception:
            on_hunt = False
        # Same map still walks when the new row is a checked rest area.
        walk_to_rest = _break_row_has_rest_goal(blackboard, entry)
        if not on_hunt or walk_to_rest:
            request_world_nav(blackboard, "routine_duration")
            arm_world_nav(blackboard, "routine_duration")
    elif entry is not None:
        request_world_nav(blackboard, "routine_duration")
        arm_world_nav(blackboard, "routine_duration")
    return True


# Back-compat alias for older call sites / tests.
_take_next_routine_if_due = take_next_routine_if_due


def leave_world_nav_mode_if_idle(blackboard: Any) -> None:
    """Return to ``FARMING`` when no session/need remains."""
    from app._04_decision.mode_control import set_mode
    from app._04_decision.player_mode import PlayerMode

    if blackboard.scratch.get(SCRATCH_WORLD_NAV) is not None:
        return
    if blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV):
        return
    if blackboard.player_mode is PlayerMode.WORLD_NAV:
        set_mode(blackboard, PlayerMode.FARMING)


def _on_world_nav_arrived(blackboard: Any, *, reason: str = "") -> None:
    """Mark routine arrival and apply hunt/farm/dungeon runtime for that row."""
    cursor: RoutineCursor | None = blackboard.scratch.get(SCRATCH_ROUTINE)
    if cursor is not None:
        cursor.mark_arrived(reset_clock=_arrival_resets_stay(reason))
        cursor.reset_fail_mask()
        entry = cursor.active()
        if entry is not None:
            apply_routine_entry_runtime(blackboard, entry)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV_GATE, None)
    # Clear stale need so break/farm UI countdown is not stuck on "Moving".
    blackboard.scratch.pop(SCRATCH_NEED_WORLD_NAV, None)
    get_logger("nav").info("world nav arrived reason=%s", reason or "-")


def arm_world_nav(blackboard: Any, reason: str) -> bool:
    """Plan world nav to the active routine goal. Returns False on plan fail."""
    cursor: RoutineCursor | None = blackboard.scratch.get(SCRATCH_ROUTINE)
    if cursor is None or not cursor.entries:
        get_logger("nav").warning("world nav arm skipped: no routine")
        return False
    entry = cursor.active()
    if entry is None:
        return False

    # Pose must come from a later tick if missing — stash need and retry.
    # Caller should pass state when available; here we only plan if scratch has pose.
    state = blackboard.scratch.get("_world_nav_pose_state")
    pose = live_pose_from_state(state) if state is not None else None
    if pose is None:
        request_world_nav(blackboard, reason)
        get_logger("nav").info("world nav arm deferred (no pose) reason=%s", reason)
        return False

    try:
        goal = goal_for_entry(entry, blackboard)
        from app._04_decision.talking_scroll import talking_scroll_available

        session = WorldNavSession()
        from app._04_decision.hunt_area import current_adena

        adena = current_adena(state) if state is not None else None
        ok = session.begin(
            pose,
            goal,
            reason=reason,
            has_talking_scroll=talking_scroll_available(),
            adena=adena,
        )
    except Exception as exc:
        get_logger("nav").warning("world nav arm fail: %s", exc)
        return _fail_skip(blackboard, reason=reason, error=str(exc))

    if not ok:
        # Already at destination (empty plan) — treat as arrival, not fail_skip.
        if _pose_meets_entry(pose, entry, blackboard):
            blackboard.scratch.pop(SCRATCH_NEED_WORLD_NAV, None)
            cursor.mark_arrived(reset_clock=_arrival_resets_stay(reason))
            cursor.reset_fail_mask()
            apply_routine_entry_runtime(blackboard, entry)
            get_logger("nav").info(
                "world nav already at goal map=%s reason=%s",
                entry.get("map_id"),
                reason,
            )
            from app._04_decision.mode_control import set_mode
            from app._04_decision.player_mode import PlayerMode

            if blackboard.player_mode is PlayerMode.WORLD_NAV:
                set_mode(blackboard, PlayerMode.FARMING)
            return True
        return _fail_skip(blackboard, reason=reason, error=session.error or "plan fail")
    blackboard.scratch[SCRATCH_WORLD_NAV] = session
    blackboard.scratch.pop(SCRATCH_NEED_WORLD_NAV, None)
    ensure_world_nav_mode(blackboard)
    # Destination HUNT_MAP / terrain apply waits until arrival (_on_world_nav_arrived).
    get_logger("nav").info(
        "world nav armed reason=%s map=%s steps=%s",
        reason,
        entry.get("map_id"),
        len(session.plan.steps) if session.plan else 0,
    )
    return True


def _pose_meets_entry(
    pose: Any, entry: dict[str, Any], blackboard: Any = None
) -> bool:
    try:
        goal = goal_for_entry(entry, blackboard)
        return bool(goal.is_satisfied(pose))
    except Exception:
        return False


def _fail_skip(blackboard: Any, *, reason: str, error: str) -> bool:
    """Skip the current routine row and arm the next; never stop the bot.

    A fail only skips this visit. When every row has failed once this round,
    clear the mask and continue — next wrap retries those destinations.
    """
    tokens = api.state_tokens()
    cursor: RoutineCursor | None = blackboard.scratch.get(SCRATCH_ROUTINE)
    if cursor is None or not cursor.entries:
        # No routine to advance — keep asking for nav; do not Stop.
        api.emit_state(tokens.FAIL_SKIP_NEXT, reason=reason, error=error)
        blackboard.scratch.pop(SCRATCH_WORLD_NAV_PAUSE, None)
        request_world_nav(blackboard, f"fail_retry:{reason}")
        blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
        get_logger("nav").warning(
            "world nav fail (no routine): %s — will retry", error
        )
        return False
    from_i = cursor.index
    cursor.mark_fail()
    wrapped = cursor.full_cycle_failed()
    cursor.advance()
    to_i = cursor.index
    api.emit_state(
        tokens.FAIL_SKIP_NEXT,
        reason=reason,
        error=error,
        from_i=from_i,
        to_i=to_i,
    )
    if wrapped:
        # New round: every entry is eligible again (skip was one-shot).
        cursor.reset_fail_mask()
        api.emit_state(
            tokens.PAUSE_CYCLE,
            reason=reason,
            error="routine round failed; retrying next round (no stop)",
        )
        get_logger("nav").warning(
            "world nav: all routine rows failed this round — "
            "continuing to next round (no stop) error=%s",
            error,
        )
    # Do not apply_routine_entry_runtime here — wait until nav arrives at the new row.
    request_world_nav(blackboard, f"fail_skip:{reason}")
    blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV_PAUSE, None)
    return False

def tick_world_nav(state: Any, blackboard: Any) -> Status | None:
    """Run active session, or arm if requested. Blocks farming while active."""
    blackboard.scratch["_world_nav_pose_state"] = state

    session: WorldNavSession | None = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)

    if session is not None and session.phase == "fail":
        err = session.error or "nav fail"
        blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
        _fail_skip(blackboard, reason=session.reason or "run", error=err)
        return Status.SUCCESS

    if session is not None and session.phase == "done":
        _on_world_nav_arrived(blackboard, reason=session.reason or "")
        # Arrival can leave the row already over its minutes (return trip).
        _take_next_routine_if_due(blackboard)
        leave_world_nav_mode_if_idle(blackboard)
        return None

    # Open walk / scroll / gate still yields when the row's minutes are up.
    if session is not None and _take_next_routine_if_due(blackboard):
        session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
        need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)

    if session is None and _take_next_routine_if_due(blackboard):
        session = blackboard.scratch.get(SCRATCH_WORLD_NAV)
        need = blackboard.scratch.get(SCRATCH_NEED_WORLD_NAV)

    if session is None and need:
        arm_world_nav(blackboard, str(need))
        session = blackboard.scratch.get(SCRATCH_WORLD_NAV)

    if session is None:
        leave_world_nav_mode_if_idle(blackboard)
        return None

    ensure_world_nav_mode(blackboard)
    status = session.tick(state, blackboard)
    if session.phase == "fail":
        err = session.error or "nav fail"
        blackboard.scratch.pop(SCRATCH_WORLD_NAV, None)
        _fail_skip(blackboard, reason=session.reason or "run", error=err)
        leave_world_nav_mode_if_idle(blackboard)
        return Status.SUCCESS
    if session.phase == "done":
        _on_world_nav_arrived(blackboard, reason=session.reason or "")
        _take_next_routine_if_due(blackboard)
        leave_world_nav_mode_if_idle(blackboard)
        return None
    return status


def apply_npc_teleporter_result(blackboard: Any, *, behavior_id: str = "") -> bool:
    """SHOP_RUN teleporter finished during world-nav → start land-xy settle."""
    session: WorldNavSession | None = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    if session is None:
        return False
    return bool(session.note_npc_teleporter_ok(behavior_id))


def apply_gate_result(
    blackboard: Any,
    *,
    ok: bool,
    error: str = "",
    live_map_id: int | None = None,
    live_x: int | None = None,
    live_y: int | None = None,
) -> None:
    """Apply ``ActionExecutor`` GATE outcome to the world-nav session."""
    session: WorldNavSession | None = blackboard.scratch.get(SCRATCH_WORLD_NAV)
    gate = blackboard.scratch.get(SCRATCH_WORLD_NAV_GATE)
    live_pose = None
    if live_map_id is not None and live_x is not None and live_y is not None:
        live_pose = api.Pose(int(live_map_id), int(live_x), int(live_y))

    if session is not None and getattr(session, "phase", None) == "gate_click":
        session.note_gate_result(bool(ok), live_pose, error=error or "")
        if ok:
            from app._04_decision.live_map_pack import (
                ensure_navigation_for_live_map_id,
            )

            cfg = blackboard.scratch.get(SCRATCH_RUNTIME_CONFIG)
            mid = int(live_map_id) if live_map_id is not None else None
            if mid is None and isinstance(gate, dict):
                try:
                    mid = int(gate.get("to_map"))
                except (TypeError, ValueError):
                    mid = None
            if isinstance(cfg, dict) and mid is not None:
                ensure_navigation_for_live_map_id(blackboard, cfg, mid)
        elif isinstance(gate, dict):
            set_nav_gate_warn(
                blackboard,
                message=error or "gate transition failed",
                to_map=int(gate.get("to_map") or -1),
                from_map=int(gate.get("from_map") or -1),
                edge=str(gate.get("edge") or ""),
            )
        else:
            set_nav_gate_warn(blackboard, message=error or "gate transition failed")
    if ok:
        clear_nav_gate_warn(blackboard)
    blackboard.scratch.pop(SCRATCH_WORLD_NAV_GATE, None)

