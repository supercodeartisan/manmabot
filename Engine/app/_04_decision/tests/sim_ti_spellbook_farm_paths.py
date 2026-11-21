"""Smoke + draw: 마법서→area_1 with random-among-shortest then via deform."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from app._04_decision.nav_prebuild import load_nav_prebuild
from app._04_decision.pathfinding import (
    find_path,
    find_path_random_shortest,
    list_shortest_paths,
)

ROOT = Path(__file__).resolve().parents[3] / "data" / "maps" / "talking_island"
OUT_DIR = ROOT
OX, OY = 32256, 32704
SCALE = 4
RUNS = 30

MERCHANT_WORLD = (32560, 33088)
FARMS = {
    "area_1": (204, 447, 285, 480),
    "area_2": (306, 322, 367, 350),
    "area_3": (284, 155, 339, 196),
    "area_4": (407, 136, 437, 171),
}
COLORS = [
    (255, 70, 70, 210),
    (70, 150, 255, 210),
    (70, 220, 100, 210),
    (255, 190, 50, 210),
    (220, 80, 220, 210),
    (50, 220, 220, 210),
    (255, 120, 40, 210),
    (160, 100, 255, 210),
    (255, 255, 80, 210),
    (80, 255, 180, 210),
]


def _snap(terrain, xy, r: int = 12):
    x, y = int(xy[0]), int(xy[1])
    if terrain.is_walkable(x, y):
        return (x, y)
    for rad in range(1, r + 1):
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                if max(abs(dx), abs(dy)) != rad:
                    continue
                nx, ny = x + dx, y + dy
                if terrain.is_walkable(nx, ny):
                    return (nx, ny)
    return None


def _draw_farms(draw: ImageDraw.ImageDraw) -> None:
    for name, (x0, y0, x1, y1) in FARMS.items():
        box = [x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE]
        draw.rectangle(box, outline=(255, 220, 0, 180), width=3)
        draw.text((box[0] + 6, box[1] + 6), name, fill=(255, 220, 0, 230))


def _paint_path(
    draw: ImageDraw.ImageDraw,
    route: list[tuple[int, int]],
    color: tuple[int, int, int, int],
    *,
    off: int = 0,
) -> None:
    """Fill each nav tile (not a chord line) so obstacles are not visually crossed."""
    for tx, ty in route:
        x0 = tx * SCALE + off
        y0 = ty * SCALE + off
        draw.rectangle(
            (x0, y0, x0 + SCALE - 1, y0 + SCALE - 1),
            fill=color,
        )


def _render(
    nav: Image.Image,
    routes: list[list[tuple[int, int]]],
    det: list[tuple[int, int]],
    start: tuple[int, int],
    goal: tuple[int, int],
    title: str,
    filename: str,
) -> None:
    overlay = Image.new("RGBA", nav.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    _draw_farms(draw)
    # Deterministic shortest in white tile marks
    _paint_path(draw, det, (255, 255, 255, 100))
    for i, route in enumerate(routes):
        color = COLORS[i % len(COLORS)]
        _paint_path(draw, route, color, off=(i % 3))
    sx = start[0] * SCALE + SCALE // 2
    sy = start[1] * SCALE + SCALE // 2
    gx = goal[0] * SCALE + SCALE // 2
    gy = goal[1] * SCALE + SCALE // 2
    draw.ellipse((sx - 10, sy - 10, sx + 10, sy + 10), fill=(255, 40, 40, 255))
    draw.text((sx + 14, sy - 12), "마법서", fill=(255, 80, 80, 255))
    draw.ellipse((gx - 10, gy - 10, gx + 10, gy + 10), fill=(40, 220, 80, 255))
    draw.text((gx + 14, gy - 12), "area_1", fill=(80, 255, 80, 255))
    draw.text((20, 20), title, fill=(255, 255, 255, 255))
    out = Image.alpha_composite(nav, overlay)
    full = OUT_DIR / filename
    out.save(full)
    xs = [t[0] * SCALE for r in routes for t in r] + [start[0] * SCALE, goal[0] * SCALE]
    ys = [t[1] * SCALE for r in routes for t in r] + [start[1] * SCALE, goal[1] * SCALE]
    pad = 120
    crop = (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(out.width, max(xs) + pad + SCALE),
        min(out.height, max(ys) + pad + SCALE),
    )
    crop_path = OUT_DIR / filename.replace(".png", "_crop.png")
    out.crop(crop).save(crop_path)
    print(f"wrote {full.name} + {crop_path.name} crop={crop}")


def main() -> None:
    terrain, _c, _g, _m = load_nav_prebuild(ROOT / "nav_prebuild")
    start = _snap(terrain, (MERCHANT_WORLD[0] - OX, MERCHANT_WORLD[1] - OY))
    goal = _snap(
        terrain,
        (
            (FARMS["area_1"][0] + FARMS["area_1"][2]) // 2,
            (FARMS["area_1"][1] + FARMS["area_1"][3]) // 2,
        ),
        r=24,
    )
    assert start and goal
    det = find_path(terrain, start, goal)
    assert det
    alts = list_shortest_paths(terrain, start, goal, max_paths=4)
    print(f"start={start} goal={goal}")
    print(f"det_steps={len(det)-1} listed_equal_shortest={len(alts)}")

    # --- smoke: live entry (random among shortest + via deform) ---
    live: list[list[tuple[int, int]]] = []
    alt_only: list[list[tuple[int, int]]] = []
    errors = 0
    for i in range(RUNS):
        p = find_path_random_shortest(terrain, start, goal, sticky_path=None)
        a = find_path_random_shortest(
            terrain, start, goal, sticky_path=None, apply_lateral_nudge=False
        )
        try:
            assert p and p[0] == start and p[-1] == goal
            assert a and a[0] == start and a[-1] == goal
            for x, y in p:
                assert terrain.is_walkable(x, y)
            for u, v in zip(p, p[1:]):
                assert terrain.can_step(u[0], u[1], v[0], v[1])
        except AssertionError as exc:
            errors += 1
            print(f"FAIL run {i}: {exc}")
            continue
        live.append([(int(x), int(y)) for x, y in p])
        alt_only.append([(int(x), int(y)) for x, y in a])
        print(
            f"  #{i+1:02d} alt_steps={len(a)-1} live_steps={len(p)-1} "
            f"live_unique={len({tuple(r) for r in live})} "
            f"alt_unique={len({tuple(r) for r in alt_only})}"
        )

    live_u = len({tuple(r) for r in live})
    alt_u = len({tuple(r) for r in alt_only})
    live_lens = Counter(len(r) - 1 for r in live)
    print(
        f"\nSMOKE errors={errors}/{RUNS} "
        f"alt_unique={alt_u}/{len(alt_only)} "
        f"live_unique={live_u}/{len(live)} "
        f"live_len_hist={dict(sorted(live_lens.items()))}"
    )
    assert errors == 0, "smoke failed"

    nav = Image.open(ROOT / "nav.png").convert("RGBA")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _render(
        nav,
        alt_only,
        det,
        start,
        goal,
        f"equal-shortest random pick only ({RUNS}, unique={alt_u})",
        "sim_spellbook_alt_only.png",
    )
    _render(
        nav,
        live,
        det,
        start,
        goal,
        f"random shortest + via deform ({RUNS}, unique={live_u})",
        "sim_spellbook_farm_paths.png",
    )
    print("done")


if __name__ == "__main__":
    main()
