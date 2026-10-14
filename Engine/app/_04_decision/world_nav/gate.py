"""Map-gate click helper for world-nav map transitions (ActionExecutor)."""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any, Callable, Optional

LogFn = Callable[[str], None]

GATE_PROBE_S = 20.0
# Concentric rings around the entrance screen point, as fractions of client height.
# Example @ height=600: 12, 24, 36, 48, 60 px. Inner → outer, 30° steps.
GATE_RADIUS_FRACS: tuple[float, ...] = (0.02, 0.04, 0.06, 0.08, 0.1)
GATE_STEP_DEG = 30
# After GATE click: treat click as attempt; wait this long for MapSubsystem mapId
# and (when provided) landing cell near the planned ``to`` tile.
TRANSITION_WAIT_S = 5.0
# Dest mapId can flip a tick before absolute xy updates (seen: map1 with TI cell
# 32477 → dungeon walk no_path). Require landing within this Chebyshev of to-xy.
LAND_XY_SLACK = 24
# Cursor search → click → mapId(+xy) wait; one full retry if land fails.
GATE_ATTEMPTS = 2
# Fresh DLL path (discoverNow) can hang; pull-now uses snapshot(False) ~20ms.
# Keep a short timeout only as a driver-stall safety net.
_FRESH_POSE_TIMEOUT_S = 1.0


def _chev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(int(ax) - int(bx)), abs(int(ay) - int(by)))


def _landed(
    live: Optional[tuple[int, int, int]],
    expect: int,
    expect_xy: Optional[tuple[int, int]],
) -> bool:
    if live is None or int(live[0]) != int(expect):
        return False
    if expect_xy is None:
        return True
    return _chev(live[1], live[2], expect_xy[0], expect_xy[1]) <= LAND_XY_SLACK


def run_gate_click(
    *,
    actions: Any,
    bounds: Any,
    entrance_abs: tuple[int, int],
    pose_abs: tuple[int, int],
    expect_map_id: int,
    read_pose: Callable[[], Optional[tuple[int, int, int]]],
    read_pose_fresh: Callable[[], Optional[tuple[int, int, int]]] | None = None,
    expect_xy: tuple[int, int] | None = None,
    stop: Callable[[], bool] | None = None,
    log: LogFn | None = None,
) -> tuple[bool, str]:
    """ESC → circular GATE search → click → wait mapId (+ land xy) (up to 2 attempts).

    ``read_pose`` is for probe re-anchor (cached / non-blocking).
    ``read_pose_fresh`` is for post-click MapSubsystem mapId only — never call
    it before/during the cursor loop (driver hang looked like a crash).

    ``expect_xy`` is the planned destination cell on ``expect_map_id``. When set,
    success requires live xy near that cell so a mapId-only flip with stale
    source-map coordinates cannot advance the plan.

    Rings: ``GATE_RADIUS_FRACS`` × client height, ``GATE_STEP_DEG`` around the
    entrance. Probe moves use ``snap=True`` so all ring samples are visited.
    """
    _log = log or (lambda _s: None)
    read_land = read_pose_fresh or read_pose
    expect = int(expect_map_id)
    land_xy = (
        (int(expect_xy[0]), int(expect_xy[1])) if expect_xy is not None else None
    )
    fx, fy = int(entrance_abs[0]), int(entrance_abs[1])
    px, py = int(pose_abs[0]), int(pose_abs[1])

    last_err = "GATE cursor not found"
    for attempt in range(1, GATE_ATTEMPTS + 1):
        if stop is not None and stop():
            return False, "interrupted"

        # Cached only — fresh monitor here hung ~28s between attempts (worker dead).
        live0 = read_pose()
        if _landed(live0, expect, land_xy):
            return True, f"already on dest map{expect}"
        if live0 is not None:
            px, py = live0[1], live0[2]

        ok, detail = _one_gate_attempt(
            actions=actions,
            bounds=bounds,
            entrance_abs=(fx, fy),
            pose_abs=(px, py),
            expect_map_id=expect,
            expect_xy=land_xy,
            read_pose=read_pose,
            read_land=read_land,
            stop=stop,
            log=_log,
            attempt=attempt,
        )
        if ok:
            return True, detail
        last_err = detail
        live = read_pose()
        if live is not None:
            px, py = live[1], live[2]
        _log(f"GATE attempt {attempt}/{GATE_ATTEMPTS} failed: {detail}")

    return False, last_err


