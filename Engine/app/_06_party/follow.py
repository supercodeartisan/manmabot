"""Pure follow geometry: travel/stop bands + approach tile (never on leader)."""
from __future__ import annotations

import random
from typing import Callable, Iterable, Optional

# Old walking start was ``follow_tiles - TRAVEL_LEAD_TILES`` (default 6).
# Close follow restarts one tile outside the stop band instead.
TRAVEL_LEAD_TILES = 2
CLOSE_RESTART_GAP = 1
# A follow click stays inside this many tiles so the hop cannot walk past the leader.
FOLLOW_CLICK_TILES = 2
# Open straight ground only: one tile past the current hop, still short of a long click.
FOLLOW_EXTEND_TILES = 3
# On the formation slot. One tile off follows at once, including a one-tile leader step.
ARRIVAL_TOLERANCE = 0
# A stand seat is a 3×3. The member holds on the center tile or any neighbor.
STAND_ARRIVE_TILES = 1
# Keep the absolute click goal while the ideal slot drifts within this Chebyshev.
STICKY_GOAL_SLACK = 2


def follow_kind(
    distance: int,
    *,
    follow_tiles: int = 8,
    stop_tiles: int = 2,
    leader_farming: bool = False,
    leader_stopped: bool = False,
    chasing: bool = False,
    at_settle_stand: Optional[bool] = None,
    at_travel_spot: Optional[bool] = None,
    **_legacy: object,
) -> tuple[str, bool]:
    """Return ``(band, chasing)`` where band is follow|near.

    Rubber-band on distance to the leader only. A behind-slot, cardinal stand,
    or turret seat is not a walk goal (those sent the member past / around the
    leader). At or inside ``stop_tiles``: hold. One tile farther: follow.
    ``follow_tiles`` does not delay the start. Combat (``leader_farming``):
    caller handles assist/close-in; here ``near`` means within the travel leash.
    """
    del _legacy, at_settle_stand, at_travel_spot
    dist = int(distance)
    follow = max(1, int(follow_tiles))
    stop = max(0, min(follow, int(stop_tiles)))
    if leader_farming:
        if dist > follow:
            return "follow", True
        return "near", False
    if dist <= stop:
        return "near", False
    if leader_stopped:
        return "follow", True
    start = stop + CLOSE_RESTART_GAP
    if dist >= start:
        return "follow", True
    if chasing:
        return "follow", True
    return "near", False


def travel_band(follow_tiles: int) -> int:
    """Max walk steps from the leader for the formation slot (lag room kept)."""
    return max(1, int(follow_tiles) - TRAVEL_LEAD_TILES)


def unit8(move_dir: Optional[tuple[int, int]]) -> tuple[int, int]:
    """Snap a tile delta to an 8-direction unit step."""
    if move_dir is None:
        return (0, 0)
    dx, dy = int(move_dir[0]), int(move_dir[1])
    if dx == 0 and dy == 0:
        return (0, 0)
    sx = 0 if dx == 0 else (1 if dx > 0 else -1)
    sy = 0 if dy == 0 else (1 if dy > 0 else -1)
    return (sx, sy)


def formation_slot_offset(
    move_dir: Optional[tuple[int, int]],
    distance: int,
    *,
    lateral: int = 0,
) -> tuple[int, int]:
    """Reynolds leader-following slot: behind the leader, optional side step.

    Target is ``leader + offset``. Behind the move vector so the member trails
    the team instead of cutting in front (GDC'99 leader following / Arrive).
    """
    d = max(1, int(distance))
    lat = int(lateral)
    ux, uy = unit8(move_dir)
    if ux == 0 and uy == 0:
        # Facing unknown — sit a few tiles "south" with optional side.
        return (lat, d)
    # Behind = opposite of facing; lateral = rotate facing 90° CCW.
    bx, by = -ux * d, -uy * d
    px, py = -uy, ux
    return (bx + px * lat, by + py * lat)


