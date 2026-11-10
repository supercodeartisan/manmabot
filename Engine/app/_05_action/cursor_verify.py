"""Cursor appearance gate: aim → capture → match → allow click."""
from __future__ import annotations

import math
import random
import time
from typing import TYPE_CHECKING, Iterable, Optional

from app._05_action.cursor_capture import capture_cursor_bgra, get_cursor_handle
from app._05_action.cursor_catalog import (
    ATTACK_OK_LABELS,
    DIALOG_OK_CATEGORIES,
    LOOT_OK_CATEGORIES,
    LOOT_OK_LABELS,
    MAGE_CAST_OK_LABELS,
    CursorCategory,
)
from app._05_action.cursor_match import CursorMatch, get_cursor_matcher

if TYPE_CHECKING:
    from app._05_action.controller import ActionExecutor

# Populated by configure_action.
CURSOR_VERIFY_ENABLED = True
CURSOR_SETTLE_S = 0.0
# After a snap during the attack pixel-ring hunt.
CURSOR_SEARCH_SETTLE_S = 0.02
# Hover the pile this long before the pickup click so we do not walk a neighbor.
LOOT_AIM_SETTLE_S = 0.08
CURSOR_CAPTURE_SIZE = 64

# After a kill the mouse is still on the corpse; the client keeps the attack
# cursor until it leaves that hover. Snap ~30px away, then onto the item / F4.
LOOT_CURSOR_NUDGE_PX = 30.0
# Treat the cursor as "already on the pile" within this radius of the item.
LOOT_CURSOR_NEAR_PX = 48.0
# Brief pause after each clear snap so the OS/game cursor leaves ATTACK.
LOOT_CURSOR_CLEAR_SETTLE_S = 0.03
# Single short nudge off leftover attack hover (corpse/empty arrow).
LOOT_CURSOR_CLEAR_RADII_PX: tuple[float, ...] = (30.0,)
# Body UV + tight pixel ring (cardinal-first). No memory-tile jump.
ATTACK_PIXEL_RADII_PX = (10.0,)
ATTACK_PIXEL_RING_N = 4
# Max aim probes per attack tick (full ring is walked across ticks).
ATTACK_AIM_PROBES_PER_TICK = 2
# Mage cast cross, in screen tiles from the body point. The inner step
# sits on the sprite; the outer step falls past a normal cast-circle rim.
# Both steps are probed in one cast so the click can be the middle of the
# pixels that read ``spell``.
MAGE_SPELL_CROSS_TILES = (0.40, 1.10)
_MAGE_CROSS_PROBE_LABELS = ("spell", "spell_disable", "spell_out_range", "dialog")


def classify_cursor(
    *,
    capture_size: int | None = None,
) -> CursorMatch | None:
    """Capture the live Win32 cursor and match against ``cursors/``."""
    size = CURSOR_CAPTURE_SIZE if capture_size is None else int(capture_size)
    bgra = capture_cursor_bgra(size)
    handle = get_cursor_handle()
    return get_cursor_matcher().match(bgra, handle=handle)


def is_cursor_paralyzed() -> bool:
    """True when the OS cursor matches ``paralyzed`` (poison / no input).

    Used at the start of each bot tick: capture+vision still run, but no
    mouse/keyboard actions are issued while this is true.
    """
    if not CURSOR_VERIFY_ENABLED:
        return False
    matcher = get_cursor_matcher()
    if not matcher.loaded:
        return False
    match = classify_cursor()
    if match is None:
        return False
    return (
        match.category is CursorCategory.PARALYZED
        or match.label == "paralyzed"
    )


def verify_cursor(
    *,
    categories: Iterable[CursorCategory] | None = None,
    labels: Iterable[str] | None = None,
) -> tuple[bool, CursorMatch | None]:
    """Capture + match; True when score and allow-lists pass."""
    if not CURSOR_VERIFY_ENABLED:
        return True, None
    matcher = get_cursor_matcher()
    if not matcher.loaded:
        # No templates → fail closed when verify is enabled.
        return False, None
    bgra = capture_cursor_bgra(CURSOR_CAPTURE_SIZE)
    handle = get_cursor_handle()
    return matcher.match_allows(
        bgra, categories=categories, labels=labels, handle=handle
    )


def aim_and_verify(
    executor: "ActionExecutor",
    x: float,
    y: float,
    *,
    categories: Iterable[CursorCategory] | None = None,
    labels: Iterable[str] | None = None,
    snap: bool = False,
) -> bool:
    """Move to ``(x,y)``, classify cursor; True if click is allowed.

    On reject sets ``executor.last_cursor_reject_reason`` and returns False
    (caller should skip the click; decision may count fails toward soft give-up).
    When verify is disabled, always returns True without moving (caller should
    use ``move_and_click`` as before).
    """
    executor.last_cursor_match = None
    executor.last_cursor_reject_reason = None
    if not CURSOR_VERIFY_ENABLED:
        return True

    executor.mouse.move(x, y, snap=snap)

    ok, match = verify_cursor(categories=categories, labels=labels)
    executor.last_cursor_match = match
    if (
        ok
        and match is not None
        and (
            match.label == "dialog"
            or match.category is CursorCategory.DIALOG
        )
        and not _dialog_click_allowed(categories=categories, labels=labels)
    ):
        ok = False
    if ok:
        return True

    if match is None:
        reason = "cursor unmatched / capture failed"
        thr = float(get_cursor_matcher().min_score)
        reason = f"{reason} need>={thr:.2f}"
    else:
        thr = float(get_cursor_matcher().min_score)
        reason = (
            f"cursor={match.label}/{match.category.value} "
            f"score={match.score:.3f} need>={thr:.2f} not allowed"
        )
    executor.last_cursor_reject_reason = reason
    return False