def _call_with_timeout(
    fn: Callable[[], Any],
    timeout_s: float,
) -> Any:
    """Run ``fn`` on a daemon thread; return None on timeout (do not join forever)."""
    box: list[Any] = [None]
    err: list[BaseException] = []

    def _run() -> None:
        try:
            box[0] = fn()
        except BaseException as exc:  # noqa: BLE001 — surface to caller via None
            err.append(exc)

    thread = threading.Thread(target=_run, name="gate-fresh-pose", daemon=True)
    thread.start()
    thread.join(max(0.05, float(timeout_s)))
    if thread.is_alive():
        return None
    if err:
        return None
    return box[0]


def _one_gate_attempt(
    *,
    actions: Any,
    bounds: Any,
    entrance_abs: tuple[int, int],
    pose_abs: tuple[int, int],
    expect_map_id: int,
    read_pose: Callable[[], Optional[tuple[int, int, int]]],
    read_land: Callable[[], Optional[tuple[int, int, int]]],
    stop: Callable[[], bool] | None,
    log: LogFn,
    attempt: int,
    expect_xy: tuple[int, int] | None = None,
) -> tuple[bool, str]:
    from app._03_world.space.world_coords import world_to_content
    from app._05_action.cursor_catalog import CursorCategory
    from app._05_action.cursor_verify import classify_cursor

    fx, fy = int(entrance_abs[0]), int(entrance_abs[1])
    px, py = int(pose_abs[0]), int(pose_abs[1])
    client_h = float(getattr(bounds, "height", 600) or 600)
    land_xy = (
        (int(expect_xy[0]), int(expect_xy[1])) if expect_xy is not None else None
    )

    try:
        actions.keyboard.press("esc")
    except Exception:
        pass
    time.sleep(0.35)

    radii_px = [round(float(f) * client_h, 1) for f in GATE_RADIUS_FRACS]
    gate_xy: tuple[int, int] | None = None
    gate_report = ""
    last_center = (int(px), int(py))
    t0 = time.time()
    bundle_i = 0
    # Each bundle = one full pass of GATE_RADIUS_FRACS. Recompute ring centre
    # from live player xy at every bundle start (not every sample).
    while time.time() - t0 < GATE_PROBE_S and gate_xy is None:
        if stop is not None and stop():
            return False, "interrupted"

        pose_src = "intent"
        live_start = _call_with_timeout(read_land, _FRESH_POSE_TIMEOUT_S)
        if live_start is None:
            live_start = read_pose()
            if live_start is not None:
                pose_src = "cache"
        else:
            pose_src = "fresh"
        if live_start is not None:
            if _landed(live_start, int(expect_map_id), land_xy):
                return True, "already on dest"
            px, py = int(live_start[1]), int(live_start[2])

        content0 = world_to_content(float(fx - px), float(fy - py))
        cx0, cy0 = actions._screen_point(content0.x, content0.y, bounds)
        cx, cy = float(cx0), float(cy0)
        last_center = (int(round(cx)), int(round(cy)))
        samples, turn = _gate_circle_samples(cx, cy, client_h)
        bundle_i += 1
        log(
            f"GATE circle {turn} n={len(samples)} entrance=({fx},{fy}) "
            f"player=({px},{py}) pose={pose_src} "
            f"attempt={attempt}/{GATE_ATTEMPTS} bundle={bundle_i} "
            f"center=({last_center[0]},{last_center[1]}) "
            f"client_h={client_h:.0f} "
            f"rings_frac={list(GATE_RADIUS_FRACS)} rings_px={radii_px} "
            f"step_deg={GATE_STEP_DEG} (inner→outer)"
        )

        for _sx0, _sy0, r_frac, ang_deg in samples:
            if time.time() - t0 >= GATE_PROBE_S:
                break
            if stop is not None and stop():
                return False, "interrupted"
            live = read_pose()
            if _landed(live, int(expect_map_id), land_xy):
                return True, "already on dest"
            r_px = float(r_frac) * client_h
            rad = math.radians(ang_deg)
            sx = int(round(cx + r_px * math.cos(rad)))
            sy = int(round(cy + r_px * math.sin(rad)))
            try:
                # snap=True: visit every ring sample; bezier path skipped ~all of them.
                actions.mouse.move(sx, sy, snap=True)
            except Exception as exc:
                return False, f"GATE mouse move failed: {exc}"
            try:
                match = classify_cursor()
            except Exception as exc:
                return False, f"GATE cursor classify failed: {exc}"
            cat = match.category if match is not None else None
            if cat is CursorCategory.GATE:
                gate_xy = (sx, sy)
                gate_report = (
                    f"r_frac={r_frac:.2f} r_px={r_px:.1f} ang={ang_deg:.0f} "
                    f"screen=({sx},{sy}) bundle={bundle_i}"
                )
                log(f"GATE SUCCESS {gate_report}")
                break
            time.sleep(0.02)

    if gate_xy is None:
        return (
            False,
            "GATE cursor not found on rings "
            f"r∈{list(GATE_RADIUS_FRACS)}×h={radii_px}px "
            f"center=({last_center[0]},{last_center[1]}) bundles={bundle_i}",
        )

    try:
        actions.mouse.move_and_click(gate_xy[0], gate_xy[1], snap=True)
    except Exception as exc:
        return False, f"GATE click failed: {exc}"
    xy_note = (
        f" xy~({land_xy[0]},{land_xy[1]})±{LAND_XY_SLACK}"
        if land_xy is not None
        else ""
    )
    log(
        f"GATE click attempt-ok {gate_report} "
        f"wait_mapId={expect_map_id}{xy_note}s={TRANSITION_WAIT_S}"
    )

    land_t0 = time.time()
    last_live: Optional[tuple[int, int, int]] = None
    while time.time() - land_t0 < TRANSITION_WAIT_S:
        if stop is not None and stop():
            return False, "interrupted"

        def _fresh() -> Optional[tuple[int, int, int]]:
            return read_land()

        live = _call_with_timeout(_fresh, _FRESH_POSE_TIMEOUT_S)
        if live is None:
            # Timed out / error — try cached pose once so mapId=0 lands still work.
            live = read_pose()
        if live is not None:
            last_live = live
        if _landed(live, int(expect_map_id), land_xy):
            assert live is not None
            return True, f"landed map{live[0]} ({live[1]},{live[2]})"
        time.sleep(0.15)
    if last_live is not None and int(last_live[0]) == int(expect_map_id):
        return (
            False,
            f"mapId={expect_map_id} but xy=({last_live[1]},{last_live[2]}) "
            f"not near land"
            + (
                f" ({land_xy[0]},{land_xy[1]})±{LAND_XY_SLACK}"
                if land_xy is not None
                else ""
            ),
        )
    return False, f"mapId did not become {expect_map_id} within {TRANSITION_WAIT_S:.0f}s"


def _gate_circle_samples(
    cx: float,
    cy: float,
    client_h: float,
) -> tuple[list[tuple[float, float, float, float]], str]:
    """Build ring samples: for each radius frac, 360/step angles around centre.

    Each entry is ``(sx, sy, r_frac, angle_deg)`` with angle 0=right, 90=down.
    Order is inner ring complete, then next radius (inner → outer).
    """
    start_deg = float(random.randrange(0, 360, max(1, GATE_STEP_DEG)))
    clockwise = bool(random.getrandbits(1))
    sign = -1.0 if clockwise else 1.0
    h = max(1.0, float(client_h))
    out: list[tuple[float, float, float, float]] = []
    n_steps = max(1, int(round(360 / max(1, GATE_STEP_DEG))))
    for r_frac in GATE_RADIUS_FRACS:
        r_px = float(r_frac) * h
        for i in range(n_steps):
            ang = (start_deg + sign * i * GATE_STEP_DEG) % 360.0
            rad = math.radians(ang)
            sx = cx + r_px * math.cos(rad)
            sy = cy + r_px * math.sin(rad)
            out.append((sx, sy, float(r_frac), float(ang)))
    return out, ("CW" if clockwise else "CCW")