def sticky_goal_tile(
    ideal: tuple[int, int],
    previous: Optional[tuple[int, int]],
    *,
    slack: int = STICKY_GOAL_SLACK,
) -> tuple[int, int]:
    """Keep ``previous`` while the ideal slot only drifts within ``slack``.

    Prevents repathing every leader step (formation zLookAhead / sticky goal).
    """
    ix, iy = int(ideal[0]), int(ideal[1])
    if previous is None:
        return (ix, iy)
    px, py = int(previous[0]), int(previous[1])
    if max(abs(px - ix), abs(py - iy)) <= max(0, int(slack)):
        return (px, py)
    return (ix, iy)


def tile_chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))


def offset_behind_move(
    offset: tuple[int, int],
    move_dir: Optional[tuple[int, int]],
) -> bool:
    """True when ``offset`` sits in the rear half-plane of ``move_dir``.

    Pure side (dot == 0) and ahead (dot > 0) are not behind. No move dir →
    never behind (caller has no facing yet).
    """
    if move_dir is None:
        return False
    mx, my = int(move_dir[0]), int(move_dir[1])
    if mx == 0 and my == 0:
        return False
    return int(offset[0]) * mx + int(offset[1]) * my < 0


def cardinal_tiles(cx: int, cy: int, radius: int) -> list[tuple[int, int]]:
    """Up / down / left / right of ``(cx, cy)`` at ``radius`` (min 1)."""
    r = max(1, int(radius))
    x, y = int(cx), int(cy)
    return [(x, y - r), (x, y + r), (x - r, y), (x + r, y)]


def choose_settle_stand(
    is_walkable: Callable[[int, int], bool],
    leader: tuple[int, int],
    radius: int,
    occupied: Iterable[tuple[int, int]],
    rng: random.Random,
    previous: Optional[tuple[int, int]] = None,
    *,
    exclude: Iterable[tuple[int, int]] = (),
) -> Optional[tuple[int, int]]:
    """Random cardinal tile beside a stopped leader; keeps ``previous`` while valid."""
    blocked = {(int(x), int(y)) for x, y in occupied}
    blocked.update((int(x), int(y)) for x, y in exclude)
    cards = cardinal_tiles(leader[0], leader[1], radius)

    def ok(tile: tuple[int, int]) -> bool:
        if tile in blocked:
            return False
        try:
            return bool(is_walkable(int(tile[0]), int(tile[1])))
        except Exception:
            return False

    if previous is not None:
        prev = (int(previous[0]), int(previous[1]))
        if prev in cards and ok(prev):
            return prev
    candidates = [tile for tile in cards if ok(tile)]
    if not candidates:
        return None
    return rng.choice(candidates)


def tiles_in_radius(
    cx: int,
    cy: int,
    radius: int,
    *,
    include_center: bool = False,
) -> list[tuple[int, int]]:
    r = max(0, int(radius))
    out: list[tuple[int, int]] = []
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if max(abs(dx), abs(dy)) > r:
                continue
            if dx == 0 and dy == 0 and not include_center:
                continue
            out.append((int(cx) + dx, int(cy) + dy))
    return out