def verified_click(
    executor: "ActionExecutor",
    x: float,
    y: float,
    *,
    categories: Iterable[CursorCategory] | None = None,
    labels: Iterable[str] | None = None,
    snap: bool = False,
    until_walk: bool = False,
) -> bool:
    """Aim+verify then click; if verify disabled, ``move_and_click``.

    ``until_walk`` repeats a ground hop until the body stands or walks.
    Attack, dialog, and cast clicks leave it false. When verify is on,
    each until_walk re-click re-checks the same allow-list so a mid-loop
    attack hover cannot fire.
    """
    if not CURSOR_VERIFY_ENABLED:
        executor.mouse.move_and_click(x, y, snap=snap, until_walk=until_walk)
        return True
    if not aim_and_verify(
        executor, x, y, categories=categories, labels=labels, snap=snap
    ):
        return False

    cursor_ok = None
    if until_walk:

        def cursor_ok() -> bool:
            ok, match = verify_cursor(categories=categories, labels=labels)
            executor.last_cursor_match = match
            if (
                ok
                and match is not None
                and (
                    match.label == "dialog"
                    or match.category is CursorCategory.DIALOG
                )
                and not _dialog_click_allowed(
                    categories=categories, labels=labels
                )
            ):
                ok = False
            if ok:
                executor.last_cursor_reject_reason = None
                return True
            from app._05_action.cursor_match import get_cursor_matcher

            thr = float(get_cursor_matcher().min_score)
            executor.last_cursor_reject_reason = (
                f"{_format_cursor_score_reason(match, thr=thr)} not allowed"
            )
            return False

    # Already at (x, y); do not bezier a second time.
    executor.mouse.click(
        x, y, snap=True, until_walk=until_walk, cursor_ok=cursor_ok
    )
    if until_walk and int(getattr(executor.mouse, "last_ground_clicks", 1) or 0) <= 0:
        return False
    return True


def verify_attack_aim(executor: "ActionExecutor", x: float, y: float) -> bool:
    """Melee/bow/fist: require an attack cursor that can actually hit."""
    return aim_and_verify(
        executor, x, y, labels=ATTACK_OK_LABELS
    )


def verify_mage_cast_aim(executor: "ActionExecutor", x: float, y: float) -> bool:
    """Mage: require fine label ``spell`` (not disable / out_range)."""
    return aim_and_verify(
        executor, x, y, labels=MAGE_CAST_OK_LABELS
    )


PARTY_LIST_AIM_WAIT_S = 1.0
PARTY_LIST_AIM_POLL_S = 0.05


def wait_party_spell_aim(
    executor: "ActionExecutor" | None = None,
    *,
    reason: str = "",
    wait_s: float | None = None,
    poll_s: float | None = None,
) -> bool:
    """True once the spell cursor is up. False when the wait elapses.

    A party-list cast clicks only after this. A click before the circle
    selects the row and leaves the cursor for the next ground hop.
    """
    budget = PARTY_LIST_AIM_WAIT_S if wait_s is None else float(wait_s)
    step = PARTY_LIST_AIM_POLL_S if poll_s is None else float(poll_s)
    deadline = time.perf_counter() + max(0.0, budget)
    while True:
        if cursor_is_spell_aim(executor):
            return True
        now = time.perf_counter()
        if now >= deadline:
            from app.bot_log import get_logger

            get_logger("action").info(
                "party list aim missed reason=%s",
                str(reason or "party").strip() or "party",
            )
            return False
        time.sleep(min(max(0.0, step), max(0.0, deadline - now)))


def cursor_is_spell_aim(executor: "ActionExecutor" | None = None) -> bool:
    """True when the live cursor is still in cast-target (spell) mode.

    After ``mage_attack`` / buff / heal the client keeps a spell circle until
    the cast lands or Esc cancels. Travel needs NORMAL, so leftover aim must
    be detected without moving the mouse.
    """
    if not CURSOR_VERIFY_ENABLED:
        return False
    matcher = get_cursor_matcher()
    if not matcher.loaded:
        return False
    match = classify_cursor()
    if match is None:
        return False
    if executor is not None:
        executor.last_cursor_match = match
    return (
        match.category is CursorCategory.SPELL
        or str(match.label or "").startswith("spell")
    )


def _right_click_here(executor: "ActionExecutor") -> None:
    """Right-click the current pixel. Cast aim cancels; it is not an attack."""
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return
    pos = getattr(mouse, "_last_pos", None)
    if not isinstance(pos, tuple) or len(pos) < 2:
        return
    try:
        mouse.click(float(pos[0]), float(pos[1]), button="right", snap=True)
    except Exception:
        return


def cancel_spell_aim(
    executor: "ActionExecutor",
    *,
    reason: str = "",
) -> bool:
    """Leave cast-target mode. Esc first; a right-click if the circle remains.

    Returns whether aim looked active. The right-click stays on the current
    pixel so it does not become an attack click.
    """
    active = cursor_is_spell_aim(executor)
    if not active:
        return False
    try:
        executor.keyboard.press("esc")
    except Exception:
        return active
    settle = float(CURSOR_SEARCH_SETTLE_S or 0.0)
    if settle > 0:
        time.sleep(settle)
    if cursor_is_spell_aim(executor):
        _right_click_here(executor)
        if settle > 0:
            time.sleep(settle)
    try:
        from app.bot_log import get_logger

        get_logger("action").info(
            "spell aim cancel reason=%s",
            str(reason or "spell").strip() or "spell",
        )
    except Exception:
        pass
    return True


