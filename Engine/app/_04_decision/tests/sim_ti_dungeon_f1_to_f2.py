"""Simulate Talking Island dungeon F1 walk: entrance → stairs to F2."""
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

ROOT = Path(__file__).resolve().parents[3] / "data" / "maps" / "talking_island_dungeon_F1"
OUT_DIR = ROOT
OX, OY = 32576, 32704
SCALE = 1  # meta pixel_scale=1
RUNS = 30

# Ground enter lands on F1; floor transition tmo:1:5 goes to F2.
ENTRANCE_WORLD = (32668, 32805)
STAIRS_TO_F2_WORLD = (32737, 32877)

COLORS = [
    (255, 70, 70, 210),
    (70, 150, 255, 210),
    (70, 220, 100, 210),
    (255, 190, 50, 210),
    (220, 80, 220, 210),
    (50, 220, 220, 210),
    (255, 120, 40, 210),
    (160, 100, 255, 210),
]


def _snap(terrain, xy, r: int = 8):
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


def _paint(draw, route, color, off=0):
    for tx, ty in route:
        x0 = tx * SCALE + off
        y0 = ty * SCALE + off
        draw.rectangle((x0, y0, x0 + max(SCALE, 1), y0 + max(SCALE, 1)), fill=color)


def main() -> None:
    terrain, *_rest = load_nav_prebuild(ROOT / "nav_prebuild")
    start = _snap(
        terrain, (ENTRANCE_WORLD[0] - OX, ENTRANCE_WORLD[1] - OY), r=12
    )
    goal = _snap(
        terrain, (STAIRS_TO_F2_WORLD[0] - OX, STAIRS_TO_F2_WORLD[1] - OY), r=12
    )
    assert start and goal, (start, goal)
    det = find_path(terrain, start, goal)
    assert det, "no path entrance→stairs"
    alts = list_shortest_paths(terrain, start, goal, max_paths=4)
    print(f"F1 entrance nav={start} world={ENTRANCE_WORLD}")
    print(f"F1 stairs→F2 nav={goal} world={STAIRS_TO_F2_WORLD}")
    print(f"det_steps={len(det)-1} equal_shortest_alts={len(alts)}")

    live = []
    errors = 0
    for i in range(RUNS):
        p = find_path_random_shortest(terrain, start, goal, sticky_path=None)
        try:
            assert p and p[0] == start and p[-1] == goal
            for x, y in p:
                assert terrain.is_walkable(x, y)
            for a, b in zip(p, p[1:]):
                assert terrain.can_step(a[0], a[1], b[0], b[1])
        except AssertionError as exc:
            errors += 1
            print(f"FAIL {i}: {exc}")
            continue
        live.append([(int(x), int(y)) for x, y in p])
        print(
            f"  #{i+1:02d} steps={len(p)-1} unique={len({tuple(r) for r in live})}"
        )

    uniq = len({tuple(r) for r in live})
    lens = Counter(len(r) - 1 for r in live)
    print(f"SMOKE errors={errors}/{RUNS} unique={uniq}/{len(live)} len_hist={dict(sorted(lens.items()))}")
    assert errors == 0

    nav = Image.open(ROOT / "nav.png").convert("RGBA")
    # Upscale for visibility when pixel_scale=1
    zoom = 3
    nav_z = nav.resize((nav.width * zoom, nav.height * zoom), Image.NEAREST)
    overlay = Image.new("RGBA", nav_z.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def zpaint(route, color, off=0):
        for tx, ty in route:
            x0 = tx * zoom + off
            y0 = ty * zoom + off
            draw.rectangle((x0, y0, x0 + zoom - 1, y0 + zoom - 1), fill=color)

    zpaint(det, (255, 255, 255, 110))
    for i, route in enumerate(live):
        zpaint(route, COLORS[i % len(COLORS)], off=i % 2)

    sx = start[0] * zoom + zoom // 2
    sy = start[1] * zoom + zoom // 2
    gx = goal[0] * zoom + zoom // 2
    gy = goal[1] * zoom + zoom // 2
    draw.ellipse((sx - 8, sy - 8, sx + 8, sy + 8), fill=(255, 40, 40, 255))
    draw.text((sx + 12, sy - 10), "F1 entrance", fill=(255, 80, 80, 255))
    draw.ellipse((gx - 8, gy - 8, gx + 8, gy + 8), fill=(40, 220, 80, 255))
    draw.text((gx + 12, gy - 10), "stairs→F2", fill=(80, 255, 80, 255))
    draw.text(
        (12, 12),
        f"TI dungeon F1: entrance→F2 stairs ({RUNS} runs, unique={uniq})",
        fill=(255, 255, 255, 255),
    )

    out = Image.alpha_composite(nav_z, overlay)
    full = OUT_DIR / "sim_f1_entrance_to_f2_stairs.png"
    out.save(full)
    xs = [t[0] * zoom for r in live for t in r] + [sx, gx]
    ys = [t[1] * zoom for r in live for t in r] + [sy, gy]
    pad = 80
    crop = (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(out.width, max(xs) + pad),
        min(out.height, max(ys) + pad),
    )
    crop_path = OUT_DIR / "sim_f1_entrance_to_f2_stairs_crop.png"
    out.crop(crop).save(crop_path)
    print(f"wrote {full}")
    print(f"wrote {crop_path} crop={crop}")


if __name__ == "__main__":
    main()