def choose_approach_tile(
    is_walkable: Callable[[int, int], bool],
    target: tuple[int, int],
    radius: int,
    occupied: Iterable[tuple[int, int]],
    rng: random.Random,
    previous: Optional[tuple[int, int]] = None,
    *,
    exclude: Iterable[tuple[int, int]] = (),
    prefer_near: Optional[tuple[int, int]] = None,
) -> Optional[tuple[int, int]]:
    """Walkable tile near target; never the target's own cell.

    Prefers ``previous`` when still valid. Otherwise picks the candidate
    closest to ``prefer_near`` (usually the player) for smoother paths.
    """
    tx, ty = int(target[0]), int(target[1])
    blocked = {(int(x), int(y)) for x, y in occupied}
    blocked.add((tx, ty))
    blocked.update((int(x), int(y)) for x, y in exclude)

    def ok(tile: tuple[int, int]) -> bool:
        x, y = int(tile[0]), int(tile[1])
        if (x, y) in blocked:
            return False
        if max(abs(x - tx), abs(y - ty)) > int(radius):
            return False
        try:
            return bool(is_walkable(x, y))
        except Exception:
            return False

    if previous is not None and ok(previous):
        return (int(previous[0]), int(previous[1]))
    candidates = [tile for tile in tiles_in_radius(tx, ty, radius) if ok(tile)]
    if not candidates:
        return None
    if prefer_near is not None:
        px, py = int(prefer_near[0]), int(prefer_near[1])
        return min(
            candidates,
            key=lambda t: (
                max(abs(int(t[0]) - px), abs(int(t[1]) - py)),
                abs(int(t[0]) - tx) + abs(int(t[1]) - ty),
                int(t[0]),
                int(t[1]),
            ),
        )
    return rng.choice(candidates)


def guid_key(value: object) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


def follow_extend_hop(
    member: tuple[int, int],
    hop: tuple[int, int],
    slot: tuple[int, int],
    *,
    kind: str,
) -> Optional[tuple[int, int]]:
    """One tile past ``hop`` when the member, the hop, and the slot are one line.

    A trail seat stays on the short hop. The new tile stays within
    ``FOLLOW_EXTEND_TILES`` of the member and closer to the slot than ``hop``.
    """
    if str(kind or "") == "trail":
        return None
    mx, my = int(member[0]), int(member[1])
    hx, hy = int(hop[0]), int(hop[1])
    sx, sy = int(slot[0]), int(slot[1])
    direction = unit8((sx - mx, sy - my))
    if direction == (0, 0) or unit8((hx - mx, hy - my)) != direction:
        return None
    if unit8((sx - hx, sy - hy)) != direction:
        return None
    nxt = (hx + direction[0], hy + direction[1])
    if max(abs(nxt[0] - mx), abs(nxt[1] - my)) > FOLLOW_EXTEND_TILES:
        return None
    if tile_chebyshev(nxt, (sx, sy)) >= tile_chebyshev((hx, hy), (sx, sy)):
        return None
    return nxt


def follow_hop_still_closes(
    member: tuple[int, int],
    slot: tuple[int, int],
    hop: Optional[tuple[int, int]],
) -> bool:
    """True when ``hop`` is still a step from the member toward ``slot``.

    The slot is the formation tile from this memory read, not the leader tile.
    A hop past that slot, or a hop whose direction differs from the current
    member-to-slot delta, does not count.
    """
    if hop is None:
        return False
    mx, my = int(member[0]), int(member[1])
    sx, sy = int(slot[0]), int(slot[1])
    hx, hy = int(hop[0]), int(hop[1])
    if (hx, hy) == (mx, my):
        return False
    slot_dir = unit8((sx - mx, sy - my))
    if slot_dir == (0, 0) or unit8((hx - mx, hy - my)) != slot_dir:
        return False
    return max(abs(hx - mx), abs(hy - my)) <= max(abs(sx - mx), abs(sy - my))


__all__ = [
    "ARRIVAL_TOLERANCE",
    "STAND_ARRIVE_TILES",
    "STICKY_GOAL_SLACK",
    "CLOSE_RESTART_GAP",
    "FOLLOW_CLICK_TILES",
    "FOLLOW_EXTEND_TILES",
    "follow_extend_hop",
    "TRAVEL_LEAD_TILES",
    "cardinal_tiles",
    "choose_approach_tile",
    "choose_settle_stand",
    "follow_hop_still_closes",
    "follow_kind",
    "formation_slot_offset",
    "guid_key",
    "offset_behind_move",
    "sticky_goal_tile",
    "tile_chebyshev",
    "tiles_in_radius",
    "travel_band",
    "unit8",
]