def verify_loot_aim(executor: "ActionExecutor", x: float, y: float) -> bool:
    """Loot: require NORMAL cursor (not dialog / door / attack)."""
    return aim_and_verify(
        executor, x, y, categories=LOOT_OK_CATEGORIES
    )


def attack_click(executor: "ActionExecutor", x: float, y: float) -> bool:
    return verified_click(
        executor, x, y, labels=ATTACK_OK_LABELS, snap=True
    )


def _arrow_lack(executor: "ActionExecutor") -> bool:
    match = getattr(executor, "last_cursor_match", None)
    return match is not None and getattr(match, "label", "") == "arrow_lack"


def _dedupe_screen_points(
    points: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    seen: set[tuple[int, int]] = set()
    out: list[tuple[float, float]] = []
    for x, y in points:
        key = (int(round(float(x))), int(round(float(y))))
        if key in seen:
            continue
        seen.add(key)
        out.append((float(x), float(y)))
    return out


def _probe_labels(
    executor: "ActionExecutor",
    x: float,
    y: float,
    labels: Iterable[str],
) -> CursorMatch | None:
    """Snap-aim and score ``labels`` (including below min_score). No click."""
    executor.last_cursor_match = None
    executor.last_cursor_reject_reason = None
    if not CURSOR_VERIFY_ENABLED:
        return CursorMatch(label=next(iter(labels), "ok"), category=CursorCategory.UNKNOWN, score=1.0)
    executor.mouse.move(x, y, snap=True)
    if CURSOR_SEARCH_SETTLE_S > 0:
        time.sleep(CURSOR_SEARCH_SETTLE_S)
    matcher = get_cursor_matcher()
    if not matcher.loaded:
        return None
    bgra = capture_cursor_bgra(CURSOR_CAPTURE_SIZE)
    handle = get_cursor_handle()
    # Floor 0 so FAIL UI can show the actual confidence even when below thr.
    match = matcher.match_labels(bgra, labels, handle=handle, min_score=0.0)
    executor.last_cursor_match = match
    return match


def _dialog_click_allowed(
    *,
    categories: Iterable[CursorCategory] | None = None,
    labels: Iterable[str] | None = None,
) -> bool:
    """Shop NPC clicks may use dialog.png. Hunt / walk / loot may not."""
    if labels and "dialog" in {str(label).strip().lower() for label in labels}:
        return True
    if categories and CursorCategory.DIALOG in set(categories):
        return True
    return False


def _format_cursor_score_reason(match: CursorMatch | None, *, thr: float) -> str:
    """Human-readable reject reason with match confidence vs threshold."""
    if match is None:
        return f"cursor unmatched / capture failed need>={thr:.2f}"
    label = str(getattr(match, "label", "") or "?")
    category = getattr(match, "category", None)
    cat = getattr(category, "value", category)
    cat_s = str(cat or "?")
    try:
        score_s = f"{float(getattr(match, 'score', 0.0)):.3f}"
    except (TypeError, ValueError):
        score_s = str(getattr(match, "score", "?"))
    return f"cursor={label}/{cat_s} score={score_s} need>={thr:.2f}"


def _click_when_found(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
    *,
    labels: Iterable[str],
    stop_labels: Iterable[str] = (),
) -> bool:
    """Hover the ring quickly; click once when an allowed cursor appears."""
    wanted = {str(label).strip().lower() for label in labels}
    stop = {str(label).strip().lower() for label in stop_labels}
    if "dialog" not in wanted:
        stop.add("dialog")
    probe = wanted | stop
    last_handle = 0
    thr = float(get_cursor_matcher().min_score)
    last_match: CursorMatch | None = None
    for x, y in _dedupe_screen_points(points):
        if not CURSOR_VERIFY_ENABLED:
            executor.mouse.move_and_click(x, y, snap=True)
            executor._last_aim_click_xy = (float(x), float(y))
            return True
        match = _probe_labels(executor, x, y, probe)
        if match is not None:
            last_match = match
        if match is None:
            last_handle = get_cursor_handle()
            continue
        if float(match.score) < thr:
            executor.last_cursor_reject_reason = _format_cursor_score_reason(
                match, thr=thr
            )
            continue
        if match.label in stop:
            executor.last_cursor_reject_reason = (
                f"{_format_cursor_score_reason(match, thr=thr)} blocked"
            )
            # dialog.png: skip this point only. arrow_lack still aborts
            # so the shop path can run.
            if match.label == "arrow_lack":
                return False
            continue
        if match.label in wanted:
            executor.mouse.click(x, y, snap=True)
            executor._last_aim_click_xy = (float(x), float(y))
            return True
        if match.handle and match.handle == last_handle:
            continue
        last_handle = int(match.handle or 0)
    if last_match is not None:
        executor.last_cursor_match = last_match
        executor.last_cursor_reject_reason = (
            f"{_format_cursor_score_reason(last_match, thr=thr)} not allowed"
        )
    elif not executor.last_cursor_reject_reason:
        executor.last_cursor_reject_reason = _format_cursor_score_reason(
            None, thr=thr
        )
    return False


def attack_pixel_offsets(
    cx: float,
    cy: float,
    *,
    radii: Iterable[float] | None = None,
    n: int | None = None,
) -> list[tuple[float, float]]:
    """Cardinal-first rings around ``(cx, cy)``. Up is first (sprite body)."""
    rings = ATTACK_PIXEL_RADII_PX if radii is None else tuple(radii)
    count = ATTACK_PIXEL_RING_N if n is None else max(1, int(n))
    out: list[tuple[float, float]] = []
    for radius in rings:
        r = float(radius)
        if r <= 0:
            continue
        for i in range(count):
            ang = -math.pi / 2 + (2 * math.pi * i) / count
            out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def object_attack_screen_points(
    executor: "ActionExecutor",
    obj: object,
    bounds,
) -> list[tuple[float, float]]:
    """Memory ``iscr`` shifted up the screen, then that point's ring.

    Up is ``ATTACK_AIM_SCREEN_UP_TILES`` (0.2). Radius is
    ``ATTACK_CURSOR_SEARCH_TILES`` (default 0.1 tile). The ring is centered
    on the lifted point. Walked across ticks via ``attack_click_search``.
    """
    from app._03_world.space.world_coords import (
        content_to_world,
        content_to_world_continuous,
    )
    from app._04_decision import player_mode as pm
    from app._05_action.travel_click import _fractional_content_ring

    lifted = _attack_body_content(obj)
    points: list[tuple[float, float]] = [
        executor._screen_point(lifted.x, lifted.y, bounds)
    ]
    radius = float(pm.ATTACK_CURSOR_SEARCH_TILES)
    if radius > 1e-6:
        cx: float | None = None
        cy: float | None = None
        try:
            center = content_to_world_continuous(lifted.x, lifted.y)
            cx, cy = float(center.x), float(center.y)
        except ValueError:
            rx = getattr(obj, "world_rx", None)
            ry = getattr(obj, "world_ry", None)
            if rx is not None and ry is not None:
                cx, cy = float(rx), float(ry)
            else:
                pos = getattr(obj, "position", None)
                raw_x = float(getattr(pos, "x", 0.0) or 0.0)
                raw_y = float(getattr(pos, "y", 0.0) or 0.0)
                try:
                    tile = content_to_world(raw_x, raw_y)
                except ValueError:
                    tile = None
                if tile is not None:
                    cx, cy = float(tile.x), float(tile.y)
        if cx is not None and cy is not None:
            for dest in _fractional_content_ring(cx, cy, radius):
                points.append(executor._screen_point(dest.x, dest.y, bounds))
    return _dedupe_screen_points(points)


def _attack_body_content(obj: object):
    """Memory ``iscr`` shifted ``ATTACK_AIM_SCREEN_UP_TILES`` up the screen."""
    from app._02_state.objects import Position
    from app._03_world.space.world_coords import content_screen_up
    from app._04_decision import player_mode as pm

    pos = getattr(obj, "position", None)
    raw_x = float(getattr(pos, "x", 0.0) or 0.0)
    raw_y = float(getattr(pos, "y", 0.0) or 0.0)
    try:
        return content_screen_up(raw_x, raw_y, pm.ATTACK_AIM_SCREEN_UP_TILES)
    except ValueError:
        return Position(x=raw_x, y=raw_y)


def mage_spell_cross_points(
    executor: "ActionExecutor",
    obj: object,
    bounds,
) -> list[tuple[float, float]]:
    """Body point, then screen-up, down, left, and right at each cross step.

    The click is not one of these samples. ``mage_cast_click_search`` probes
    them and clicks the center of the samples whose cursor is ``spell``.
    """
    from app._03_world.space.world_coords import content_screen_right, content_screen_up

    center = _attack_body_content(obj)
    points: list[tuple[float, float]] = [
        executor._screen_point(center.x, center.y, bounds)
    ]
    for radius in MAGE_SPELL_CROSS_TILES:
        step = float(radius)
        if step <= 1e-6:
            continue
        for dest in (
            content_screen_up(center.x, center.y, step),
            content_screen_up(center.x, center.y, -step),
            content_screen_right(center.x, center.y, step),
            content_screen_right(center.x, center.y, -step),
        ):
            points.append(executor._screen_point(dest.x, dest.y, bounds))
    return _dedupe_screen_points(points)


def _contiguous_spell_hits(
    points: Iterable[tuple[float, float]],
    hits: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Spell pixels on this monster's cross, stopping at the first gap.

    Point 0 is the body center. Each following group of four is one cross
    step in order up, down, right, left, inner step first. A ``spell`` pixel
    past a non-spell sample is a different monster and is left out. A list
    that is not that cross keeps every hit.
    """
    hit_at = {(float(x), float(y)) for x, y in hits}
    pts = [(float(x), float(y)) for x, y in points]
    if len(pts) < 2 or (len(pts) - 1) % 4 != 0:
        return [p for p in pts if p in hit_at]
    center = pts[0]
    kept: list[tuple[float, float]] = []
    if center in hit_at:
        kept.append(center)
    radii = (len(pts) - 1) // 4
    for direction in range(4):
        arm = [pts[1 + ring * 4 + direction] for ring in range(radii)]
        started = center in hit_at
        for sample in arm:
            if sample in hit_at:
                started = True
                kept.append(sample)
            elif started:
                break
    return kept


def spell_range_center(
    points: Iterable[tuple[float, float]],
) -> tuple[float, float] | None:
    """Midpoint of the spell-hit range on each screen axis."""
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return ((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5)


def object_loot_screen_points(
    executor: "ActionExecutor",
    obj: object,
    bounds,
) -> list[tuple[float, float]]:
    """Pile UV and its memory cell only. Neighbor hunts walk off the pile."""
    from app._04_decision import player_mode as pm
    from app._05_action.travel_click import object_cursor_search_destinations

    dests = object_cursor_search_destinations(
        obj, radius=float(pm.LOOT_CURSOR_SEARCH_TILES)
    )
    return [executor._screen_point(dest.x, dest.y, bounds) for dest in dests]


def _reset_attack_aim_if_target_changed(
    executor: "ActionExecutor",
    target_id: int | None,
) -> None:
    prev = getattr(executor, "_attack_aim_tid", None)
    if target_id is None or prev == int(target_id):
        return
    executor._attack_aim_tid = int(target_id)
    executor._attack_aim_idx = 0
    executor._attack_aim_lock = None


def _next_aim_window(
    executor: "ActionExecutor",
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Take up to ``ATTACK_AIM_PROBES_PER_TICK`` points, advancing a ring index."""
    if not points:
        return []
    n = len(points)
    budget = max(1, min(int(ATTACK_AIM_PROBES_PER_TICK), n))
    idx = int(getattr(executor, "_attack_aim_idx", 0) or 0) % n
    window = [points[(idx + i) % n] for i in range(budget)]
    executor._attack_aim_idx = (idx + budget) % n
    return window


def attack_click_search(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
    *,
    target_id: int | None = None,
    sticky: bool = False,
) -> bool:
    """Probe a small aim window; sticky reuses the last successful pixel.

    Does not walk the full pixel ring every tick. Miss → no click this tick
    (index advances for the next). ``arrow_lack`` aborts for the shop path.
    """
    pts = _dedupe_screen_points(points)
    if not pts:
        return False
    _reset_attack_aim_if_target_changed(executor, target_id)
    tid = int(target_id) if target_id is not None else None
    lock = getattr(executor, "_attack_aim_lock", None)
    if (
        sticky
        and tid is not None
        and isinstance(lock, tuple)
        and len(lock) >= 3
        and int(lock[0]) == tid
    ):
        if _click_when_found(
            executor,
            [(float(lock[1]), float(lock[2]))],
            labels=ATTACK_OK_LABELS,
            stop_labels=("arrow_lack", "dialog"),
        ):
            return True
        executor._attack_aim_lock = None

    window = _next_aim_window(executor, pts)
    if not _click_when_found(
        executor,
        window,
        labels=ATTACK_OK_LABELS,
        stop_labels=("arrow_lack", "dialog"),
    ):
        return False
    xy = getattr(executor, "_last_aim_click_xy", None)
    if tid is not None and isinstance(xy, tuple) and len(xy) >= 2:
        executor._attack_aim_lock = (tid, float(xy[0]), float(xy[1]))
    return True


def _spell_hit(match: CursorMatch | None, thr: float) -> bool:
    if match is None or str(match.label) != "spell":
        return False
    try:
        score = float(match.score)
    except (TypeError, ValueError):
        return False
    return score >= thr


def _click_aim(executor: "ActionExecutor", x: float, y: float) -> tuple[float, float]:
    executor.mouse.click(x, y, snap=True)
    xy = (float(x), float(y))
    executor._last_aim_click_xy = xy
    return xy


def _collect_spell_hits(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Every probed pixel whose cursor is ``spell``. Other labels are skipped."""
    thr = float(get_cursor_matcher().min_score)
    hits: list[tuple[float, float]] = []
    last: CursorMatch | None = None
    for x, y in _dedupe_screen_points(points):
        match = _probe_labels(executor, x, y, _MAGE_CROSS_PROBE_LABELS)
        if match is None:
            continue
        last = match
        if _spell_hit(match, thr):
            hits.append((float(x), float(y)))
    executor.last_cursor_match = last
    if not hits:
        executor.last_cursor_reject_reason = (
            f"{_format_cursor_score_reason(last, thr=thr)} not allowed"
        )
    return hits


def _click_spell_range_center(
    executor: "ActionExecutor",
    hits: list[tuple[float, float]],
) -> tuple[float, float] | None:
    """Click the center of the spell-hit range.

    When that center is not itself ``spell``, click the spell sample nearest
    to it.
    """
    center = spell_range_center(hits)
    if center is None:
        return None
    cx, cy = center
    nearest = min(hits, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    if abs(nearest[0] - cx) <= 1.0 and abs(nearest[1] - cy) <= 1.0:
        return _click_aim(executor, nearest[0], nearest[1])
    thr = float(get_cursor_matcher().min_score)
    match = _probe_labels(executor, cx, cy, _MAGE_CROSS_PROBE_LABELS)
    if _spell_hit(match, thr):
        return _click_aim(executor, cx, cy)
    match = _probe_labels(executor, nearest[0], nearest[1], _MAGE_CROSS_PROBE_LABELS)
    if _spell_hit(match, thr):
        return _click_aim(executor, nearest[0], nearest[1])
    executor.last_cursor_match = match
    executor.last_cursor_reject_reason = (
        f"{_format_cursor_score_reason(match, thr=thr)} not allowed"
    )
    return None


def find_attack_aim_point(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
    *,
    target_id: int | None = None,
    sticky: bool = False,
) -> tuple[float, float] | None:
    """Hover like elf aim; return the pixel where the attack cursor is valid.

    Accepts knife/bow/fist (``arrow``, ``fist``, ``sword``) and an already
    armed ``spell`` circle. ``spell_out_range`` and ``spell_disable`` cancel
    the circle and are not attack-cursor misses. Does **not** click.
    """
    pts = _dedupe_screen_points(points)
    if not pts:
        return None
    _reset_attack_aim_if_target_changed(executor, target_id)
    tid = int(target_id) if target_id is not None else None
    thr = float(get_cursor_matcher().min_score)
    wanted = {str(label).strip().lower() for label in ATTACK_OK_LABELS}
    spell_ready = {"spell"}
    spell_drop = {"spell_out_range", "spell_disable"}
    stop = {"arrow_lack", "dialog"}
    probe = wanted | stop | spell_ready | spell_drop
    executor.mage_spell_ready = False
    executor.spell_aim_suppressed = False

    def _accept(x: float, y: float) -> tuple[float, float] | None:
        if not CURSOR_VERIFY_ENABLED:
            return (float(x), float(y))
        match = _probe_labels(executor, x, y, probe)
        if match is None:
            return None
        label = str(match.label or "")
        if float(match.score) < thr:
            executor.last_cursor_reject_reason = _format_cursor_score_reason(
                match, thr=thr
            )
            return None
        if label in stop:
            executor.last_cursor_reject_reason = (
                f"{_format_cursor_score_reason(match, thr=thr)} blocked"
            )
            return None
        if label in spell_ready:
            executor.spell_aim_suppressed = False
            executor.mage_spell_ready = True
            return (float(x), float(y))
        if label in spell_drop:
            executor.spell_aim_suppressed = True
            executor.last_cursor_reject_reason = None
            cancel_spell_aim(executor, reason="aim:spell circle")
            return None
        if label in wanted:
            executor.spell_aim_suppressed = False
            executor.mage_spell_ready = False
            return (float(x), float(y))
        executor.last_cursor_reject_reason = (
            f"{_format_cursor_score_reason(match, thr=thr)} not allowed"
        )
        return None

    lock = getattr(executor, "_attack_aim_lock", None)
    if (
        sticky
        and tid is not None
        and isinstance(lock, tuple)
        and len(lock) >= 3
        and int(lock[0]) == tid
    ):
        hit = _accept(float(lock[1]), float(lock[2]))
        if hit is not None:
            return hit
        executor._attack_aim_lock = None

    window = _next_aim_window(executor, pts)
    for x, y in window:
        hit = _accept(x, y)
        if hit is not None:
            if tid is not None:
                executor._attack_aim_lock = (tid, hit[0], hit[1])
            return hit
    return None


def mage_cast_at_point(
    executor: "ActionExecutor",
    x: float,
    y: float,
    *,
    target_id: int | None = None,
) -> bool:
    """After the spell key: click ``(x, y)`` only when the cursor is ``spell``."""
    tid = int(target_id) if target_id is not None else None
    if not CURSOR_VERIFY_ENABLED:
        _click_aim(executor, x, y)
        if tid is not None:
            executor._attack_aim_lock = (tid, float(x), float(y))
        return True
    if _click_when_found(
        executor,
        [(float(x), float(y))],
        labels=MAGE_CAST_OK_LABELS,
        stop_labels=("dialog", "spell_disable", "spell_out_range"),
    ):
        if tid is not None:
            xy = getattr(executor, "_last_aim_click_xy", None)
            if isinstance(xy, tuple) and len(xy) >= 2:
                executor._attack_aim_lock = (tid, float(xy[0]), float(xy[1]))
            else:
                executor._attack_aim_lock = (tid, float(x), float(y))
        return True
    return False


def mage_cast_click_search(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
    *,
    target_id: int | None = None,
    sticky: bool = False,
) -> bool:
    """Legacy: probe a cross and click the center of the ``spell`` range.

    Prefer :func:`find_attack_aim_point` + :func:`mage_cast_at_point` for the
    knife-first mage path. Sticky reuses a center while it still reads
    ``spell``. ``spell_disable`` and ``spell_out_range`` do not count.
    """
    pts = _dedupe_screen_points(points)
    if not pts:
        return False
    _reset_attack_aim_if_target_changed(executor, target_id)
    tid = int(target_id) if target_id is not None else None
    if not CURSOR_VERIFY_ENABLED:
        xy = _click_aim(executor, pts[0][0], pts[0][1])
        if tid is not None:
            executor._attack_aim_lock = (tid, xy[0], xy[1])
        return True
    lock = getattr(executor, "_attack_aim_lock", None)
    if (
        sticky
        and tid is not None
        and isinstance(lock, tuple)
        and len(lock) >= 3
        and int(lock[0]) == tid
    ):
        if _click_when_found(
            executor,
            [(float(lock[1]), float(lock[2]))],
            labels=MAGE_CAST_OK_LABELS,
            stop_labels=("dialog",),
        ):
            return True
        executor._attack_aim_lock = None

    clicked = _click_spell_range_center(
        executor,
        _contiguous_spell_hits(pts, _collect_spell_hits(executor, pts)),
    )
    if clicked is None:
        return False
    if tid is not None:
        executor._attack_aim_lock = (tid, clicked[0], clicked[1])
    return True


def dialog_click(executor: "ActionExecutor", x: float, y: float) -> bool:
    """NPC: require DIALOG cursor before clicking."""
    return verified_click(
        executor, x, y, categories=DIALOG_OK_CATEGORIES, snap=True
    )


def npc_search_screen_points(
    cx: float,
    cy: float,
    radius_px: float,
    n: int = 8,
) -> list[tuple[float, float]]:
    """Catalog pixel, then ``n`` points on a circle of ``radius_px``."""
    points: list[tuple[float, float]] = [(cx, cy)]
    if radius_px <= 0:
        return points
    for i in range(n):
        ang = -math.pi / 2 + (2 * math.pi * i) / n
        points.append((cx + radius_px * math.cos(ang), cy + radius_px * math.sin(ang)))
    return points


def dialog_click_ring(
    executor: "ActionExecutor",
    dest,
    screen_xy,
    *,
    radius_px: float,
    step_s: float,
) -> bool:
    """Hover catalog UV, then a slow pixel ring, until the cursor is dialog.

    Always sleeps ``step_s`` between probes. ``_fixed_wait`` is a no-op when
    humanize is off (Practice), which made the ring finish without a visible
    cursor scan and fail before the dialog glyph could appear.
    """
    cx, cy = screen_xy(dest.x, dest.y)
    for x, y in npc_search_screen_points(cx, cy, radius_px):
        executor.mouse.move(x, y, snap=True)
        if step_s > 0:
            time.sleep(step_s)
        if dialog_click(executor, x, y):
            return True
    return False


def dialog_click_destinations(
    executor: "ActionExecutor",
    dests,
    screen_xy,
    *,
    step_s: float,
) -> bool:
    """Hover each content UV (tile hunt) until the cursor is dialog.

    Always sleeps ``step_s`` — Practice does the same; ``_fixed_wait``
    skips when humanize is off and the live bot then clicks too early.
    """
    for dest in dests:
        if dest is None:
            continue
        x, y = screen_xy(float(dest.x), float(dest.y))
        executor.mouse.move(x, y, snap=True)
        if step_s > 0:
            time.sleep(step_s)
        if dialog_click(executor, x, y):
            return True
    return False


def mage_cast_click(executor: "ActionExecutor", x: float, y: float) -> bool:
    return verified_click(
        executor, x, y, labels=MAGE_CAST_OK_LABELS, snap=True
    )


def _current_mouse_px(executor: "ActionExecutor") -> tuple[float, float] | None:
    """Last known mouse pixel, or None if the controller has no position yet."""
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return None
    last = getattr(mouse, "_last_pos", None)
    if isinstance(last, (tuple, list)) and len(last) >= 2:
        return float(last[0]), float(last[1])
    start = getattr(mouse, "_start_pos", None)
    if callable(start):
        try:
            pos = start()
        except Exception:
            return None
        if isinstance(pos, (tuple, list)) and len(pos) >= 2:
            return float(pos[0]), float(pos[1])
    return None


def _item_px(executor: "ActionExecutor", x: float, y: float) -> tuple[float, float]:
    mouse = getattr(executor, "mouse", None)
    to_px = getattr(mouse, "_to_pixels", None) if mouse is not None else None
    if callable(to_px):
        px, py = to_px(x, y)
        return float(px), float(py)
    return float(x), float(y)


def _screen_size_px(executor: "ActionExecutor") -> tuple[float, float]:
    mouse = getattr(executor, "mouse", None)
    w = float(getattr(mouse, "screen_width", 0) or 0) if mouse is not None else 0.0
    h = float(getattr(mouse, "screen_height", 0) or 0) if mouse is not None else 0.0
    return (w if w > 0 else 1920.0), (h if h > 0 else 1080.0)


def loot_nudge_away_point(
    cx: float,
    cy: float,
    rng: random.Random,
    *,
    width: float,
    height: float,
    dist: float | None = None,
) -> tuple[float, float]:
    """Pixel ~``dist`` from ``(cx, cy)``, clamped to the screen."""
    radius = LOOT_CURSOR_NUDGE_PX if dist is None else float(dist)
    ang = rng.random() * 2.0 * math.pi
    nx = cx + radius * math.cos(ang)
    ny = cy + radius * math.sin(ang)
    nx = min(max(0.0, nx), max(0.0, width - 1.0))
    ny = min(max(0.0, ny), max(0.0, height - 1.0))
    if math.hypot(nx - cx, ny - cy) < radius * 0.5:
        toward = 1.0 if cx < width * 0.5 else -1.0
        nx = min(max(0.0, cx + toward * radius), max(0.0, width - 1.0))
        ny = cy
    return nx, ny


def _cursor_is_attack() -> bool | None:
    """True/False when templates can classify; None when classify is unavailable."""
    matcher = get_cursor_matcher()
    if not matcher.loaded:
        return None
    match = classify_cursor()
    if match is None:
        return None
    return (
        match.category is CursorCategory.ATTACK
        or match.label in ("arrow", "arrow_lack", "fist", "sword")
    )


def clear_loot_attack_hover(
    executor: "ActionExecutor",
    *,
    from_xy: tuple[float, float] | None = None,
) -> bool:
    """Snap off leftover attack hover only while the cursor is still ATTACK.

    If classify already reports non-attack (e.g. normal on a corpse), do not
    move — avoids pickup-retry spam hovering around the character. When
    classify is unavailable (``None``), still nudge once for safety.
    """
    mouse = getattr(executor, "mouse", None)
    if mouse is None:
        return False
    # Already clear → F4/click path can proceed without moving the mouse.
    if _cursor_is_attack() is False:
        return False
    if from_xy is not None:
        cx, cy = float(from_xy[0]), float(from_xy[1])
    else:
        pos = _current_mouse_px(executor)
        if pos is None:
            width, height = _screen_size_px(executor)
            cx, cy = width * 0.5, height * 0.5
        else:
            cx, cy = pos
    rng = getattr(executor, "_rng", None)
    if rng is None:
        rng = random
    width, height = _screen_size_px(executor)
    radii = LOOT_CURSOR_CLEAR_RADII_PX or (float(LOOT_CURSOR_NUDGE_PX),)
    moved = False
    for radius in radii:
        nx, ny = loot_nudge_away_point(
            cx, cy, rng, width=width, height=height, dist=float(radius)
        )
        mouse.move(nx, ny, snap=True)
        moved = True
        cx, cy = nx, ny
        if LOOT_CURSOR_CLEAR_SETTLE_S > 0:
            time.sleep(float(LOOT_CURSOR_CLEAR_SETTLE_S))
        attack = _cursor_is_attack()
        if attack is not True:
            break
    return moved


def nudge_loot_cursor_if_nearby(executor: "ActionExecutor", x: float, y: float) -> bool:
    """If already on/near the item, snap away so the attack cursor can clear.

    Prefer ``clear_loot_attack_hover`` for pickup/F4 (always clear). Kept for
    callers that only want a near-pile nudge.
    """
    pos = _current_mouse_px(executor)
    if pos is None:
        return False
    tx, ty = _item_px(executor, x, y)
    if math.hypot(pos[0] - tx, pos[1] - ty) > LOOT_CURSOR_NEAR_PX:
        return False
    return clear_loot_attack_hover(executor, from_xy=pos)


def loot_click_search(
    executor: "ActionExecutor",
    points: Iterable[tuple[float, float]],
) -> bool:
    """Click the pile points only. Do not hunt neighbors (NORMAL = walk)."""
    for x, y in _dedupe_screen_points(points):
        if loot_click(executor, x, y):
            return True
    return False


def loot_click(executor: "ActionExecutor", x: float, y: float) -> bool:
    """Pickup: leave a leftover attack hover, settle on the pile, then click."""
    clear_loot_attack_hover(executor, from_xy=_item_px(executor, x, y))
    if not CURSOR_VERIFY_ENABLED:
        executor.mouse.move_and_click(x, y, snap=True)
        return True
    executor.mouse.move(x, y, snap=True)
    if LOOT_AIM_SETTLE_S > 0:
        time.sleep(LOOT_AIM_SETTLE_S)
    ok, match = verify_cursor(categories=LOOT_OK_CATEGORIES, labels=LOOT_OK_LABELS)
    executor.last_cursor_match = match
    if (
        ok
        and match is not None
        and (
            match.label == "dialog"
            or match.category is CursorCategory.DIALOG
        )
        and not _dialog_click_allowed(
            categories=LOOT_OK_CATEGORIES, labels=LOOT_OK_LABELS
        )
    ):
        ok = False
    if not ok:
        from app._05_action.cursor_match import get_cursor_matcher

        thr = float(get_cursor_matcher().min_score)
        if match is None:
            executor.last_cursor_reject_reason = (
                f"cursor unmatched / capture failed need>={thr:.2f}"
            )
        else:
            executor.last_cursor_reject_reason = (
                f"cursor={match.label}/{match.category.value} "
                f"score={match.score:.3f} need>={thr:.2f} not allowed"
            )
        return False
    executor.mouse.click(x, y, snap=True)
    return True


def click_closed_door(executor: "ActionExecutor", x: float, y: float) -> bool:
    """One click on a door cursor. Does not repeat, so the door stays open."""
    ok, match = verify_cursor(labels=("door",))
    executor.last_cursor_match = match
    if not ok or match is None or str(getattr(match, "label", "") or "") != "door":
        return False
    executor.mouse.click(x, y, snap=True, until_walk=False)
    return True


def sweep_click_closed_door(
    executor: "ActionExecutor",
    cx: float,
    cy: float,
    client_h: float,
) -> bool:
    """Hover the door cell, then the entrance rings, and click the first door cursor.

    One pass and one click. The click is not repeated, so the opened door stays open.
    """
    from app._04_decision.world_nav.gate import _gate_circle_samples

    samples, _turn = _gate_circle_samples(float(cx), float(cy), float(client_h))
    points = [(float(cx), float(cy))]
    points.extend((float(sx), float(sy)) for sx, sy, _r, _ang in samples)
    for x, y in points:
        try:
            executor.mouse.move(x, y, snap=True)
        except Exception:
            return False
        if click_closed_door(executor, x, y):
            return True
        time.sleep(0.02)
    return False


def travel_click(executor: "ActionExecutor", x: float, y: float) -> bool:
    """Ground hop: require NORMAL cursor (not attack / dialog / door).

    ``snap=True`` skips the curved mouse path so search/travel hops stay
    inside the tick budget (same as attack/loot). The click repeats until
    the body stands or the walk starts; each re-click re-checks NORMAL.
    """
    return verified_click(
        executor,
        x,
        y,
        categories=LOOT_OK_CATEGORIES,
        snap=True,
        until_walk=True,
    )


__all__ = [
    "CURSOR_VERIFY_ENABLED",
    "CURSOR_SETTLE_S",
    "CURSOR_SEARCH_SETTLE_S",
    "LOOT_AIM_SETTLE_S",
    "CURSOR_CAPTURE_SIZE",
    "LOOT_CURSOR_NUDGE_PX",
    "LOOT_CURSOR_NEAR_PX",
    "LOOT_CURSOR_CLEAR_SETTLE_S",
    "LOOT_CURSOR_CLEAR_RADII_PX",
    "ATTACK_PIXEL_RADII_PX",
    "ATTACK_PIXEL_RING_N",
    "ATTACK_AIM_PROBES_PER_TICK",
    "MAGE_SPELL_CROSS_TILES",
    "clear_loot_attack_hover",
    "classify_cursor",
    "is_cursor_paralyzed",
    "verify_cursor",
    "aim_and_verify",
    "verified_click",
    "verify_attack_aim",
    "verify_mage_cast_aim",
    "PARTY_LIST_AIM_WAIT_S",
    "PARTY_LIST_AIM_POLL_S",
    "wait_party_spell_aim",
    "cursor_is_spell_aim",
    "cancel_spell_aim",
    "verify_loot_aim",
    "attack_click",
    "attack_pixel_offsets",
    "object_attack_screen_points",
    "mage_spell_cross_points",
    "spell_range_center",
    "object_loot_screen_points",
    "attack_click_search",
    "find_attack_aim_point",
    "mage_cast_at_point",
    "mage_cast_click_search",
    "mage_cast_click",
    "loot_click",
    "loot_click_search",
    "nudge_loot_cursor_if_nearby",
    "loot_nudge_away_point",
    "dialog_click",
    "dialog_click_ring",
    "dialog_click_destinations",
    "npc_search_screen_points",
    "click_closed_door",
    "sweep_click_closed_door",
    "travel_click",
]
